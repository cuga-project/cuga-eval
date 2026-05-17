@echo off
REM Shared helper: invokes a .sh script via Git Bash or WSL, forwarding all args.
REM
REM Usage (from another .bat):
REM   call "<path-to-helpers>\_delegate_to_bash.bat" "<absolute-or-relative-path-to-script.sh>" %*
REM
REM Rationale: many of the .sh scripts in this repo use POSIX-only features
REM (process substitution, traps, lsof, pkill, comm, find -mindepth, mktemp,
REM heredocs, etc.) that don't have clean cmd.exe equivalents. Rather than
REM ship subtly-broken cmd.exe ports, we delegate to a real bash. A native
REM Python port is tracked in the follow-up issue.

setlocal enabledelayedexpansion

if "%~1"=="" (
    echo [ERROR] _delegate_to_bash.bat called without a script path
    exit /b 2
)
set "_SCRIPT=%~1"
shift

if not exist "%_SCRIPT%" (
    echo [ERROR] Script not found: %_SCRIPT%
    exit /b 2
)

REM Try Git Bash in well-known install locations
for %%G in (
    "%ProgramFiles%\Git\bin\bash.exe"
    "%ProgramFiles(x86)%\Git\bin\bash.exe"
    "%LocalAppData%\Programs\Git\bin\bash.exe"
) do (
    if exist %%G (
        %%G "%_SCRIPT%" %*
        exit /b !errorlevel!
    )
)

REM Then any bash on PATH (e.g. msys2, cygwin)
where bash >nul 2>&1
if not errorlevel 1 (
    bash "%_SCRIPT%" %*
    exit /b !errorlevel!
)

REM Finally WSL
where wsl >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%P in ('wsl wslpath -u "%_SCRIPT%" 2^>nul') do set "_WSL_SCRIPT=%%P"
    if not "!_WSL_SCRIPT!"=="" (
        wsl bash "!_WSL_SCRIPT!" %*
        exit /b !errorlevel!
    )
)

echo [ERROR] No bash interpreter found on this system.
echo This script requires bash. Install one of:
echo   - Git for Windows ^(provides Git Bash^): https://git-scm.com/download/win
echo   - WSL ^(Windows Subsystem for Linux^):   wsl --install
exit /b 1
