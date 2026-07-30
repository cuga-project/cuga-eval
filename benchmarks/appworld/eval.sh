#!/bin/bash
# AppWorld benchmark eval script (called by top-level scripts/eval.sh or directly).
#
# Starts AppWorld services and registry, runs evaluation, and cleans up.
# Works from any directory — just run ./eval.sh
#
# Usage:
#   ./eval.sh                          # Default evaluation
#   ./eval.sh --specific-task-levels 1  # Level 1 tasks only
#   ./eval.sh --task 82e2fac_1           # Single task

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Source common helpers if available
if [ -f "$PROJECT_ROOT/benchmarks/helpers/common.sh" ]; then
    source "$PROJECT_ROOT/benchmarks/helpers/common.sh"
fi

# Early --help before any server startup
for arg in "$@"; do
    if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
        echo "Usage: ./eval.sh [--task ID] [--dataset DATASET] [--specific-task-levels LEVELS] [--sdk] [--no-bundle] [--bundle-zip]"
        echo ""
        echo "Options:"
        echo "  --task ID                    Run a specific task ID (e.g., '82e2fac_1')"
        echo "  --dataset DATASET            Dataset to run (train, dev, test_normal, test_challenge)"
        echo "  --specific-task-levels 1 2   Run tasks with specific difficulty levels"
        echo "  --sdk                        Use SDK evaluator (eval_appworld_sdk.py) instead of default"
        echo "  --no-bundle                  Skip reproducibility bundle creation"
        echo "  --bundle-zip                 Create zip archive of bundle"
        echo "  --model-profile <name>       Model profile (for bundle metadata)"
        echo "  --agent <name>               Agent to run (cuga, react, codeact; default: cuga)"
        echo "  --eval-key <key>             Task group key in eval_config.toml (e.g. test_med); recorded in bundle metadata"
        echo ""
        echo "Examples:"
        echo "  ./eval.sh                          # Default evaluation (cuga)"
        echo "  ./eval.sh --sdk                    # Use SDK evaluator"
        echo "  ./eval.sh --specific-task-levels 1  # Level 1 tasks only"
        echo "  ./eval.sh --task 82e2fac_1           # Single task"
        echo "  ./eval.sh --agent codeact            # Improved CodeAct loop"
        echo "  ./eval.sh --agent react              # Baseline (pre-PR-31) CodeAct loop"
        exit 0
    fi
done

APPWORLD_PID=""
REGISTRY_PID=""

# Parse bundle / model-profile / sdk flags before any server startup so
# --status / --stop / --background can short-circuit without side effects.
USE_SDK=false
PASSTHROUGH_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-bundle)   NO_BUNDLE=true;    shift ;;
        --bundle-zip)  BUNDLE_ZIP=true;   shift ;;
        --sdk)         USE_SDK=true;      shift ;;
        --model-profile) MODEL_PROFILE="$2"; shift 2 ;;
        --eval-key)    EVAL_KEY="$2"; PASSTHROUGH_ARGS+=(--eval-key "$2"); shift 2 ;;
        --experiment)  EXPERIMENT="$2"; shift 2 ;;
        --resume)      RESUME=true; shift ;;
        --resume-experiment) RESUME_EXPERIMENT="$2"; shift 2 ;;
        --background)  BACKGROUND=true; shift ;;
        --stop)        STOP=true; shift ;;
        --restart)     RESTART=true; shift ;;
        --status)      STATUS=true; shift ;;
        --agent)       AGENT="$2"; shift 2 ;;
        --verbose|-v|--quiet|-q)  PASSTHROUGH_ARGS+=("$1"); shift ;;
        --task)        PASSTHROUGH_ARGS+=("--task-id"); shift
                       while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                           PASSTHROUGH_ARGS+=("$1"); shift
                       done ;;
        *)             PASSTHROUGH_ARGS+=("$1"); shift ;;
    esac
done

