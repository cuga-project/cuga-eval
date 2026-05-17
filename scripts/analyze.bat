@echo off
REM Windows equivalent of scripts/analyze.sh — delegates to bash (uses
REM bash arrays for --bundles / --task-ids, sources config .conf via source).
setlocal
set "_THIS=%~dp0"
if "%_THIS:~-1%"=="\" set "_THIS=%_THIS:~0,-1%"
call "%_THIS%\..\benchmarks\helpers\_delegate_to_bash.bat" "%_THIS%\analyze.sh" %*
exit /b %errorlevel%
