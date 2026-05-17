@echo off
REM Windows equivalent of benchmarks/oak_health_insurance/run_app.sh
REM Loads env and runs the Oak Health Insurance FastAPI app on port 8090.

setlocal
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
pushd "%SCRIPT_DIR%\..\.." >nul
set "PROJECT_ROOT=%CD%"
popd >nul

echo Loading Oak Health Insurance configuration...
call "%PROJECT_ROOT%\benchmarks\helpers\load_env.bat" "oak_health_insurance"

echo.
echo Starting FastAPI app...
cd /d "%SCRIPT_DIR%"
uv run uvicorn main:app --reload --port 8090
exit /b %errorlevel%
