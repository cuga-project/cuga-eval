#!/bin/bash
# Common helper functions for all benchmark scripts.
# Source this file to get shared utilities.
#
# Provides:
#   - Color definitions
#   - wait_for_server() - Wait for HTTP server to be ready
#   - port_in_use() - Check if a port is in use (cross-platform)
#   - parse_common_args() - Parse shared CLI arguments
#   - cleanup_pids() - Kill tracked background processes
#   - add_cleanup_pid() - Register a PID for cleanup
#   - resolve_project_root() - Find the project root directory

# Colors (safe for non-terminal output)
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    BLUE='\033[0;34m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    CYAN='\033[0;36m'
    NC='\033[0m'
else
    GREEN='' BLUE='' YELLOW='' RED='' CYAN='' NC=''
fi

# Tracked PIDs for cleanup
_CLEANUP_PIDS=()

add_cleanup_pid() {
    _CLEANUP_PIDS+=("$1")
}

cleanup_pids() {
    local exit_code=$?
    for pid in "${_CLEANUP_PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "${BLUE}Stopping process (PID: $pid)${NC}"
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done
    return $exit_code
}

# Kill all processes listening on the given ports
kill_port_processes() {
    for port in "$@"; do
        if port_in_use "$port" 2>/dev/null; then
            echo -e "${BLUE:-}Killing process on port $port${NC:-}"
            lsof -ti :"$port" 2>/dev/null | xargs kill 2>/dev/null || true
        fi
    done
}

# Cross-platform port check
port_in_use() {
    local port=$1
    case "$(uname -s)" in
        Linux)
            ss -tlnp 2>/dev/null | grep -q ":${port} " && return 0
            # Fallback to lsof if ss not available
            lsof -i ":$port" > /dev/null 2>&1
            ;;
        Darwin)
            lsof -i ":$port" > /dev/null 2>&1
            ;;
        MINGW*|MSYS*|CYGWIN*)
            netstat -an 2>/dev/null | grep -q ":${port}.*LISTEN" && return 0
            return 1
            ;;
        *)
            lsof -i ":$port" > /dev/null 2>&1
            ;;
    esac
}

# Wait for an HTTP server to respond
wait_for_server() {
    local url=$1
    local name=$2
    local max_attempts=${3:-30}
    local attempt=1

    echo -n "Waiting for $name to be ready"
    while [ $attempt -le $max_attempts ]; do
        if curl -s "$url" > /dev/null 2>&1; then
            echo -e " ${GREEN}ready${NC}"
            return 0
        fi
        echo -n "."
        sleep 1
        attempt=$((attempt + 1))
    done

    echo -e " ${RED}timeout${NC}"
    return 1
}

# Resolve project root (walks up from caller to find pyproject.toml)
resolve_project_root() {
    local dir="${1:-$(pwd)}"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/pyproject.toml" ]; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    echo "$dir"
    return 1
}

# Parse common CLI arguments.
# Sets global variables: BENCHMARK, RUNS, OUTPUT_FILE, DRY_RUN, VERBOSE, MODEL_PROFILE,
# AGENT, AGENTS, COMPARE_AGENTS. Remaining args go into FORWARDED_ARGS array.
#
# Usage:
#   parse_common_args "$@"
#   # Now use $BENCHMARK, $RUNS, $FORWARDED_ARGS, etc.
BENCHMARK="${BENCHMARK:-}"
RUNS="${RUNS:-1}"
OUTPUT_FILE="${OUTPUT_FILE:-}"
DRY_RUN="${DRY_RUN:-false}"
VERBOSE="${VERBOSE:-false}"
MODEL_PROFILE="${MODEL_PROFILE:-}"
CLI_MODEL_NAME="${CLI_MODEL_NAME:-}"
CLI_OPENAI_BASE_URL="${CLI_OPENAI_BASE_URL:-}"
AGENT="${AGENT:-cuga}"
AGENTS="${AGENTS:-}"
COMPARE_AGENTS="${COMPARE_AGENTS:-false}"
NO_BUNDLE="${NO_BUNDLE:-false}"
BUNDLE_ZIP="${BUNDLE_ZIP:-false}"
FORWARDED_ARGS=()

