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

# Shared .env parser (_parse_env_file), used by apply_dotenv_model_overrides.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env_parse.sh"

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
EXPERIMENT="${EXPERIMENT:-}"
RESUME="${RESUME:-false}"
RESUME_EXPERIMENT="${RESUME_EXPERIMENT:-}"
WORKSPACE_BUNDLE_DIR="${WORKSPACE_BUNDLE_DIR:-}"
BACKGROUND="${BACKGROUND:-false}"
STOP="${STOP:-false}"
RESTART="${RESTART:-false}"
STATUS="${STATUS:-false}"
FORWARDED_ARGS=()
USE_DOTENV="${USE_DOTENV:-false}"

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
            --experiment)
                EXPERIMENT="${args[$((idx+1))]}"
                idx=$((idx+2))
                ;;
            --resume)
                RESUME=true
                idx=$((idx+1))
                ;;
            --resume-experiment)
                RESUME_EXPERIMENT="${args[$((idx+1))]}"
                idx=$((idx+2))
                ;;
            --background)
                BACKGROUND=true
                idx=$((idx+1))
                ;;
            --stop)
                STOP=true
                idx=$((idx+1))
                ;;
            --restart)
                RESTART=true
                idx=$((idx+1))
                ;;
            --status)
                STATUS=true
                idx=$((idx+1))
                ;;
            --dotenv)
                USE_DOTENV=true
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

# Re-read .env with force-export semantics so .env vars win over a
# previously-applied model profile. Resolution order for the file:
#   $1 (explicit path, used by tests) → $DOTENV_FILE → <project_root>/.env
apply_dotenv_model_overrides() {
    local helpers_dir env_file
    helpers_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    env_file="${1:-${DOTENV_FILE:-$helpers_dir/../../.env}}"

    if [ ! -f "$env_file" ]; then
        echo -e "${YELLOW}Warning: --dotenv specified but .env not found at $env_file${NC}"
        return 0
    fi

    echo -e "${GREEN}✓${NC} .env overrides (--dotenv):"
    _parse_env_file "$env_file" true true
}

