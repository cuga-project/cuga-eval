@echo off
REM Placeholder for benchmarks/helpers/common.sh.
REM
REM common.sh is a bash function library (port_in_use, wait_for_server,
REM parse_common_args, cleanup_pids, etc.) that gets sourced by other .sh
REM scripts. There's no equivalent of `source` for function definitions in
REM cmd.exe, so a direct port is not feasible.
REM
REM In practice, this file is never called directly: the heavy .bat files
REM in this repo (eval.bat, compare.bat, etc.) delegate to bash via
REM _delegate_to_bash.bat, and bash sources common.sh itself.
REM
REM If you ARE invoking this file directly, you probably want one of:
REM   - call _delegate_to_bash.bat ".\common.sh" ^<args^>    (run from bash)
REM   - Use Git Bash or WSL to source it the normal way
REM
REM See the follow-up issue for the Python migration that removes this gap.

if "%~1"=="" (
    echo common.bat is a placeholder. See comment block in this file.
    exit /b 0
)
echo [WARN] common.bat does not implement %~1 in cmd.exe. Use bash to source common.sh.
exit /b 1
