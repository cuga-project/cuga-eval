#!/bin/bash
# Oak Health Insurance benchmark eval script (called by top-level scripts/eval.sh or directly).
#
# Starts FastAPI app, registry server, runs evaluation, and cleans up.
# Works from any directory — just run ./eval.sh
#
# Usage:
#   ./eval.sh                        # Default evaluation
#   ./eval.sh --task approved_claims  # Single task
#   ./eval.sh --difficulty easy       # Filter by difficulty

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
        echo "Usage: ./eval.sh [--task TASK] [--difficulty LEVEL] [--no-bundle] [--bundle-zip] [--model-profile NAME]"
        echo ""
        echo "Options:"
        echo "  --task TASK              Run a specific task by ID/name (e.g., 'approved_claims')"
        echo "  --difficulty LEVEL       Filter by difficulty level (easy, medium, hard)"
        echo "  --no-bundle              Skip reproducibility bundle creation"
        echo "  --bundle-zip             Create zip archive of bundle"
        echo "  --model-profile <name>   Model profile (for bundle metadata)"
        echo "  --no-policies            Disable CUGA policies (for baselining)"
        echo ""
        echo "Examples:"
        echo "  ./eval.sh                        # Default evaluation"
        echo "  ./eval.sh --task approved_claims  # Single task"
        echo "  ./eval.sh --difficulty easy       # Filter by difficulty"
        exit 0
    fi
done

FASTAPI_PORT=8090
REGISTRY_PORT=8001
FASTAPI_PID=""
REGISTRY_PID=""

cleanup() {
    local exit_code=$?
    echo ""
    echo -e "${YELLOW:-}Cleaning up...${NC:-}"
    if [ "${SKIP_SERVER_CLEANUP:-false}" != "true" ]; then
        if [ -n "$FASTAPI_PID" ] && kill -0 "$FASTAPI_PID" 2>/dev/null; then
            echo -e "${BLUE:-}Stopping FastAPI server (PID: $FASTAPI_PID)${NC:-}"
            kill "$FASTAPI_PID" 2>/dev/null || true
            wait "$FASTAPI_PID" 2>/dev/null || true
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
source "$PROJECT_ROOT/benchmarks/helpers/load_env.sh" "oak_health_insurance"

# Capture console output to a log file for reproducibility bundles
CONSOLE_LOG="/tmp/oak_console.log"
exec > >(tee "$CONSOLE_LOG") 2>&1

echo -e "${BLUE:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
echo -e "${BLUE:-}║  Oak Health Insurance Benchmark Evaluation                 ║${NC:-}"
echo -e "${BLUE:-}╚════════════════════════════════════════════════════════════╝${NC:-}"
echo ""

# Start servers unless SKIP_SERVER_START is set
if [ "${SKIP_SERVER_START:-false}" != "true" ]; then
    # Kill any stale process on the FastAPI port before starting
    if port_in_use $FASTAPI_PORT 2>/dev/null; then
        echo -e "${YELLOW:-}Killing existing process on port $FASTAPI_PORT...${NC:-}"
        lsof -ti :$FASTAPI_PORT | xargs kill 2>/dev/null || true
        sleep 1
    fi

    echo -e "${YELLOW:-}Starting FastAPI server on port $FASTAPI_PORT...${NC:-}"
    # Oak app uses relative imports (from models import ...), must run from its directory
    (cd "$SCRIPT_DIR" && uv run uvicorn main:app --port $FASTAPI_PORT) > /tmp/oak_fastapi.log 2>&1 &
    FASTAPI_PID=$!

    if wait_for_server "http://127.0.0.1:$FASTAPI_PORT/" "FastAPI server" 30; then
        echo -e "${GREEN:-}✓${NC:-} FastAPI server started (PID: $FASTAPI_PID)"
    else
        echo -e "${RED:-}Error: FastAPI server failed to start${NC:-}"
        cat /tmp/oak_fastapi.log | tail -20
        exit 1
    fi

    # Kill any stale process on the registry port before starting
    if port_in_use $REGISTRY_PORT 2>/dev/null; then
        echo -e "${YELLOW:-}Killing existing process on port $REGISTRY_PORT...${NC:-}"
        lsof -ti :$REGISTRY_PORT | xargs kill 2>/dev/null || true
        sleep 1
    fi

    echo -e "${YELLOW:-}Starting registry server on port $REGISTRY_PORT...${NC:-}"
    bash "$SCRIPT_DIR/run_registry.sh" > /tmp/oak_registry.log 2>&1 &
    REGISTRY_PID=$!

    if wait_for_server "http://127.0.0.1:$REGISTRY_PORT/" "registry server" 60; then
        echo -e "${GREEN:-}✓${NC:-} Registry started (PID: $REGISTRY_PID)"
    else
        echo -e "${RED:-}Error: Registry failed to start${NC:-}"
        cat /tmp/oak_registry.log | tail -20
        exit 1
    fi
fi

echo ""

# Parse bundle / model-profile flags; forward everything else to Python
PASSTHROUGH_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-bundle)   NO_BUNDLE=true;    shift ;;
        --bundle-zip)  BUNDLE_ZIP=true;   shift ;;
        --model-profile) MODEL_PROFILE="$2"; shift 2 ;;
        --verbose|-v|--quiet|-q)  PASSTHROUGH_ARGS+=("$1"); shift ;;
        *)             PASSTHROUGH_ARGS+=("$1"); shift ;;
    esac
done

# Run evaluation
echo -e "${YELLOW:-}Starting evaluation...${NC:-}"
uv run python -m benchmarks.oak_health_insurance.eval_bench_sdk "${PASSTHROUGH_ARGS[@]}"

EVAL_EXIT=$?

if [ $EVAL_EXIT -eq 0 ]; then
    echo -e "${GREEN:-}✓${NC:-} Oak Health Insurance evaluation completed successfully"

    # Create reproducibility bundle unless skipped
    if [ "${NO_BUNDLE:-false}" != "true" ]; then
        echo ""
        echo -e "${YELLOW:-}Creating reproducibility bundle...${NC:-}"

        LATEST_RESULT=$(ls -t "$SCRIPT_DIR/results"/oak_health_*.json 2>/dev/null | head -1)
        if [ -n "$LATEST_RESULT" ]; then
            # Generate eval report
            REPORT_TMP=$(mktemp /tmp/oak_eval_report_XXXXXX)
            uv run --no-sync python -m benchmarks.helpers.compare_report eval \
                --result-file "$LATEST_RESULT" --output "$REPORT_TMP"

            BUNDLE_ARGS=(assemble --benchmark oak_health_insurance
                --result-files "$LATEST_RESULT"
                --task-files "$SCRIPT_DIR/oak_health_test_suite_v1.json"
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
            BUNDLE_ARGS+=(--log-files /tmp/oak_fastapi.log /tmp/oak_registry.log "$CONSOLE_LOG")
            # Download Langfuse traces if available
            BUNDLE_ARGS+=(--fetch-langfuse)
            uv run --no-sync python -m benchmarks.helpers.bundle "${BUNDLE_ARGS[@]}"
            rm -f "$REPORT_TMP"
        fi
    fi
else
    echo -e "${RED:-}✗ Oak Health Insurance evaluation failed (exit code: $EVAL_EXIT)${NC:-}"
fi

exit $EVAL_EXIT