# Guard: --dotenv forces model configuration from .env, so comparing more than
# one model would silently run the same model for every config (the comparison
# would be meaningless). Refuse the combination loudly.
# Usage: require_single_model_for_dotenv "${MODEL_LIST[@]}"
require_single_model_for_dotenv() {
    if [[ "${USE_DOTENV:-false}" == "true" && $# -gt 1 ]]; then
        echo -e "${RED}Error: --dotenv cannot be combined with multiple models: $*${NC}" >&2
        echo -e "${YELLOW}--dotenv forces model configuration from .env, so every config would run the same model and the comparison would be meaningless.${NC}" >&2
        echo -e "${YELLOW}Run a single model with --dotenv, or drop --dotenv to compare profiles.${NC}" >&2
        return 1
    fi
    return 0
}

# Apply a model profile and, when USE_DOTENV=true, layer .env overrides on top.
# With no profile and USE_DOTENV=true, defaults to gpt-oss as the base.
# env_file is optional; used by tests to supply a temp file instead of the real .env.
apply_model_config() {
    local profile="${1:-}"
    local env_file="${2:-}"
    if [[ "${USE_DOTENV:-false}" == "true" && -z "$profile" ]]; then
        profile="gpt-oss"
    fi
    if [[ -n "$profile" ]]; then
        _ensure_model_profiles_loaded || return 1
        apply_model_profile "$profile" || return 1
    fi
    if [[ "${USE_DOTENV:-false}" == "true" ]]; then
        apply_dotenv_model_overrides "$env_file"
    fi
}

# Apply profile then CLI overrides. Call after load_env.sh and arg parsing.
finalize_model_config() {
    apply_model_config "$MODEL_PROFILE" || return 1
    apply_model_cli_overrides_if_set
}

# Build model-envs JSON for bundle CLI.
# Usage: build_model_envs_json model1 model2 ...
# Applies each model config (profile + .env overrides when USE_DOTENV=true) so
# the captured snapshot matches what actually ran, then outputs JSON to stdout.
# Restores original env afterwards.
build_model_envs_json() {
    local models=("$@")
    local json="{"
    local first=true

    # Save current env. DYNACONF_* are snapshotted too because apply_model_config
    # (profile and/or .env when --dotenv) can export them as a side effect.
    local orig_agent_setting="${AGENT_SETTING_CONFIG:-}"
    local orig_model_name="${MODEL_NAME:-}"
    local orig_base_url="${OPENAI_BASE_URL:-}"
    local orig_api_version="${OPENAI_API_VERSION:-}"
    local orig_dynaconf
    orig_dynaconf="$(env | grep '^DYNACONF_' || true)"

    for model in "${models[@]}"; do
        if [[ "$first" != "true" ]]; then
            json+=","
        fi
        first=false

        # Apply model config (profile + .env overrides when --dotenv) silently
        apply_model_config "$model" > /dev/null 2>&1

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
    # Restore DYNACONF_* to the pre-call state: drop any added by the loop, then
    # re-export the snapshot so this function leaves the environment unchanged.
    while IFS= read -r line; do
        [[ -n "$line" ]] && unset "${line%%=*}" 2>/dev/null || true
    done < <(env | grep '^DYNACONF_' || true)
    while IFS= read -r line; do
        [[ -n "$line" ]] && export "$line"
    done <<< "$orig_dynaconf"

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
    # GNU coreutils stat uses -c; BSD/macOS stat uses -f. GNU's -f means
    # something else entirely (filesystem status, not file status) and
    # succeeds instead of erroring, so detect the flavor up front rather
    # than relying on a `||` fallback after the fact.
    local stat_fmt
    if stat -c '%Y' "$traj_data_dir" >/dev/null 2>&1; then
        stat_fmt=(-c '%Y %n')
    else
        stat_fmt=(-f '%m %N')
    fi
    # Find the most recently modified directory
    local latest
    latest=$(find "$traj_data_dir" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null \
        | xargs -0 stat "${stat_fmt[@]}" 2>/dev/null \
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

# True when any experiment/resume flag requests the workspace bundle path.
experiment_workspace_requested() {
    [[ -n "${EXPERIMENT:-}" || "${RESUME:-false}" == "true" || -n "${RESUME_EXPERIMENT:-}" ]]
}

# Parse --experiment / --resume / --resume-experiment in a benchmark eval.sh loop.
# Usage: parse_eval_experiment_flag "$1" "$2"  -> returns 0 if consumed (caller should shift).
parse_eval_experiment_flag() {
    case "$1" in
        --experiment)
            EXPERIMENT="$2"
            return 0
            ;;
        --resume)
            RESUME=true
            return 0
            ;;
        --resume-experiment)
            RESUME_EXPERIMENT="$2"
            return 0
            ;;
    esac
    return 1
}

# Create or re-open an experiment workspace before the evaluator runs.
# Sets WORKSPACE_BUNDLE_DIR on success. Returns 1 for legacy/no-op paths.
prepare_experiment_workspace() {
    local benchmark="$1"
    WORKSPACE_BUNDLE_DIR=""
    if ! experiment_workspace_requested; then
        return 1
    fi
    if [[ "${NO_BUNDLE:-false}" == "true" ]]; then
        if [[ -n "${EXPERIMENT:-}" || "${RESUME:-false}" == "true" || -n "${RESUME_EXPERIMENT:-}" ]]; then
            echo -e "${YELLOW:-}Warning: --no-bundle skips workspace creation — --experiment/--resume/--resume-experiment are ignored, running a fresh legacy (non-resumed) evaluation${NC:-}" >&2
        fi
        return 1
    fi

    local prep_args=(prepare-workspace --benchmark "$benchmark")
    [[ -n "${EXPERIMENT:-}" ]] && prep_args+=(--experiment "$EXPERIMENT")
    [[ "${RESUME:-false}" == "true" ]] && prep_args+=(--resume)
    [[ -n "${RESUME_EXPERIMENT:-}" ]] && prep_args+=(--resume-experiment "$RESUME_EXPERIMENT")
    [[ -n "${MODEL_PROFILE:-}" ]] && prep_args+=(--model-profile "$MODEL_PROFILE")
    [[ -n "${AGENT:-}" ]] && prep_args+=(--agent "$AGENT")
    [[ "${NO_POLICIES:-false}" == "true" ]] && prep_args+=(--no-policies)
    [[ -n "${EVAL_KEY:-}" ]] && prep_args+=(--eval-key "$EVAL_KEY")

    local out
    if ! out=$(uv run python -m benchmarks.helpers.experiment "${prep_args[@]}"); then
        echo -e "${RED:-}Error: $out${NC:-}" >&2
        return 1
    fi
    WORKSPACE_BUNDLE_DIR="$out"
    echo -e "${GREEN:-}Experiment workspace:${NC:-} $WORKSPACE_BUNDLE_DIR"
    return 0
}

# Finalize an experiment workspace after the evaluator exits.
# Remaining args are forwarded to ``experiment finalize-workspace`` (e.g.
# --task-file, --policies-dir, --trajectory-dir, --log-file, --partial).
finalize_experiment_workspace() {
    local benchmark="$1"
    shift
    [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]] || return 1
    [[ "${NO_BUNDLE:-false}" == "true" ]] && return 1

    local fin_args=(
        finalize-workspace
        --benchmark "$benchmark"
        --bundle-dir "$WORKSPACE_BUNDLE_DIR"
    )
    [[ -n "${MODEL_PROFILE:-}" ]] && fin_args+=(--model-profile "$MODEL_PROFILE")
    [[ -n "${AGENT:-}" ]] && fin_args+=(--agent "$AGENT")
    [[ "${NO_POLICIES:-false}" == "true" ]] && fin_args+=(--no-policies)
    [[ -n "${EVAL_KEY:-}" ]] && fin_args+=(--eval-key "$EVAL_KEY")
    [[ -n "${CUGA_GIT_INFO_JSON:-}" ]] && fin_args+=(--cuga-git-info "$CUGA_GIT_INFO_JSON")
    [[ "${BUNDLE_ZIP:-false}" == "true" ]] && fin_args+=(--zip)
    fin_args+=("$@")

    uv run python -m benchmarks.helpers.experiment "${fin_args[@]}"
}