if handle_eval_lifecycle "appworld" "$0" "${PASSTHROUGH_ARGS[@]}"; then
    exit 0
fi

cleanup() {
    local exit_code=$?
    finalize_run_state_on_exit "$exit_code"
    echo ""
    echo -e "${YELLOW:-}Cleaning up...${NC:-}"
    if [ "${SKIP_SERVER_CLEANUP:-false}" != "true" ]; then
        if [ -n "$APPWORLD_PID" ] && kill -0 "$APPWORLD_PID" 2>/dev/null; then
            echo -e "${BLUE:-}Stopping AppWorld (PID: $APPWORLD_PID)${NC:-}"
            kill "$APPWORLD_PID" 2>/dev/null || true
            wait "$APPWORLD_PID" 2>/dev/null || true
        fi
        if [ -n "$REGISTRY_PID" ] && kill -0 "$REGISTRY_PID" 2>/dev/null; then
            echo -e "${BLUE:-}Stopping registry (PID: $REGISTRY_PID)${NC:-}"
            kill "$REGISTRY_PID" 2>/dev/null || true
            wait "$REGISTRY_PID" 2>/dev/null || true
        fi
        # Killing $APPWORLD_PID does not reap its server children (`appworld
        # serve env` / `appworld serve apis` — the latter observed listening on
        # 9111 hours after its parent died, #148). Reap by port as a backstop.
        kill_port_processes "$APPWORLD_ENV_PORT" "$APPWORLD_APIS_PORT"
    fi
    # RUN_MARKER (if created) is only used up to the LATEST_RESULT lookup right
    # after the evaluator exits; clean it up here instead of a dedicated trap so
    # it can't leak on SIGKILL/early-abort without clobbering this EXIT trap.
    [ -n "${RUN_MARKER:-}" ] && rm -f "$RUN_MARKER"
    exit $exit_code
}

trap cleanup EXIT INT TERM ERR

cd "$PROJECT_ROOT"

# Load environment
source "$PROJECT_ROOT/benchmarks/helpers/load_env.sh" "appworld"

# Single registry/environment ports for shell helpers and Python (appworld_eval
# / cuga-agent both read these via settings.server_ports.{registry,environment_url}).
# Override with REGISTRY_PORT / APPWORLD_ENV_PORT or the DYNACONF_ vars directly.
REGISTRY_PORT="${REGISTRY_PORT:-${DYNACONF_SERVER_PORTS__REGISTRY:-8001}}"
export REGISTRY_PORT
export DYNACONF_SERVER_PORTS__REGISTRY="$REGISTRY_PORT"
APPWORLD_ENV_PORT="${APPWORLD_ENV_PORT:-${DYNACONF_SERVER_PORTS__ENVIRONMENT_URL:-8000}}"
export APPWORLD_ENV_PORT
export DYNACONF_SERVER_PORTS__ENVIRONMENT_URL="$APPWORLD_ENV_PORT"
APPWORLD_APIS_PORT="${APPWORLD_APIS_PORT:-${DYNACONF_SERVER_PORTS__APIS_URL:-9111}}"
export APPWORLD_APIS_PORT
export DYNACONF_SERVER_PORTS__APIS_URL="$APPWORLD_APIS_PORT"

# Capture console output to a log file for reproducibility bundles
CONSOLE_LOG="/tmp/appworld_console.log"
exec > >(tee "$CONSOLE_LOG") 2>&1

echo -e "${BLUE:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
echo -e "${BLUE:-}║  AppWorld Benchmark Evaluation                             ║${NC:-}"
echo -e "${BLUE:-}╚════════════════════════════════════════════════════════════╝${NC:-}"
echo ""

