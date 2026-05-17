@echo off
REM Windows equivalent of benchmarks/appworld/run_app.sh
REM Loads env and starts AppWorld.

setlocal
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
pushd "%SCRIPT_DIR%\..\.." >nul
set "PROJECT_ROOT=%CD%"
popd >nul

echo Loading AppWorld configuration...
call "%PROJECT_ROOT%\benchmarks\helpers\load_env.bat" "appworld"

echo.
echo Starting AppWorld...
cd /d "%PROJECT_ROOT%"
uv run cuga start appworld
exit /b %errorlevel%