# Record a legacy post-hoc bundle dir in .last_experiment (unnamed runs).
write_legacy_experiment_pointer() {
    local benchmark="$1"
    local bundle_dir="$2"
    [[ -n "$bundle_dir" ]] || return 0
    uv run python -m benchmarks.helpers.experiment write-pointer \
        --benchmark "$benchmark" \
        --bundle-dir "$bundle_dir" >/dev/null
}

# Resolve bundle dir for --status / --stop (uses experiment.py resolve).
resolve_lifecycle_bundle_dir() {
    local benchmark="$1"
    if [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]]; then
        echo "$WORKSPACE_BUNDLE_DIR"
        return 0
    fi
    local use_resume="${RESUME:-false}"
    if ! experiment_workspace_requested; then
        use_resume=true
    fi
    local resolve_args=(resolve --benchmark "$benchmark")
    [[ -n "${EXPERIMENT:-}" ]] && resolve_args+=(--experiment "$EXPERIMENT")
    [[ "$use_resume" == "true" ]] && resolve_args+=(--resume)
    [[ -n "${RESUME_EXPERIMENT:-}" ]] && resolve_args+=(--resume-experiment "$RESUME_EXPERIMENT")
    local out
    if ! out=$(uv run python -m benchmarks.helpers.experiment "${resolve_args[@]}" 2>&1); then
        echo -e "${RED:-}Error: $out${NC:-}" >&2
        return 1
    fi
    if [[ "$out" == "legacy" ]]; then
        echo -e "${RED:-}Error: no experiment workspace found (use --experiment, --resume, or --resume-experiment)${NC:-}" >&2
        return 1
    fi
    echo "${out%%$'\t'*}"
}

dispatch_run_status() {
    local benchmark="$1"
    local bundle_dir
    bundle_dir=$(resolve_lifecycle_bundle_dir "$benchmark") || return 1
    uv run python -m benchmarks.helpers.run_state status --bundle-dir "$bundle_dir"
}

dispatch_run_stop() {
    local benchmark="$1"
    local bundle_dir
    bundle_dir=$(resolve_lifecycle_bundle_dir "$benchmark") || return 1
    uv run python -m benchmarks.helpers.run_state stop --bundle-dir "$bundle_dir"
}

# Filter lifecycle flags out of an arg array for background re-exec.
_filter_lifecycle_args() {
    local -a filtered=()
    local skip_next=false
    local arg
    for arg in "$@"; do
        if [[ "$skip_next" == "true" ]]; then
            skip_next=false
            continue
        fi
        case "$arg" in
            --background|--stop|--restart|--status)
                ;;
            --experiment|--resume-experiment)
                skip_next=true
                ;;
            --resume)
                ;;
            *)
                filtered+=("$arg")
                ;;
        esac
    done
    printf '%s\0' "${filtered[@]}"
}