# Start servers unless SKIP_SERVER_START is set
if [ "${SKIP_SERVER_START:-false}" != "true" ]; then
    # Reap only ORPHANED AppWorld servers: a port that is held but does not
    # answer is a hung leftover from an aborted run (an `appworld serve apis`
    # child has been observed outliving its parent for hours, #148). A port
    # whose server still answers is left alone — compare.sh deliberately reuses
    # live servers across runs (SKIP_SERVER_CLEANUP), and killing them here
    # would re-pay the slow API-server boot on every run.
    reap_unresponsive_port() {
        local port=$1 url=$2 name=$3
        if port_in_use "$port" 2>/dev/null && ! curl -s --max-time 5 "$url" > /dev/null 2>&1; then
            echo -e "${YELLOW:-}Port $port held by an unresponsive $name — reaping orphan${NC:-}"
            kill_port_processes "$port"
            sleep 1
        fi
    }
    reap_unresponsive_port "$APPWORLD_ENV_PORT" "http://127.0.0.1:$APPWORLD_ENV_PORT/" "AppWorld"
    reap_unresponsive_port "$APPWORLD_APIS_PORT" "http://127.0.0.1:$APPWORLD_APIS_PORT/" "AppWorld API server"

    # Start AppWorld
    echo -e "${YELLOW:-}Starting AppWorld...${NC:-}"
    uv run --no-sync cuga start appworld > /tmp/appworld.log 2>&1 &
    APPWORLD_PID=$!

    if wait_for_server "http://127.0.0.1:$APPWORLD_ENV_PORT/" "AppWorld" 90; then
        echo -e "${GREEN:-}✓${NC:-} AppWorld started (PID: $APPWORLD_PID)"
    else
        echo -e "${RED:-}Error: AppWorld failed to start${NC:-}"
        cat /tmp/appworld.log | tail -20
        exit 1
    fi

    # Also wait for the API server: it boots after the environment server and
    # takes longer (it builds every app's routes). The registry fetches each
    # app's openapi.json from it at init and does NOT retry — waiting only for
    # the env server leaves a race where the registry loads 0 tools (#148).
    if wait_for_server "http://127.0.0.1:$APPWORLD_APIS_PORT/" "AppWorld API server" 120; then
        echo -e "${GREEN:-}✓${NC:-} AppWorld API server ready (port $APPWORLD_APIS_PORT)"
    else
        echo -e "${RED:-}Error: AppWorld API server failed to start${NC:-}"
        cat /tmp/appworld.log | tail -20
        exit 1
    fi

    # Kill any stale process on the registry port before starting
    if port_in_use $REGISTRY_PORT 2>/dev/null; then
        echo -e "${YELLOW:-}Killing existing process on port $REGISTRY_PORT...${NC:-}"
        lsof -ti :$REGISTRY_PORT | xargs kill 2>/dev/null || true
        sleep 1
    fi

    echo -e "${YELLOW:-}Starting registry server...${NC:-}"
    bash "$SCRIPT_DIR/run_registry.sh" > /tmp/appworld_registry.log 2>&1 &
    REGISTRY_PID=$!

    if wait_for_server "http://127.0.0.1:$REGISTRY_PORT/" "registry server" 60; then
        echo -e "${GREEN:-}✓${NC:-} Registry started (PID: $REGISTRY_PID)"
    else
        echo -e "${RED:-}Error: Registry failed to start${NC:-}"
        exit 1
    fi
fi

echo ""

if experiment_workspace_requested && [[ "${NO_BUNDLE:-false}" != "true" ]]; then
    if [[ "$USE_SDK" != "true" ]]; then
        echo -e "${YELLOW:-}Note: experiment workspace requires the SDK evaluator; enabling --sdk${NC:-}"
        USE_SDK=true
    fi
fi

if prepare_experiment_workspace "appworld"; then
    PASSTHROUGH_ARGS+=(--bundle-dir "$WORKSPACE_BUNDLE_DIR")
    mark_run_state_started
fi

# Apply --model-profile after load_env + arg parsing. common.sh is sourced
# unconditionally above; hard-fail loudly if that ever stops being true
# instead of silently skipping model-profile application.
declare -F finalize_model_config >/dev/null || { echo "Error: common.sh not sourced (finalize_model_config unavailable)" >&2; exit 1; }
finalize_model_config || exit 1

