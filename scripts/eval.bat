@echo off
REM Windows equivalent of scripts/eval.sh — delegates to bash because the
REM script sources common.sh (a bash function library: parse_common_args,
REM apply_model_profile_if_set, check_langfuse_env, list_benchmarks).
setlocal
set "_THIS=%~dp0"
if "%_THIS:~-1%"=="\" set "_THIS=%_THIS:~0,-1%"
call "%_THIS%\..\benchmarks\helpers\_delegate_to_bash.bat" "%_THIS%\eval.sh" %*
exit /b %errorlevel%
