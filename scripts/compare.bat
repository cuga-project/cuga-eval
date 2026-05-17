@echo off
REM Windows equivalent of scripts/compare.sh — delegates to bash (sources common.sh).
setlocal
set "_THIS=%~dp0"
if "%_THIS:~-1%"=="\" set "_THIS=%_THIS:~0,-1%"
call "%_THIS%\..\benchmarks\helpers\_delegate_to_bash.bat" "%_THIS%\compare.sh" %*
exit /b %errorlevel%
