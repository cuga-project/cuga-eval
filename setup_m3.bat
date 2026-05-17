@echo off
REM Windows equivalent of setup_m3.sh
REM
REM Clones vakra into vendor\, sets up Python venv, installs deps, downloads
REM benchmark data, builds Docker image, starts containers.
REM
REM Requires: git, docker or podman, python (with venv), HF_TOKEN env var.

setlocal enabledelayedexpansion

set "REPO_URL=https://github.com/IBM/vakra.git"
set "VENDOR_DIR=.\vendor"
set "REPO_NAME=vakra"
set "REPO_PATH=%VENDOR_DIR%\%REPO_NAME%"
set "DATA_DIR=%REPO_PATH%\data"

REM Mode flags
set "DOWNLOAD_ONLY=false"
set "BUILD_ONLY=false"
set "START_ONLY=false"
set "VERIFY_ONLY=false"
set "SKIP_DOWNLOAD=false"

:parse_args
if "%~1"=="" goto args_done
if "%~1"=="--download-only" (set "DOWNLOAD_ONLY=true" & shift & goto parse_args)
if "%~1"=="--build-only"    (set "BUILD_ONLY=true"    & shift & goto parse_args)
if "%~1"=="--start-only"    (set "START_ONLY=true"    & shift & goto parse_args)
if "%~1"=="--verify"        (set "VERIFY_ONLY=true"   & shift & goto parse_args)
if "%~1"=="--skip-download" (set "SKIP_DOWNLOAD=true" & shift & goto parse_args)
if "%~1"=="--help" goto show_usage
echo [ERROR] Unknown option: %~1
goto show_usage

:show_usage
echo Usage: %~nx0 [OPTIONS]
echo.
echo Options:
echo   --download-only Download data only (no build/start)
echo   --build-only    Only build image, don't start containers
echo   --start-only    Only start containers (assumes already built)
echo   --verify        Only verify containers are running
echo   --skip-download Skip data download step
echo   --help          Show this help message
exit /b 0

:args_done
echo ============================================================
echo               Vakra Benchmark Setup Script
echo ============================================================
echo.

REM Check prerequisites
where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Missing required dependency: git
    exit /b 1
)
set "RUNTIME="
where docker >nul 2>&1 && set "RUNTIME=docker"
if "%RUNTIME%"=="" where podman >nul 2>&1 && set "RUNTIME=podman"
if "%RUNTIME%"=="" (
    echo [ERROR] Missing required dependency: docker or podman
    exit /b 1
)
echo [INFO] Using container runtime: %RUNTIME%

if "%VERIFY_ONLY%"=="true" (
    call :verify_containers
    exit /b !errorlevel!
)

if "%START_ONLY%"=="true" (
    call :start_containers || exit /b 1
    call :verify_containers
    exit /b !errorlevel!
)

REM Step 1: Clone or update repo
if not exist "%VENDOR_DIR%\" (
    echo [INFO] Creating vendor directory...
    mkdir "%VENDOR_DIR%"
)
if exist "%REPO_PATH%\.git" (
    echo [INFO] Repository already exists at %REPO_PATH%, pulling latest...
    pushd "%REPO_PATH%" || exit /b 1
    git pull origin main 2>nul || git pull origin master 2>nul
    if errorlevel 1 echo [WARNING] Could not update repository
    popd
) else if exist "%REPO_PATH%\" (
    echo [WARNING] Directory exists but is not a git repository. Removing and cloning fresh...
    rmdir /s /q "%REPO_PATH%"
    call :clone_repo || exit /b 1
) else (
    call :clone_repo || exit /b 1
)

REM Step 2: Python env + install deps
echo [INFO] Step 2: Installing Python dependencies...
pushd "%REPO_PATH%" || exit /b 1
if not exist ".venv\" (
    echo [INFO] Creating Python virtual environment...
    python -m venv .venv || (echo [ERROR] Failed to create venv & popd & exit /b 1)
)
echo [INFO] Activating virtual environment and installing vakra...
call .venv\Scripts\activate.bat
pip install -e ".[init]" || (echo [ERROR] vakra install failed & popd & exit /b 1)
pip install -r requirements_benchmark.txt || (echo [ERROR] benchmark deps install failed & popd & exit /b 1)
popd

