@echo off
REM Windows equivalent of benchmarks/appworld/run_eval.sh
REM Loads AppWorld env and runs cuga-eval.

setlocal
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
pushd "%SCRIPT_DIR%\..\.." >nul
set "PROJECT_ROOT=%CD%"
popd >nul
call "%PROJECT_ROOT%\benchmarks\helpers\load_env.bat" "appworld"
cuga-eval appworld %*
exit /b %errorlevel%
