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
        echo ""
        echo "Examples:"
        echo "  ./eval.sh                          # Default evaluation"
        echo "  ./eval.sh --sdk                    # Use SDK evaluator"
        echo "  ./eval.sh --specific-task-levels 1  # Level 1 tasks only"
        echo "  ./eval.sh --task 82e2fac_1           # Single task"
        exit 0
    fi
done

APPWORLD_PID=""
REGISTRY_PID=""
REGISTRY_PORT=8001

cleanup() {
    local exit_code=$?
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
    fi
    exit $exit_code
}

trap cleanup EXIT INT TERM ERR

cd "$PROJECT_ROOT"

# Load environment
source "$PROJECT_ROOT/benchmarks/helpers/load_env.sh" "appworld"

# Capture console output to a log file for reproducibility bundles
CONSOLE_LOG="/tmp/appworld_console.log"
exec > >(tee "$CONSOLE_LOG") 2>&1

echo -e "${BLUE:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
echo -e "${BLUE:-}║  AppWorld Benchmark Evaluation                             ║${NC:-}"
echo -e "${BLUE:-}╚════════════════════════════════════════════════════════════╝${NC:-}"
echo ""

# Start servers unless SKIP_SERVER_START is set
if [ "${SKIP_SERVER_START:-false}" != "true" ]; then
    # Start AppWorld
    echo -e "${YELLOW:-}Starting AppWorld...${NC:-}"
    uv run --no-sync cuga start appworld > /tmp/appworld.log 2>&1 &
    APPWORLD_PID=$!

    if wait_for_server "http://127.0.0.1:8000/" "AppWorld" 90; then
        echo -e "${GREEN:-}✓${NC:-} AppWorld started (PID: $APPWORLD_PID)"
    else
        echo -e "${RED:-}Error: AppWorld failed to start${NC:-}"
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

# Parse bundle / model-profile / sdk flags; forward everything else to Python
# --task is the standard interface; mapped to --task-id for the AppWorld Python CLI.
USE_SDK=false
PASSTHROUGH_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-bundle)   NO_BUNDLE=true;    shift ;;
        --bundle-zip)  BUNDLE_ZIP=true;   shift ;;
        --sdk)         USE_SDK=true;      shift ;;
        --model-profile) MODEL_PROFILE="$2"; shift 2 ;;
        --agent)       AGENT="$2"; shift 2 ;;
        --verbose|-v|--quiet|-q)  PASSTHROUGH_ARGS+=("$1"); shift ;;
        --task)        PASSTHROUGH_ARGS+=("--task-id"); shift
                       while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                           PASSTHROUGH_ARGS+=("$1"); shift
                       done ;;
        *)             PASSTHROUGH_ARGS+=("$1"); shift ;;
    esac
done

# Run evaluation
echo -e "${YELLOW:-}Starting evaluation with agent ${AGENT:-cuga}...${NC:-}"
if [ "${AGENT:-cuga}" = "react" ]; then
    echo -e "${BLUE:-}Using React agent (appworld_eval_react.py)${NC:-}"
    uv run --no-sync python -m benchmarks.appworld.appworld_eval_react --agent "${AGENT:-cuga}" "${PASSTHROUGH_ARGS[@]}"
elif [[ "$USE_SDK" == "true" ]]; then
    echo -e "${BLUE:-}Using SDK evaluator (eval_appworld_sdk.py)${NC:-}"
    uv run --no-sync python -m benchmarks.appworld.eval_appworld_sdk "${PASSTHROUGH_ARGS[@]}"
else
    echo -e "${BLUE:-}Using default evaluator (appworld_eval.py)${NC:-}"
    uv run --no-sync python -m benchmarks.appworld.appworld_eval --agent "${AGENT:-cuga}" "${PASSTHROUGH_ARGS[@]}"
fi

EVAL_EXIT=$?

if [ $EVAL_EXIT -eq 0 ]; then
    echo -e "${GREEN:-}✓${NC:-} AppWorld evaluation completed successfully"

    # Create reproducibility bundle unless skipped
    if [ "${NO_BUNDLE:-false}" != "true" ]; then
        echo ""
        echo -e "${YELLOW:-}Creating reproducibility bundle...${NC:-}"

        # Find the most recent experiment result
        LATEST_RESULT=$(find "$SCRIPT_DIR/experiments/outputs" -name "*_final_report.json" -type f 2>/dev/null | sort | tail -1)
        if [ -n "$LATEST_RESULT" ]; then
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
            uv run --no-sync python -m benchmarks.helpers.bundle "${BUNDLE_ARGS[@]}"
            rm -f "$REPORT_TMP"
        fi
    fi
else
    echo -e "${RED:-}✗ AppWorld evaluation failed (exit code: $EVAL_EXIT)${NC:-}"
fi

exit $EVAL_EXIT
