$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)
Push-Location .\frontend
pnpm dev
Pop-Location
