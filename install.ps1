#requires -version 5.1
# Elysian in one command, on Windows:
#
#   irm https://raw.githubusercontent.com/ELY-Open-Source/Elysian/main/install.ps1 | iex
#
# It installs uv if it is missing, Elysian with its own Python, the store in ~\.elysian (or
# ELYSIAN_HOME) with an operator token, the checksum-verified MCP server, and registers that
# server with every coding agent it finds. Run from a checkout with -Source to install the
# backend and build the MCP server from that checkout instead (needs Go 1.25).
[CmdletBinding()]
param(
  [switch]$Source,
  [string]$Version = ""
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Repo = "ELY-Open-Source/Elysian"

function Step($text) { Write-Host "==> $text" }

function Invoke-Checked {
  param([string]$Program, [string[]]$Arguments)
  & $Program @Arguments
  if ($LASTEXITCODE -ne 0) { throw "$Program $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

function Get-Platform {
  # PROCESSOR_ARCHITEW6432 holds the machine's architecture under x64 emulation on ARM64.
  $arch = $env:PROCESSOR_ARCHITEW6432
  if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
  switch ($arch) {
    "AMD64" { return "windows_amd64" }
    "ARM64" { return "windows_arm64" }
    default { throw "unsupported architecture: $arch" }
  }
}

$Checkout = ""
if ($PSScriptRoot -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot "backend\pyproject.toml"))) { $Checkout = $PSScriptRoot }
if ($Source) {
  if (-not $Checkout) { throw "-Source must run from a checkout" }
  if (-not (Get-Command go -ErrorAction SilentlyContinue)) { throw "-Source needs Go 1.25 or newer" }
}
elseif (-not $Version) {
  $releases = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases" -Headers @{ "User-Agent" = "elysian-installer" }
  $Version = ($releases | Where-Object { $_.tag_name -like "mcp-*" } | Select-Object -First 1).tag_name
  if (-not $Version) { throw "no mcp-* release found for $Repo" }
}

Step "uv"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  $env:UV_INSTALL_DIR = Join-Path $HOME ".local\bin"
  Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
  $env:Path = "$env:UV_INSTALL_DIR;$env:Path"
}
$Uv = (Get-Command uv).Source