launch_background_eval() {
    local benchmark="$1"
    local script_path="$2"
    shift 2

    if ! prepare_experiment_workspace "$benchmark"; then
        echo -e "${RED:-}Error: --background requires --experiment, --resume, or --resume-experiment${NC:-}" >&2
        return 1
    fi

    local log_file="${WORKSPACE_BUNDLE_DIR}/background.log"
    local -a child_flags=()
    if [[ -n "${RESUME_EXPERIMENT:-}" ]]; then
        child_flags+=(--resume-experiment "$RESUME_EXPERIMENT")
    elif [[ -n "${EXPERIMENT:-}" ]]; then
        child_flags+=(--resume-experiment "$EXPERIMENT")
    elif [[ "${RESUME:-false}" == "true" ]]; then
        child_flags+=(--resume)
    fi

    local -a filtered=()
    while IFS= read -r -d '' arg; do
        filtered+=("$arg")
    done < <(_filter_lifecycle_args "$@")

    nohup bash "$script_path" "${child_flags[@]}" "${filtered[@]}" >>"$log_file" 2>&1 &
    local bg_pid=$!
    disown "$bg_pid" 2>/dev/null || true

    uv run python -m benchmarks.helpers.run_state mark-running \
        --bundle-dir "$WORKSPACE_BUNDLE_DIR" --pid "$bg_pid" >/dev/null

    echo -e "${GREEN:-}Started in background${NC:-} (pid $bg_pid)"
    echo -e "${GREEN:-}Log:${NC:-} $log_file"
    echo -e "${GREEN:-}Bundle:${NC:-} $WORKSPACE_BUNDLE_DIR"
}

# Short-circuit for --status / --stop / --restart / --background.
# Returns 0 when the caller should exit immediately.
handle_eval_lifecycle() {
    local benchmark="$1"
    local script_path="$2"
    shift 2

    if [[ "${STATUS:-false}" == "true" ]]; then
        dispatch_run_status "$benchmark"
        return 0
    fi

    if [[ "${STOP:-false}" == "true" ]]; then
        dispatch_run_stop "$benchmark"
        return 0
    fi

    if [[ "${RESTART:-false}" == "true" ]]; then
        # Validate the resume target BEFORE stopping anything — a bare
        # --restart with no --experiment/--resume/--resume-experiment must
        # fail without touching a currently-running process.
        if [[ -z "${RESUME_EXPERIMENT:-}" && -n "${EXPERIMENT:-}" ]]; then
            RESUME_EXPERIMENT="$EXPERIMENT"
            EXPERIMENT=""
        fi
        if [[ -z "${RESUME_EXPERIMENT:-}" && "${RESUME:-false}" != "true" ]]; then
            echo -e "${RED:-}Error: --restart requires --experiment, --resume, or --resume-experiment${NC:-}" >&2
            exit 1
        fi
        dispatch_run_stop "$benchmark" || true
        RESUME=true
        EXPERIMENT=""
        BACKGROUND=true
    fi

    if [[ "${BACKGROUND:-false}" == "true" ]]; then
        launch_background_eval "$benchmark" "$script_path" "$@"
        return 0
    fi

    return 1
}

mark_run_state_started() {
    [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]] || return 0
    [[ "${BACKGROUND:-false}" == "true" ]] && return 0
    uv run python -m benchmarks.helpers.run_state mark-running \
        --bundle-dir "$WORKSPACE_BUNDLE_DIR" --pid $$ >/dev/null
}

finalize_run_state_on_exit() {
    local exit_code="${1:-$?}"
    [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]] || return 0
    uv run python -m benchmarks.helpers.run_state mark-finished \
        --bundle-dir "$WORKSPACE_BUNDLE_DIR" \
        --exit-code "$exit_code" >/dev/null 2>&1 || true
}

