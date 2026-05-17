@echo off
REM Windows equivalent of benchmarks/m3/eval.sh
REM Delegates to bash (Git Bash / WSL) because the script uses POSIX features
REM that don't translate cleanly to cmd.exe (traps, lsof, process subs, ...).
REM Tracked in the follow-up issue: migrate these to Python.

setlocal
set "_THIS=%~dp0"
if "%_THIS:~-1%"=="\" set "_THIS=%_THIS:~0,-1%"
call "%_THIS%\..\helpers\_delegate_to_bash.bat" "%_THIS%\eval.sh" %*
exit /b %errorlevel%
