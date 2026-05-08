# One-shot setup script for Windows PowerShell
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtualenv..."
    python -m venv .venv
}

Write-Host "Installing dependencies..."
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host ""
    Write-Host "Created .env — open it and fill in HF_TOKEN + HF_REPO_ID." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup complete. Run:   .\run_worker.bat" -ForegroundColor Green
