@echo off
REM Run the Q-Mol worker. Windows Task Scheduler can invoke this at boot.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo ERROR: .venv not found. Run setup.ps1 first.
    exit /b 1
)
.venv\Scripts\python.exe worker.py