# Create or re-open a compare experiment workspace (compare.sh).
prepare_compare_experiment_workspace() {
    local benchmark="$1"
    WORKSPACE_BUNDLE_DIR=""
    if ! experiment_workspace_requested; then
        return 1
    fi
    if [[ "${NO_BUNDLE:-false}" == "true" ]]; then
        if [[ -n "${EXPERIMENT:-}" || "${RESUME:-false}" == "true" || -n "${RESUME_EXPERIMENT:-}" ]]; then
            echo -e "${YELLOW:-}Warning: --no-bundle skips compare workspace creation — --experiment/--resume/--resume-experiment are ignored, running a fresh legacy (non-resumed) comparison${NC:-}" >&2
        fi
        return 1
    fi

    local prep_args=(prepare-workspace --benchmark "$benchmark" --compare)
    [[ -n "${EXPERIMENT:-}" ]] && prep_args+=(--experiment "$EXPERIMENT")
    [[ "${RESUME:-false}" == "true" ]] && prep_args+=(--resume)
    [[ -n "${RESUME_EXPERIMENT:-}" ]] && prep_args+=(--resume-experiment "$RESUME_EXPERIMENT")
    [[ -n "${MODEL_PROFILE:-}" ]] && prep_args+=(--model-profile "$MODEL_PROFILE")

    local out
    if ! out=$(uv run python -m benchmarks.helpers.experiment "${prep_args[@]}"); then
        echo -e "${RED:-}Error: $out${NC:-}" >&2
        return 1
    fi
    WORKSPACE_BUNDLE_DIR="$out"
    echo -e "${GREEN:-}Compare workspace:${NC:-} $WORKSPACE_BUNDLE_DIR"
    return 0
}

dispatch_compare_status() {
    local benchmark="$1"
    local bundle_dir
    bundle_dir=$(resolve_lifecycle_bundle_dir "$benchmark") || return 1
    uv run python -m benchmarks.helpers.compare_state status --compare-dir "$bundle_dir"
}

resolve_compare_experiment_name() {
    if [[ -n "${EXPERIMENT:-}" ]]; then
        echo "$EXPERIMENT"
    elif [[ -n "${RESUME_EXPERIMENT:-}" ]]; then
        echo "$RESUME_EXPERIMENT"
    elif [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]]; then
        basename "$WORKSPACE_BUNDLE_DIR"
    else
        echo ""
    fi
}

init_compare_state_for_run() {
    local compare_exp="$1"
    local total_planned="$2"
    local runs_per_config="$3"
    shift 3
    [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]] || return 0
    local init_args=(
        init
        --compare-dir "$WORKSPACE_BUNDLE_DIR"
        --compare-experiment "$compare_exp"
        --total-planned "$total_planned"
        --runs-per-config "$runs_per_config"
    )
    local config
    for config in "$@"; do
        init_args+=(--config "$config")
    done
    uv run python -m benchmarks.helpers.compare_state "${init_args[@]}" >/dev/null
}

compare_combo_is_done() {
    local config="$1"
    local run="$2"
    [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]] || return 1
    uv run python -m benchmarks.helpers.compare_state is-done \
        --compare-dir "$WORKSPACE_BUNDLE_DIR" \
        --config "$config" --run "$run" >/dev/null 2>&1
}

compare_combo_eval_flags() {
    local compare_exp="$1"
    local config="$2"
    local run="$3"
    [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]] || return 0
    uv run python -m benchmarks.helpers.compare_state eval-flags \
        --compare-dir "${WORKSPACE_BUNDLE_DIR:-}" \
        --compare-experiment "$compare_exp" \
        --config "$config" --run "$run"
}

compare_mark_combo_started() {
    local config="$1"
    local run="$2"
    local sub_exp="$3"
    [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]] || return 0
    uv run python -m benchmarks.helpers.compare_state mark-started \
        --compare-dir "$WORKSPACE_BUNDLE_DIR" \
        --config "$config" --run "$run" \
        --sub-experiment "$sub_exp" >/dev/null
}

compare_mark_combo_completed() {
    local config="$1"
    local run="$2"
    local exit_code="$3"
    [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]] || return 0
    uv run python -m benchmarks.helpers.compare_state mark-completed \
        --compare-dir "$WORKSPACE_BUNDLE_DIR" \
        --config "$config" --run "$run" \
        --exit-code "$exit_code" >/dev/null
}

# Parse --background / --stop / --restart / --status in a benchmark eval.sh loop.
parse_eval_lifecycle_flag() {
    case "$1" in
        --background)
            BACKGROUND=true
            return 0
            ;;
        --stop)
            STOP=true
            return 0
            ;;
        --restart)
            RESTART=true
            return 0
            ;;
        --status)
            STATUS=true
            return 0
            ;;
    esac
    return 1
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
