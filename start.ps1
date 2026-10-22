$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv-win\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv-win
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
}
& $pythonPath -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host 'Open http://127.0.0.1:8000 to use the workspace.' -ForegroundColor Green
if (Test-Path -LiteralPath '.env') {
    & $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --env-file .env
} else {
    & $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8000
}
