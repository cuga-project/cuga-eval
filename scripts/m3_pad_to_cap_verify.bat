@echo off
REM Windows equivalent of scripts/m3_pad_to_cap_verify.sh — delegates to bash.
REM
REM This script uses tee, mktemp, embedded Python heredoc, gh api PATCH with
REM @file body, process substitution, and signal traps. None of these have
REM clean cmd.exe equivalents. Use Git Bash or WSL.
setlocal
set "_THIS=%~dp0"
if "%_THIS:~-1%"=="\" set "_THIS=%_THIS:~0,-1%"
call "%_THIS%\..\benchmarks\helpers\_delegate_to_bash.bat" "%_THIS%\m3_pad_to_cap_verify.sh" %*
exit /b %errorlevel%