# Run evaluation
echo -e "${YELLOW:-}Starting evaluation with agent ${AGENT:-cuga}...${NC:-}"

# Unique per-process ID (timestamp + PID) so concurrent runs on this host never
# collide, even if started in the same wall-clock second. Exported so the SDK
# evaluator embeds it in its result filename (see save_evaluation_results).
RUN_ID="$(date +%Y%m%d_%H%M%S)_$$"
export EVAL_RUN_ID="$RUN_ID"

# Marker whose mtime marks the start of THIS run, used as a fallback for
# evaluators that don't embed EVAL_RUN_ID in their output filename (the
# non-SDK cuga/codeact/react evaluators, which use ExperimentManager, not
# save_evaluation_results). POSIX -newer is portable to BSD/macOS (unlike
# GNU-only -newermt). NOTE: mtime-newer alone is not run-scoped — it can still
# pick up a concurrent sibling run's report, not just a stale one; it's kept
# only as a safety net for the paths that don't have a real per-run ID.
RUN_MARKER=$(mktemp "${TMPDIR:-/tmp}/appworld_run_marker.XXXXXX")

# Capture the evaluator's exit code instead of letting `set -e` abort here — an
# abort would skip both bundling and the failure banner below.
set +e
if [ "${AGENT:-cuga}" = "codeact" ]; then
    echo -e "${BLUE:-}Using CodeAct agent (appworld_eval_codeact.py)${NC:-}"
    uv run --no-sync python -m benchmarks.appworld.appworld_eval_codeact --agent codeact "${PASSTHROUGH_ARGS[@]}"
elif [ "${AGENT:-cuga}" = "react" ]; then
    echo -e "${BLUE:-}Using React agent (appworld_eval_react.py)${NC:-}"
    uv run --no-sync python -m benchmarks.appworld.appworld_eval_react --agent react "${PASSTHROUGH_ARGS[@]}"
elif [[ "$USE_SDK" == "true" ]]; then
    echo -e "${BLUE:-}Using SDK evaluator (eval_appworld_sdk.py)${NC:-}"
    uv run --no-sync python -m benchmarks.appworld.eval_appworld_sdk "${PASSTHROUGH_ARGS[@]}"
else
    echo -e "${BLUE:-}Using default evaluator (appworld_eval.py)${NC:-}"
    uv run --no-sync python -m benchmarks.appworld.appworld_eval --agent "${AGENT:-cuga}" "${PASSTHROUGH_ARGS[@]}"
fi
EVAL_EXIT=$?
set -e

# Select ONLY a report produced by this run. Prefer an exact match on our
# unique RUN_ID (true run-scoping, safe under concurrent runs); fall back to
# mtime-newer-than-marker for evaluators that don't embed EVAL_RUN_ID.
# (stderr is not redirected to /dev/null here — a missing/unreadable output
# dir should surface as a real error, not silently look like "no fresh result".)
LATEST_RESULT=""
if [ -d "$SCRIPT_DIR/experiments/outputs" ]; then
    LATEST_RESULT=$(find "$SCRIPT_DIR/experiments/outputs" -name "*_${RUN_ID}_final_report.json" -type f | sort | tail -1)
    if [ -z "$LATEST_RESULT" ]; then
        LATEST_RESULT=$(find "$SCRIPT_DIR/experiments/outputs" -name "*_final_report.json" -type f -newer "$RUN_MARKER" | sort | tail -1)
    fi
else
    echo -e "${RED:-}✗ $SCRIPT_DIR/experiments/outputs does not exist — the evaluator never got as far as writing a report.${NC:-}" >&2
fi

if [ $EVAL_EXIT -eq 0 ]; then
    echo -e "${GREEN:-}✓${NC:-} AppWorld evaluation completed successfully"
