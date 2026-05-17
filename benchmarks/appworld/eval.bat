@echo off
REM Windows equivalent of benchmarks/appworld/eval.sh — delegates to bash
REM (traps, kill -0, lsof, process substitution, find with -mindepth).
setlocal
set "_THIS=%~dp0"
if "%_THIS:~-1%"=="\" set "_THIS=%_THIS:~0,-1%"
call "%_THIS%\..\helpers\_delegate_to_bash.bat" "%_THIS%\eval.sh" %*
exit /b %errorlevel%
