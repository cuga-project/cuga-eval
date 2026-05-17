@echo off
REM Windows equivalent of load_env.sh
REM
REM Usage: call load_env.bat [benchmark_name]
REM
REM Sourcing semantics: this script writes a temporary .bat snippet of `set`
REM commands and calls it, so env vars persist into the caller's scope when
REM invoked via `call`.

setlocal enabledelayedexpansion

set "BENCHMARK_NAME=%~1"

set "HELPERS_DIR=%~dp0"
if "%HELPERS_DIR:~-1%"=="\" set "HELPERS_DIR=%HELPERS_DIR:~0,-1%"
pushd "%HELPERS_DIR%\..\.." >nul
set "PROJECT_ROOT=%CD%"
popd >nul
set "CONFIG_DIR=%PROJECT_ROOT%\config"

REM Temp file holds the set-commands we'll call from the caller's scope
set "_SETS=%TEMP%\cuga_loadenv_%RANDOM%_%RANDOM%.bat"
echo @echo off> "%_SETS%"

call :emit_env_file "%PROJECT_ROOT%\.env"            ".env (secrets)"
call :emit_env_file "%CONFIG_DIR%\global.env"        "global.env"
if not "%BENCHMARK_NAME%"=="" (
    call :emit_env_file "%PROJECT_ROOT%\benchmarks\%BENCHMARK_NAME%\config\%BENCHMARK_NAME%.env" "%BENCHMARK_NAME%.env"
)

REM Default LOGURU_LEVEL handling
if "%LOGURU_LEVEL%"=="" echo set "LOGURU_LEVEL=WARNING">> "%_SETS%"
if /i "%VERBOSE%"=="true" echo set "LOGURU_LEVEL=DEBUG">> "%_SETS%"

REM Single-line endlocal so %_SETS% is expanded at parse time (before endlocal runs)
endlocal & call "%_SETS%" & del "%_SETS%" 2>nul
exit /b 0

:emit_env_file
set "_FILE=%~1"
set "_LABEL=%~2"
if not exist "%_FILE%" (
    if not "%_LABEL%"=="" echo (skipping missing %_LABEL%)
    exit /b 0
)
echo [ok] Loading %_LABEL%
for /f "usebackq tokens=* eol=#" %%L in ("%_FILE%") do (
    set "_line=%%L"
    if not "!_line!"=="" (
        for /f "tokens=1,* delims==" %%A in ("!_line!") do (
            echo set "%%A=%%B">> "%_SETS%"
        )
    )
)
exit /b 0
