@echo off
REM Windows equivalent of run_registry.sh
REM Loads env (global + benchmark-specific) and starts the registry server.
REM Usage: run_registry.bat ^<benchmark_name^>

setlocal

set "BENCHMARK_NAME=%~1"
if "%BENCHMARK_NAME%"=="" (
    echo Usage: %~nx0 ^<benchmark_name^>
    echo Example: %~nx0 m3
    exit /b 1
)

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
pushd "%SCRIPT_DIR%\..\.." >nul
set "PROJECT_ROOT=%CD%"
popd >nul

echo Loading %BENCHMARK_NAME% evaluation configuration...
call "%SCRIPT_DIR%\load_env.bat" "%BENCHMARK_NAME%"

echo.
echo Starting registry server...
cd /d "%PROJECT_ROOT%"
uv run registry
exit /b %errorlevel%
