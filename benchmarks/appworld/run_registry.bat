@echo off
REM Windows equivalent of benchmarks/appworld/run_registry.sh
REM Delegates to the generic helper.
setlocal
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
call "%SCRIPT_DIR%\..\helpers\run_registry.bat" "appworld"
exit /b %errorlevel%
