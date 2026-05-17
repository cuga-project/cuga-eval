@echo off
REM Windows equivalent of benchmarks/m3/analyze.sh
REM Thin wrapper around scripts/analyze.bat with --benchmark m3.

setlocal
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
call "%SCRIPT_DIR%\..\..\scripts\analyze.bat" --benchmark m3 %*
exit /b %errorlevel%
