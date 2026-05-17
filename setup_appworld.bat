@echo off
REM Windows equivalent of setup_appworld.sh
REM
REM Sources the appworld env file (set -a equivalent), then installs AppWorld
REM via uv. Interactive reinstall prompt preserved.

setlocal enabledelayedexpansion

set "APPWORLD_DIR=benchmarks\appworld"
set "APPWORLD_ENV_FILE=benchmarks\appworld\config\appworld.env"
set "APPWORLD_REPO_DIR=%APPWORLD_DIR%\appworld"
set "APPWORLD_DATA_DIR=%APPWORLD_REPO_DIR%\data"

if not exist "%APPWORLD_DIR%\" (
    echo Error: '%APPWORLD_DIR%' directory not found!
    echo Please clone the repository first
    exit /b 1
)

if not exist "%APPWORLD_ENV_FILE%" (
    echo Error: '%APPWORLD_ENV_FILE%' file not found!
    exit /b 1
)

REM Load env file: each non-comment KEY=VALUE line becomes a set
for /f "usebackq tokens=* eol=#" %%L in ("%APPWORLD_ENV_FILE%") do (
    set "_line=%%L"
    if not "!_line!"=="" (
        for /f "tokens=1,* delims==" %%A in ("!_line!") do (
            set "%%A=%%B"
        )
    )
)

if not exist "%APPWORLD_REPO_DIR%\" (
    echo Error: '%APPWORLD_REPO_DIR%' directory not found!
    echo Please clone the AppWorld repository into '%APPWORLD_REPO_DIR%' first
    exit /b 1
)

if exist "%APPWORLD_DATA_DIR%\" (
    echo AppWorld repository already present at '%APPWORLD_REPO_DIR%'.
    echo AppWorld data already exists at '%APPWORLD_DATA_DIR%'.
    set /p REINSTALL="Would you like to reinstall AppWorld and re-download the data? [y/N] "
    if /i not "!REINSTALL!"=="y" if /i not "!REINSTALL!"=="yes" (
        echo Keeping existing AppWorld installation and data. Skipping setup.
        exit /b 0
    )
    echo Reinstalling AppWorld and downloading data...
)

pushd "%APPWORLD_REPO_DIR%" || exit /b 1
uv pip install .                || (popd & exit /b 1)
uv run -m appworld.cli install  || (popd & exit /b 1)
uv run appworld install --repo  || (popd & exit /b 1)
uv run appworld download data   || (popd & exit /b 1)
popd
exit /b 0
