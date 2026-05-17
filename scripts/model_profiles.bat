@echo off
REM Windows equivalent of model_profiles.sh
REM Usage: call model_profiles.bat ^<profile_name^>
REM Sets AGENT_SETTING_CONFIG, MODEL_NAME, OPENAI_BASE_URL, OPENAI_API_VERSION.

setlocal
set "PROFILE=%~1"

set "_AGENT_SETTING="
set "_MODEL_NAME="
set "_BASE_URL="
set "_API_VERSION="
set "_RC=0"

if "%PROFILE%"=="" goto done
if /i "%PROFILE%"=="gpt-oss" (
    set "_AGENT_SETTING=settings.groq.toml"
    set "_MODEL_NAME=openai/gpt-oss-120b"
    echo [OK] Model profile: gpt-oss
    goto done
)
if /i "%PROFILE%"=="gpt4o" (
    set "_AGENT_SETTING=settings.openai.toml"
    set "_MODEL_NAME=Azure/gpt-4o"
    set "_BASE_URL=https://ete-litellm.bx.cloud9.ibm.com"
    set "_API_VERSION=2024-08-06"
    echo [OK] Model profile: gpt4o ^(Azure/gpt-4o^)
    goto done
)
if /i "%PROFILE%"=="gpt4.1" (
    set "_AGENT_SETTING=settings.openai.toml"
    set "_MODEL_NAME=Azure/gpt-4.1"
    set "_BASE_URL=https://ete-litellm.bx.cloud9.ibm.com"
    set "_API_VERSION=2024-08-06"
    echo [OK] Model profile: gpt4.1 ^(Azure/gpt-4.1^)
    goto done
)
if /i "%PROFILE%"=="opus4.5" (
    set "_AGENT_SETTING=settings.openai.toml"
    set "_MODEL_NAME=claude-opus-4-5-20251101"
    set "_BASE_URL=https://ete-litellm.bx.cloud9.ibm.com"
    echo [OK] Model profile: opus4.5
    goto done
)
echo [ERROR] Unknown model profile '%PROFILE%'
echo Valid values: gpt-oss, gpt4o, gpt4.1, opus4.5
set "_RC=1"

:done
endlocal & (
    if not "%_AGENT_SETTING%"=="" set "AGENT_SETTING_CONFIG=%_AGENT_SETTING%"
    if not "%_MODEL_NAME%"=="" set "MODEL_NAME=%_MODEL_NAME%"
    if not "%_BASE_URL%"=="" (set "OPENAI_BASE_URL=%_BASE_URL%") else (set "OPENAI_BASE_URL=")
    if not "%_API_VERSION%"=="" (set "OPENAI_API_VERSION=%_API_VERSION%") else (set "OPENAI_API_VERSION=")
    exit /b %_RC%
)
