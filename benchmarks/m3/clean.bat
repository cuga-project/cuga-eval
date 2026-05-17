@echo off
REM Windows equivalent of benchmarks/m3/clean.sh — delegates to bash.
REM (Uses pkill, lsof, docker exec curl loops, glob removal — POSIX-only.)
setlocal
set "_THIS=%~dp0"
if "%_THIS:~-1%"=="\" set "_THIS=%_THIS:~0,-1%"
call "%_THIS%\..\helpers\_delegate_to_bash.bat" "%_THIS%\clean.sh" %*
exit /b %errorlevel%