REM Step 3: Download data
if "%SKIP_DOWNLOAD%"=="false" (
    if not exist "%DATA_DIR%\" (
        call :download_data || exit /b 1
    ) else (
        dir /b /a "%DATA_DIR%" >nul 2>&1
        if errorlevel 1 (
            call :download_data || exit /b 1
        ) else (
            echo [INFO] Data directory exists and is not empty, skipping download
        )
    )
)

if "%DOWNLOAD_ONLY%"=="true" (
    echo [SUCCESS] Setup and data download completed!
    exit /b 0
)

REM Build + start
call :build_image || exit /b 1
if "%BUILD_ONLY%"=="false" (
    call :start_containers
    call :verify_containers
)

echo.
echo [SUCCESS] Vakra setup completed successfully!
echo.
echo Container Information:
echo   * capability_1_bi_apis - Tool Chaining MCP Server
echo   * capability_2_dashboard_apis - Tool Selection MCP Server
echo   * capability_3_multihop_reasoning - Multi-hop Reasoning MCP Server
echo   * capability_4_multiturn - Multi-hop Multi-Source MCP Server
exit /b 0

:clone_repo
echo [INFO] Cloning %REPO_URL%...
git clone "%REPO_URL%" "%REPO_PATH%"
if errorlevel 1 (
    echo [ERROR] Failed to clone repository. Check SSH keys / network.
    exit /b 1
)
echo [SUCCESS] Repository cloned successfully
exit /b 0

:download_data
echo [INFO] Downloading benchmark data from HuggingFace (~30 GB)...
if "%HF_TOKEN%"=="" (
    echo [ERROR] HF_TOKEN environment variable is not set
    echo Set it with: set HF_TOKEN=hf_your_token_here
    echo Get your token from: https://huggingface.co/settings/tokens
    exit /b 1
)
pushd "%REPO_PATH%" || exit /b 1
if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat
where make >nul 2>&1
if not errorlevel 1 (
    make download
) else (
    python benchmark_setup.py --download-data
)
if errorlevel 1 (
    echo [ERROR] Failed to download data
    popd
    exit /b 1
)
popd
echo [SUCCESS] Data downloaded successfully
exit /b 0

:build_image
echo [INFO] Building vakra Docker image using %RUNTIME%...
pushd "%REPO_PATH%" || exit /b 1
where make >nul 2>&1
if not errorlevel 1 (
    set "DOCKER=%RUNTIME%" && make build
) else (
    %RUNTIME% build -t m3_environ -f docker/Dockerfile.unified .
)
if errorlevel 1 (
    echo [ERROR] Failed to build image
    popd
    exit /b 1
)
popd
echo [SUCCESS] Image built successfully
exit /b 0

:start_containers
echo [INFO] Starting containers using %RUNTIME% compose...
pushd "%REPO_PATH%" || exit /b 1
where make >nul 2>&1
if not errorlevel 1 (
    set "DOCKER=%RUNTIME%" && make start
) else (
    %RUNTIME% compose up -d
)
if errorlevel 1 (
    echo [ERROR] Failed to start containers
    popd
    exit /b 1
)
popd
echo [SUCCESS] Containers started successfully
exit /b 0

:verify_containers
echo [INFO] Verifying containers...
%RUNTIME% ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
for /f %%C in ('%RUNTIME% ps --format "{{.Names}}" ^| findstr /c:"capability_" /c:"" ^| find /c "capability_"') do set "RUNNING=%%C"
if "%RUNNING%"=="" set "RUNNING=0"
if %RUNNING% GEQ 4 (
    echo [SUCCESS] Found %RUNNING% capability containers running
    exit /b 0
) else (
    echo [WARNING] Only %RUNNING% capability containers running (expected 4)
    exit /b 1
)
