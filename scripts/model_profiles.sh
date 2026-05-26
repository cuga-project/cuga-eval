#!/bin/bash
# Shared model profile environment variable definitions.
# Source this file and call: apply_model_profile <profile_name>

# Colors (define only if not already set)
: "${GREEN:=\033[0;32m}"
: "${RED:=\033[0;31m}"
: "${YELLOW:=\033[1;33m}"
: "${NC:=\033[0m}"

apply_model_profile() {
    local profile="$1"
    case "$profile" in
        gpt-oss)
            export AGENT_SETTING_CONFIG="settings.groq.toml"
            export MODEL_NAME="openai/gpt-oss-120b"
            unset OPENAI_BASE_URL
            unset OPENAI_API_VERSION
            echo -e "${GREEN}✓${NC} Model profile: gpt-oss"
            echo -e "${GREEN}  AGENT_SETTING_CONFIG=$AGENT_SETTING_CONFIG${NC}"
            echo -e "${GREEN}  MODEL_NAME=$MODEL_NAME${NC}"
            ;;
        gpt4o)
            export AGENT_SETTING_CONFIG="settings.openai.toml"
            export MODEL_NAME="Azure/gpt-4o"
            export OPENAI_BASE_URL="https://ete-litellm.bx.cloud9.ibm.com"
            export OPENAI_API_VERSION="2024-08-06"
            echo -e "${GREEN}✓${NC} Model profile: gpt4o (Azure/gpt-4o)"
            echo -e "${GREEN}  AGENT_SETTING_CONFIG=$AGENT_SETTING_CONFIG${NC}"
            echo -e "${GREEN}  MODEL_NAME=$MODEL_NAME${NC}"
            echo -e "${GREEN}  OPENAI_BASE_URL=$OPENAI_BASE_URL${NC}"
            echo -e "${GREEN}  OPENAI_API_VERSION=$OPENAI_API_VERSION${NC}"
            ;;
        gpt4.1)
            export AGENT_SETTING_CONFIG="settings.openai.toml"
            export MODEL_NAME="Azure/gpt-4.1"
            export OPENAI_BASE_URL="https://ete-litellm.bx.cloud9.ibm.com"
            export OPENAI_API_VERSION="2024-08-06"
            echo -e "${GREEN}✓${NC} Model profile: gpt4.1 (Azure/gpt-4.1)"
            echo -e "${GREEN}  AGENT_SETTING_CONFIG=$AGENT_SETTING_CONFIG${NC}"
            echo -e "${GREEN}  MODEL_NAME=$MODEL_NAME${NC}"
            echo -e "${GREEN}  OPENAI_BASE_URL=$OPENAI_BASE_URL${NC}"
            echo -e "${GREEN}  OPENAI_API_VERSION=$OPENAI_API_VERSION${NC}"
            ;;
        opus4.5)
            export AGENT_SETTING_CONFIG="settings.openai.toml"
            export MODEL_NAME="claude-opus-4-5-20251101"
            export OPENAI_BASE_URL="https://ete-litellm.bx.cloud9.ibm.com"
            unset OPENAI_API_VERSION
            echo -e "${GREEN}✓${NC} Model profile: opus4.5"
            echo -e "${GREEN}  AGENT_SETTING_CONFIG=$AGENT_SETTING_CONFIG${NC}"
            echo -e "${GREEN}  MODEL_NAME=$MODEL_NAME${NC}"
            echo -e "${GREEN}  OPENAI_BASE_URL=$OPENAI_BASE_URL${NC}"
            ;;
        "")
            # No profile specified, use .env defaults
            ;;
        *)
            echo -e "${RED}Error: Unknown model profile '$profile'${NC}"
            echo -e "${YELLOW}Valid values: gpt-oss, gpt4o, gpt4.1, opus4.5${NC}"
            return 1
            ;;
    esac
}