else
    echo -e "${RED:-}✗ AppWorld evaluation failed (exit code: $EVAL_EXIT)${NC:-}"
fi

# A clean exit MUST come with a fresh report from this run. If it does not,
# refuse to bundle: the old `find | sort | tail -1` fallback silently bundled a
# previous run's report as if it were this run's results.
if [ $EVAL_EXIT -eq 0 ] && [ -z "$LATEST_RESULT" ]; then
    echo -e "${RED:-}✗ Evaluator exited 0 but wrote no fresh result report — refusing to bundle stale results.${NC:-}"
    echo -e "${RED:-}  The evaluator process was likely terminated before saving; check the console log above.${NC:-}"
    exit 1
fi

# Bundle whenever this run produced a report. A partial report from a non-zero
# exit is still bundled for forensics, but EVAL_EXIT is preserved so the run is
# not mistaken for a clean pass.
if [ -n "$LATEST_RESULT" ] && [ "${NO_BUNDLE:-false}" != "true" ]; then
    echo ""
    if [ -n "${WORKSPACE_BUNDLE_DIR:-}" ]; then
        echo -e "${YELLOW:-}Finalizing experiment workspace...${NC:-}"
        FIN_EXTRA=(--task-file "$SCRIPT_DIR/eval_config.toml")
        TRAJ_DIR=$(find_latest_trajectory "$SCRIPT_DIR/logging/trajectory_data")
        if [ -n "$TRAJ_DIR" ]; then
            FIN_EXTRA+=(--trajectory-dir "$TRAJ_DIR")
        fi
        FIN_EXTRA+=(--log-file /tmp/appworld.log --log-file /tmp/appworld_registry.log --log-file "$CONSOLE_LOG")
        finalize_experiment_workspace "appworld" "${FIN_EXTRA[@]}"
    else
        echo -e "${YELLOW:-}Creating reproducibility bundle...${NC:-}"

        # Generate eval report
        REPORT_TMP=$(mktemp /tmp/appworld_eval_report_XXXXXX)
        uv run --no-sync python -m benchmarks.helpers.compare_report eval \
            --result-file "$LATEST_RESULT" --output "$REPORT_TMP"

        BUNDLE_ARGS=(assemble --benchmark appworld
            --result-files "$LATEST_RESULT"
            --task-files "$SCRIPT_DIR/eval_config.toml"
            --report "$REPORT_TMP")
        if [ -n "$MODEL_PROFILE" ]; then
            BUNDLE_ARGS+=(--model-profile "$MODEL_PROFILE")
        fi
        [[ -n "${EVAL_KEY:-}" ]] && BUNDLE_ARGS+=(--eval-key "$EVAL_KEY")
        if [ "${BUNDLE_ZIP:-false}" = "true" ]; then
            BUNDLE_ARGS+=(--zip)
        fi
        # Include cuga trajectories
        TRAJ_DIR=$(find_latest_trajectory "$SCRIPT_DIR/logging/trajectory_data")
        if [ -n "$TRAJ_DIR" ]; then
            BUNDLE_ARGS+=(--trajectory-dir "$TRAJ_DIR")
        fi
        # Include server and console logs
        BUNDLE_ARGS+=(--log-files /tmp/appworld.log /tmp/appworld_registry.log "$CONSOLE_LOG")
        # Download Langfuse traces if available
        BUNDLE_ARGS+=(--fetch-langfuse)
        BUNDLE_OUT=$(uv run --no-sync python -m benchmarks.helpers.bundle "${BUNDLE_ARGS[@]}" 2>&1 | tee /dev/stderr)
        BUNDLE_PATH=$(echo "$BUNDLE_OUT" | sed -n 's/^Bundle created: //p' | tail -1)
        if [ -n "$BUNDLE_PATH" ]; then
            write_legacy_experiment_pointer "appworld" "$BUNDLE_PATH"
        fi
        rm -f "$REPORT_TMP"
    fi
fi

exit $EVAL_EXIT
