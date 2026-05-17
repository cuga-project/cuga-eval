@echo off
REM Windows equivalent of setup_m3_eval.sh — delegates to bash (uses
REM interactive prompts, docker detection, file edits — bash-only).
setlocal
set "_THIS=%~dp0"
if "%_THIS:~-1%"=="\" set "_THIS=%_THIS:~0,-1%"
call "%_THIS%\..\..\..\helpers\_delegate_to_bash.bat" "%_THIS%\setup_m3_eval.sh" %*
exit /b %errorlevel%
