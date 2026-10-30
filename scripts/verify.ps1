$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

.\.venv\Scripts\python.exe -m compileall .\backend\src
.\.venv\Scripts\elysian.exe status

Push-Location .\frontend
npm run build
Pop-Location
