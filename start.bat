@echo off
REM Q-Mol one-click local test.
REM Runs: smoke test (5 mols) -> build release bundle -> open landing page.
REM No HuggingFace token needed for this. Nothing is uploaded.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] No virtualenv found. Run setup.ps1 first.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Q-Mol local test
echo ============================================================
echo.
echo [1/3] Smoke test: ingest 5 molecules from PubChem...
echo.
.\.venv\Scripts\python.exe -u smoke_test.py
if errorlevel 1 (
    echo.
    echo [ERROR] Smoke test failed.
    pause
    exit /b 1
)

echo.
echo [2/3] Building release bundle (Parquet + CSV + sample)...
echo.
.\.venv\Scripts\python.exe -u build_release.py
if errorlevel 1 (
    echo.
    echo [ERROR] Release build failed.
    pause
    exit /b 1
)

echo.
echo [3/3] Opening landing page in your browser...
start "" "landing\index.html"

echo.
echo ============================================================
echo  Done. Outputs:
echo    data\qmol.sqlite       - database
echo    data\qmol.parquet      - dataset
echo    release\               - sellable bundle
echo    landing\index.html     - sales page (open in browser)
echo.
echo  To run continuously and grow the dataset:  run_worker.bat
echo  To launch / sell:  see LAUNCH.md
echo ============================================================
echo.
pause
