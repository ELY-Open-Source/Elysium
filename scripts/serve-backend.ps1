$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)
.\.venv\Scripts\elysium.exe serve --host 127.0.0.1 --port 8765
