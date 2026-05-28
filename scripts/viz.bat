@echo off
REM Windows equivalent of viz.sh
REM Loads benchmark env and runs cuga viz against the trajectory_data dir.

setlocal enabledelayedexpansion

set "BENCHMARK_NAME=%~1"
if "%BENCHMARK_NAME%"=="" (
    echo Usage: %~nx0 ^<benchmark_name^>
    echo Example: %~nx0 m3
    exit /b 1
)

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
pushd "%SCRIPT_DIR%\.." >nul
set "PROJECT_ROOT=%CD%"
popd >nul

echo Loading %BENCHMARK_NAME% visualization configuration...
call "%PROJECT_ROOT%\benchmarks\helpers\load_env.bat" "%BENCHMARK_NAME%"

echo.
echo Running cuga viz...
cd /d "%PROJECT_ROOT%"
uv run cuga-viz run %CUGA_LOGGING_DIR%\trajectory_data\
exit /b %errorlevel%