parse_common_args() {
    local args=("$@")
    local idx=0
    FORWARDED_ARGS=()

    while [[ $idx -lt ${#args[@]} ]]; do
        local arg="${args[$idx]}"
        case "$arg" in
            --benchmark|-b)
                BENCHMARK="${args[$((idx+1))]}"
                idx=$((idx+2))
                ;;
            --runs)
                RUNS="${args[$((idx+1))]}"
                idx=$((idx+2))
                ;;
            --output|-o)
                OUTPUT_FILE="${args[$((idx+1))]}"
                idx=$((idx+2))
                ;;
            --dry-run)
                DRY_RUN=true
                idx=$((idx+1))
                ;;
            --verbose|-v)
                VERBOSE=true
                FORWARDED_ARGS+=("$arg")
                idx=$((idx+1))
                ;;
            --model-profile)
                MODEL_PROFILE="${args[$((idx+1))]}"
                idx=$((idx+2))
                ;;
            --model-name)
                CLI_MODEL_NAME="${args[$((idx+1))]}"
                idx=$((idx+2))
                ;;
            --openai-base-url)
                CLI_OPENAI_BASE_URL="${args[$((idx+1))]}"
                idx=$((idx+2))
                ;;
            --agent)
                AGENT="${args[$((idx+1))]}"
                idx=$((idx+2))
                ;;
            --agents)
                AGENTS="${args[$((idx+1))]}"
                idx=$((idx+2))
                ;;
            --compare-agents)
                COMPARE_AGENTS=true
                idx=$((idx+1))
                ;;
            --no-bundle)
                NO_BUNDLE=true
                idx=$((idx+1))
                ;;
            --bundle-zip)
                BUNDLE_ZIP=true
                idx=$((idx+1))
                ;;
            --help|-h)
                # Let the caller handle --help
                FORWARDED_ARGS+=("$arg")
                idx=$((idx+1))
                ;;
            *)
                FORWARDED_ARGS+=("$arg")
                idx=$((idx+1))
                ;;
        esac
    done

    # Resolve AGENTS: --compare-agents implies cuga,react;
    # an empty AGENTS defaults to the singular --agent value (back-compat).
    if [[ "$COMPARE_AGENTS" == "true" && -z "$AGENTS" ]]; then
        AGENTS="cuga,react"
    fi
    if [[ -z "$AGENTS" ]]; then
        AGENTS="$AGENT"
    fi
}

# Source scripts/model_profiles.sh once (idempotent).
_ensure_model_profiles_loaded() {
    local script_dir profiles_script
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    profiles_script="$script_dir/../../scripts/model_profiles.sh"
    if [ -f "$profiles_script" ]; then
        # shellcheck source=/dev/null
        source "$profiles_script"
        return 0
    fi
    echo -e "${RED}Error: model_profiles.sh not found at $profiles_script${NC}"
    return 1
}

# Apply model profile if specified
apply_model_profile_if_set() {
    if [ -n "$MODEL_PROFILE" ]; then
        _ensure_model_profiles_loaded || return 1
        apply_model_profile "$MODEL_PROFILE"
    fi
}

# Apply per-run CLI overrides (after profile and .env load).
apply_model_cli_overrides_if_set() {
    if [ -n "$CLI_MODEL_NAME" ]; then
        export MODEL_NAME="$CLI_MODEL_NAME"
        echo -e "${GREEN}✓${NC} MODEL_NAME override: $MODEL_NAME"
    fi
    if [ -n "$CLI_OPENAI_BASE_URL" ]; then
        export OPENAI_BASE_URL="$CLI_OPENAI_BASE_URL"
        echo -e "${GREEN}✓${NC} OPENAI_BASE_URL override: $OPENAI_BASE_URL"
    fi
}

# Apply profile then CLI overrides. Call after load_env.sh and arg parsing.
finalize_model_config() {
    apply_model_profile_if_set || return 1
    apply_model_cli_overrides_if_set
}

# Build model-envs JSON for bundle CLI.
# Usage: build_model_envs_json model1 model2 ...
# Applies each profile, captures env vars, and outputs JSON to stdout.
# Restores original env after each model.
build_model_envs_json() {
    local models=("$@")
    local json="{"
    local first=true

    # Save current env
    local orig_agent_setting="${AGENT_SETTING_CONFIG:-}"
    local orig_model_name="${MODEL_NAME:-}"
    local orig_base_url="${OPENAI_BASE_URL:-}"
    local orig_api_version="${OPENAI_API_VERSION:-}"

    for model in "${models[@]}"; do
        if [[ "$first" != "true" ]]; then
            json+=","
        fi
        first=false

        # Apply profile (silently)
        apply_model_profile "$model" > /dev/null 2>&1

        # Build per-model JSON object with model vars + DYNACONF overrides
        json+="\"${model}\":{"
        json+="\"AGENT_SETTING_CONFIG\":\"${AGENT_SETTING_CONFIG:-}\""
        json+=",\"MODEL_NAME\":\"${MODEL_NAME:-}\""
        if [ -n "${OPENAI_BASE_URL:-}" ]; then
            json+=",\"OPENAI_BASE_URL\":\"${OPENAI_BASE_URL}\""
        fi
        if [ -n "${OPENAI_API_VERSION:-}" ]; then
            json+=",\"OPENAI_API_VERSION\":\"${OPENAI_API_VERSION}\""
        fi
        if [ -n "${LANGFUSE_HOST:-}" ]; then
            json+=",\"LANGFUSE_HOST\":\"${LANGFUSE_HOST}\""
        fi
        # Capture DYNACONF overrides that affect behaviour
        while IFS='=' read -r key value; do
            if [[ "$key" == DYNACONF_* ]]; then
                # Escape double quotes in value
                value="${value//\"/\\\"}"
                json+=",\"${key}\":\"${value}\""
            fi
        done < <(env | grep '^DYNACONF_' | sort)
        json+="}"
    done
    json+="}"

    # Restore original env
    export AGENT_SETTING_CONFIG="$orig_agent_setting"
    export MODEL_NAME="$orig_model_name"
    if [ -n "$orig_base_url" ]; then
        export OPENAI_BASE_URL="$orig_base_url"
    else
        unset OPENAI_BASE_URL 2>/dev/null || true
    fi
    if [ -n "$orig_api_version" ]; then
        export OPENAI_API_VERSION="$orig_api_version"
    else
        unset OPENAI_API_VERSION 2>/dev/null || true
    fi

    echo "$json"
}