# The API a previous install started holds the old files; stop it before uv replaces them.
# Same rule as the backend's absolute_home: ELYSIAN_HOME with ~ expanded, made absolute, else ~\.elysian.
$OldHome = $env:ELYSIAN_HOME
if (-not $OldHome) { $OldHome = Join-Path $HOME ".elysian" }
if ($OldHome -eq "~" -or $OldHome.StartsWith("~/") -or $OldHome.StartsWith("~\")) { $OldHome = Join-Path $HOME $OldHome.Substring(1).TrimStart("/", "\") }
$OldHome = [IO.Path]::GetFullPath([IO.Path]::Combine((Get-Location).Path, $OldHome)).TrimEnd("\", "/")
$Beside = Join-Path $OldHome "bin\elysian.exe"
Get-CimInstance Win32_Process -Filter "Name = 'elysian.exe'" | Where-Object { $_.ExecutablePath -eq $Beside } | ForEach-Object {
  Stop-Process -Id $_.ProcessId -Force
  Wait-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
  Write-Host "stopped the running API (pid $($_.ProcessId)); restart your agents to reconnect"
}
Step "Elysian and its Python"
# rapidocr pulls the GUI build of OpenCV; the headless build Elysian lists serves the same cv2.
$Excludes = [IO.Path]::GetTempFileName()
Set-Content -LiteralPath $Excludes -Value "opencv-python"
if ($Source) {
  Invoke-Checked $Uv @("tool", "install", "--python", "3.12", "--reinstall", "--excludes", $Excludes, (Join-Path $Checkout "backend"))
}
else {
  Invoke-Checked $Uv @("tool", "install", "--python", "3.12", "--reinstall", "--excludes", $Excludes, "elysian @ https://github.com/$Repo/archive/refs/tags/$Version.tar.gz#subdirectory=backend")
}
Remove-Item -LiteralPath $Excludes
$Elysian = Join-Path (& $Uv tool dir --bin) "elysian.exe"
if (-not (Test-Path -LiteralPath $Elysian)) { throw "uv did not install $Elysian" }

Step "The store and its operator token"
$Init = & $Elysian init
if ($LASTEXITCODE -ne 0) { throw "elysian init failed with exit code $LASTEXITCODE" }
$Init | Write-Host
$HomeDir = ($Init | Out-String | ConvertFrom-Json).home
$BinDir = Join-Path $HomeDir "bin"
[IO.Directory]::CreateDirectory($BinDir) | Out-Null
$Mcp = Join-Path $BinDir "elysian-mcp.exe"
$Fresh = "$Mcp.new"
$Start = Join-Path $BinDir "elysian-start.exe"
$FreshStart = "$Start.new"

Step "The MCP server"
if ($Source) {
  Push-Location -LiteralPath (Join-Path $Checkout "elysian-mcp")
  try {
    $env:CGO_ENABLED = "0"
    Invoke-Checked "go" @("build", "-trimpath", "-ldflags=-s -w", "-o", $Fresh, ".\cmd\elysian-mcp")
    Invoke-Checked "go" @("build", "-trimpath", "-ldflags=-s -w -H=windowsgui", "-o", $FreshStart, ".\cmd\elysian-start")
  }
  finally { Pop-Location }
}
else {
  $asset = "elysian-mcp_$(Get-Platform).zip"
  $base = "https://github.com/$Repo/releases/download/$Version"
  $tmp = Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString())
  [IO.Directory]::CreateDirectory($tmp) | Out-Null
  try {
    # .NET file calls take paths literally; a [ in a user name breaks the cmdlets' wildcard paths.
    $web = New-Object Net.WebClient
    $web.DownloadFile("$base/$asset", (Join-Path $tmp $asset))
    $web.DownloadFile("$base/elysian-mcp_SHA256SUMS.txt", (Join-Path $tmp "SHA256SUMS"))
    $line = Select-String -LiteralPath (Join-Path $tmp "SHA256SUMS") -Pattern ("\*?" + [Regex]::Escape($asset) + "$") | Select-Object -First 1
    if (-not $line) { throw "no checksum for $asset in $Version" }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $tmp $asset)).Hash
    if (($line.Line -split "\s+")[0].ToLower() -ne $actual.ToLower()) { throw "checksum mismatch for $asset" }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory((Join-Path $tmp $asset), (Join-Path $tmp "x"))
    [IO.File]::Delete($Fresh)
    [IO.File]::Move((Join-Path $tmp "x\elysian-mcp.exe"), $Fresh)
    [IO.File]::Delete($FreshStart)
    [IO.File]::Move((Join-Path $tmp "x\elysian-start.exe"), $FreshStart)
  }
  finally { Remove-Item -Recurse -Force -LiteralPath $tmp }
}
# The new binary is in hand; a connected agent keeps the old one open, which Windows lets be renamed, not replaced.
if (Test-Path -LiteralPath $Mcp) {
  $Retired = "$Mcp.old"
  if (Test-Path -LiteralPath $Retired) {
    try { [IO.File]::Delete($Retired) }
    catch { throw "$Retired is still held by an agent from an earlier upgrade; close your agents and run again" }
  }
  [IO.File]::Move($Mcp, $Retired)
}
[IO.File]::Move($Fresh, $Mcp)
[IO.File]::Delete($Start)
[IO.File]::Move($FreshStart, $Start)
# The MCP server starts the API from the elysian beside it; a client's PATH may not hold uv's bin.
[IO.File]::Copy($Elysian, (Join-Path $BinDir "elysian.exe"), $true)

Step "Start at sign-in"
# A GUI-subsystem program, so sign-in opens no console; it starts the API hidden and exits.
$Run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
Set-ItemProperty -Path $Run -Name "Elysian" -Value "`"$Start`" --home `"$HomeDir`""
# -Wait would also wait on the API it leaves running.
$started = Start-Process -FilePath $Start -ArgumentList @("--home", "`"$HomeDir`"") -PassThru
$started.WaitForExit()
if ($started.ExitCode -ne 0) { throw "elysian-start exited $($started.ExitCode); see $(Join-Path $HomeDir 'logs\start.log')" }
Write-Host "the API is running and starts at every sign-in ($Run\Elysian)"

Step "Coding agents"
Invoke-Checked $Mcp @("setup")

Step "Done"
Write-Host "Memory lives in $HomeDir. The MCP server is $Mcp; it starts the API itself whenever the API is down."
Write-Host "Any other MCP client: paste the any_other_client entry printed above into its MCP config."
Write-Host "Restart your agents to load it. The CLI is $Elysian; run ``uv tool update-shell`` to put it on PATH."
