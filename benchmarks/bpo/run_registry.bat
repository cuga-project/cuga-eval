@echo off
REM Windows equivalent of benchmarks/bpo/run_registry.sh
setlocal
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
call "%SCRIPT_DIR%\..\helpers\run_registry.bat" "bpo"
exit /b %errorlevel%
