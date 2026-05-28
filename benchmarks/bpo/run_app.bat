@echo off
REM Windows equivalent of benchmarks/bpo/run_app.sh
REM Loads env and runs the BPO FastAPI app on port 8095.

setlocal
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
pushd "%SCRIPT_DIR%\..\.." >nul
set "PROJECT_ROOT=%CD%"
popd >nul

echo Loading BPO configuration...
call "%PROJECT_ROOT%\benchmarks\helpers\load_env.bat" "bpo"

echo.
echo Starting BPO FastAPI app on port 8095...
cd /d "%PROJECT_ROOT%"
uv run uvicorn benchmarks.bpo.main:app --reload --port 8095
exit /b %errorlevel%