# Find the most recently modified trajectory folder under a trajectory_data directory.
# Usage: find_latest_trajectory "/path/to/logging/trajectory_data"
# Prints the path to the latest subfolder, or empty string if none found.
find_latest_trajectory() {
    local traj_data_dir="$1"
    if [ ! -d "$traj_data_dir" ]; then
        echo ""
        return
    fi
    # Find the most recently modified directory
    local latest
    latest=$(find "$traj_data_dir" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null \
        | xargs -0 stat -f '%m %N' 2>/dev/null \
        | sort -rn | head -1 | cut -d' ' -f2-)
    echo "$latest"
}

# List available benchmarks by checking for eval.sh in benchmark directories
list_benchmarks() {
    local helpers_dir
    helpers_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local benchmarks_dir="$(dirname "$helpers_dir")"

    echo "Available benchmarks:"
    for dir in "$benchmarks_dir"/*/; do
        local name="$(basename "$dir")"
        if [ "$name" != "helpers" ] && [ -d "$dir" ]; then
            echo "  - $name"
        fi
    done
}

# Format a number of seconds as a compact human duration ("47s", "3m12s",
# "1h05m20s"). Used by progress / ETA helpers in compare.sh.
fmt_duration() {
    local secs=$1
    if (( secs < 60 )); then
        echo "${secs}s"
    elif (( secs < 3600 )); then
        printf "%dm%02ds" $((secs/60)) $((secs%60))
    else
        printf "%dh%02dm%02ds" $((secs/3600)) $(((secs%3600)/60)) $((secs%60))
    fi
}

# Compute an ETA line: "~Xm remaining (avg Ys/run)".
# Safe against done_count=0 (returns "ETA: pending").
#   $1: total elapsed seconds spent on completed runs
#   $2: number of runs completed
#   $3: number of runs remaining
fmt_eta() {
    local elapsed=$1
    local done_count=$2
    local remaining=$3
    if (( done_count <= 0 )); then
        echo "ETA: pending"
        return
    fi
    local avg=$(( elapsed / done_count ))
    local eta=$(( avg * remaining ))
    echo "~$(fmt_duration $eta) remaining (avg $(fmt_duration $avg)/run)"
}

# Check and normalize Langfuse environment variables.
# If LANGFUSE_HOST is not set but LANGFUSE_BASE_URL is, copy it over.
# Warns if neither is set.
check_langfuse_env() {
    if [ -z "${LANGFUSE_HOST:-}" ]; then
        if [ -n "${LANGFUSE_BASE_URL:-}" ]; then
            echo -e "${YELLOW:-}Warning: LANGFUSE_HOST is not set but LANGFUSE_BASE_URL is.${NC:-}"
            echo -e "${YELLOW:-}  Setting LANGFUSE_HOST=\$LANGFUSE_BASE_URL (${LANGFUSE_BASE_URL})${NC:-}"
            export LANGFUSE_HOST="$LANGFUSE_BASE_URL"
        else
            echo ""
            echo -e "${YELLOW:-}╔══════════════════════════════════════════════════════════╗${NC:-}"
            echo -e "${YELLOW:-}║  WARNING: Neither LANGFUSE_HOST nor LANGFUSE_BASE_URL    ║${NC:-}"
            echo -e "${YELLOW:-}║  is set. Langfuse tracing and trace download in bundles  ║${NC:-}"
            echo -e "${YELLOW:-}║  may not work.                                           ║${NC:-}"
            echo -e "${YELLOW:-}╚══════════════════════════════════════════════════════════╝${NC:-}"
            echo ""
        fi
    fi
}
