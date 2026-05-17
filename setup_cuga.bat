@echo off
REM Windows equivalent of setup_cuga.sh
REM Clones cuga-agent next to this repo (matches pyproject.toml path "../cuga-agent")
REM and sets up environment variables for the current session.
REM
REM Note: env vars set here only persist for this cmd.exe session.
REM See the follow-up issue tracking conversion of these scripts to Python.

setlocal

set "REPO_URL=https://github.com/cuga-project/cuga-agent.git"
set "REPO_BRANCH=main"
set "SCRIPT_DIR=%~dp0"
REM strip trailing backslash from %~dp0
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
pushd "%SCRIPT_DIR%\.." >nul || (echo [ERROR] Could not access parent of %SCRIPT_DIR% & exit /b 1)
set "PARENT_DIR=%CD%"
popd >nul
set "REPO_NAME=cuga-agent"
set "REPO_PATH=%PARENT_DIR%\%REPO_NAME%"

echo ============================================================
echo                    CUGA Agent Setup Script
echo ============================================================
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git is not installed. Please install git and try again.
    exit /b 1
)

if exist "%REPO_PATH%\.git" (
    echo [INFO] Repository already exists at %REPO_PATH%
    echo [INFO] Pulling latest changes from branch: %REPO_BRANCH%...
    pushd "%REPO_PATH%" || exit /b 1
    git fetch origin && git checkout "%REPO_BRANCH%" && git pull origin "%REPO_BRANCH%"
    if errorlevel 1 echo [WARNING] Could not update repository. You may need to resolve conflicts manually.
    popd
) else if exist "%REPO_PATH%\" (
    echo [WARNING] Directory exists but is not a git repository. Removing and cloning fresh...
    rmdir /s /q "%REPO_PATH%"
    call :clone_repo || exit /b 1
) else (
    call :clone_repo || exit /b 1
)

echo [INFO] Exporting environment variables...
endlocal & (
    set "ENV_FILE=.\.env"
    set "MCP_SERVERS_FILE=.\mcp_servers.yaml"
    set "CUGA_LOGGING_DIR=.\logging"
    echo [INFO] Exported ENV_FILE=.\.env
    echo [INFO] Exported MCP_SERVERS_FILE=.\mcp_servers.yaml
    echo [INFO] Exported CUGA_LOGGING_DIR=.\logging
)

if not exist ".\logging" (
    echo [INFO] Creating logging directory...
    mkdir ".\logging"
)

REM Optionally run AppWorld setup if the script exists
if exist "%~dp0setup_appworld.bat" (
    echo [INFO] Running AppWorld setup...
    call "%~dp0setup_appworld.bat"
    if errorlevel 1 (
        echo [ERROR] AppWorld setup failed
        exit /b 1
    )
) else (
    echo [WARNING] AppWorld setup script not found. Skipping.
)

echo.
echo [SUCCESS] Setup completed successfully!
echo.
echo Next steps:
echo   1. Check the cloned repository at: %REPO_PATH%
echo   2. Environment variables are now available in this terminal session
echo   3. Note: Variables will only persist for this terminal session
echo.
exit /b 0

:clone_repo
echo [INFO] Cloning %REPO_URL% (branch: %REPO_BRANCH%)...
git clone -b "%REPO_BRANCH%" "%REPO_URL%" "%REPO_PATH%"
if errorlevel 1 (
    echo [ERROR] Failed to clone repository. Please check your SSH keys and network connection.
    exit /b 1
)
echo [SUCCESS] Repository cloned successfully to %REPO_PATH%
exit /b 0
