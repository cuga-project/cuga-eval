#!/bin/bash
# BPO Benchmark Evaluation Script
#
# Starts required servers, runs evaluation, and cleans up on exit.
#
# Usage:
#   ./eval.sh                                                        # Run default data/bpo_test_suite_v1.json
#   ./eval.sh --tasks data/tasks_http_errors.json                    # Run only HTTP error tests
#   ./eval.sh --tasks data/bpo_test_suite_v1.json data/tasks_http_errors.json  # Run multiple task files
#   ./eval.sh --task 1                                               # Run specific task (passed through)
#   ./eval.sh --task 1 2 3                                           # Run multiple tasks (passed through)
#   ./eval.sh --task 1 --verbose                                     # With verbose output
#
# Parameters:
#   --tasks file1.json [file2.json ...]  - Task JSON file paths to evaluate (maps to --data in eval_bench_sdk.py)
#                                          Defaults to data/bpo_test_suite_v1.json if not provided.
#   All other arguments are passed through to eval_bench_sdk.py.
#
# Environment variables:
#   MCP_SERVERS_FILE  - Path to MCP servers config (default: benchmarks/bpo/mcp_servers/bpo.yaml)
#   SKIP_SERVER_START - Set to "true" to skip starting servers (use existing)

set -e

# Script paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Source common helpers (provides colors, wait_for_server, port_in_use, etc.)
if [ -f "$PROJECT_ROOT/benchmarks/helpers/common.sh" ]; then
    source "$PROJECT_ROOT/benchmarks/helpers/common.sh"
fi

# Server ports
FASTAPI_PORT=8095
REGISTRY_PORT=8001

# PIDs for cleanup
FASTAPI_PID=""
REGISTRY_PID=""

# Default MCP servers file (can be overridden via environment variable)
MCP_SERVERS_FILE="${MCP_SERVERS_FILE:-benchmarks/bpo/mcp_servers/bpo.yaml}"

# Cleanup function - runs on exit, error, or interrupt
# When SKIP_SERVER_CLEANUP=true (set by compare.sh), servers are left running.
cleanup() {
    local exit_code=$?
    echo ""
    echo -e "${YELLOW:-}Cleaning up...${NC:-}"

    if [ "${SKIP_SERVER_CLEANUP:-false}" != "true" ]; then
        # Kill FastAPI server if we started it
        if [ -n "$FASTAPI_PID" ]; then
            if kill -0 "$FASTAPI_PID" 2>/dev/null; then
                echo -e "${BLUE:-}Stopping FastAPI server (PID: $FASTAPI_PID)${NC:-}"
                kill "$FASTAPI_PID" 2>/dev/null || true
                wait "$FASTAPI_PID" 2>/dev/null || true
            fi
        fi

        # Kill registry server if we started it
        if [ -n "$REGISTRY_PID" ]; then
            if kill -0 "$REGISTRY_PID" 2>/dev/null; then
                echo -e "${BLUE:-}Stopping registry server (PID: $REGISTRY_PID)${NC:-}"
                kill "$REGISTRY_PID" 2>/dev/null || true
                wait "$REGISTRY_PID" 2>/dev/null || true
            fi
        fi

        # Also kill any child processes that might have been spawned
        # (uvicorn spawns worker processes)
        pkill -f "uvicorn benchmarks.bpo.main:app.*--port.*$FASTAPI_PORT" 2>/dev/null || true
        pkill -f "api_registry_server.*--port.*$REGISTRY_PORT" 2>/dev/null || true
    fi

    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN:-}Cleanup complete.${NC:-}"
    else
        echo -e "${RED:-}Cleanup complete (script exited with code $exit_code).${NC:-}"
    fi

    # RUN_MARKER (if created) is only used up to the LATEST_RESULT lookup right
    # after the evaluator exits; clean it up here instead of a dedicated trap so
    # it can't leak on SIGKILL/early-abort without clobbering this EXIT trap.
    [ -n "${RUN_MARKER:-}" ] && rm -f "$RUN_MARKER"

    exit $exit_code
}

# Set up trap for cleanup on EXIT, INT (Ctrl+C), TERM, and ERR
trap cleanup EXIT INT TERM ERR

# Print header
echo -e "${BLUE:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
echo -e "${BLUE:-}║  BPO Benchmark Evaluation (CUGA Internal)                  ║${NC:-}"
echo -e "${BLUE:-}╚════════════════════════════════════════════════════════════╝${NC:-}"
echo ""

# Change to project root
cd "$PROJECT_ROOT"

# Load environment configuration
echo -e "${YELLOW:-}Loading configuration...${NC:-}"
source "$SCRIPT_DIR/../helpers/load_env.sh" "bpo"

# Capture console output to a log file for reproducibility bundles
CONSOLE_LOG="/tmp/bpo_console.log"
exec > >(tee "$CONSOLE_LOG") 2>&1

# Export MCP_SERVERS_FILE for the registry
export MCP_SERVERS_FILE
echo -e "${GREEN:-}✓${NC:-} MCP_SERVERS_FILE: $MCP_SERVERS_FILE"
echo ""

# Parse --tasks arguments from the command line, collecting remaining args to pass through.
# --tasks accepts one or more file paths and maps to --data in eval_bench_sdk.py.
# Paths are resolved relative to SCRIPT_DIR (benchmarks/bpo/) since the script later
# does cd to PROJECT_ROOT.
TASK_FILES=()
PASSTHROUGH_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tasks)
            shift
            # Collect all non-flag arguments following --tasks as task file paths
            while [[ $# -gt 0 && "$1" != --* ]]; do
                # Resolve relative paths against the script directory
                if [[ "$1" = /* ]]; then
                    TASK_FILES+=("$1")
                else
                    TASK_FILES+=("$SCRIPT_DIR/$1")
                fi
                shift
            done
            ;;
        --no-bundle)
            NO_BUNDLE=true
            shift
            ;;
        --bundle-zip)
            BUNDLE_ZIP=true
            shift
            ;;
        --model-profile)
            MODEL_PROFILE="$2"
            shift 2
            ;;
        --agent)
            AGENT="$2"
            shift 2
            ;;
        --verbose|-v|--quiet|-q)
            PASSTHROUGH_ARGS+=("$1")
            shift
            ;;
        --help|-h)
            echo "Usage: ./eval.sh [--tasks file1.json [file2.json ...]] [--task ID ...] [--verbose|--quiet]"
            echo ""
            echo "Options:"
            echo "  --tasks file1 [file2 ...]  Task JSON file paths relative to benchmarks/bpo/ (default: data/bpo_test_suite_v1.json)"
            echo "  --task ID [ID ...]         Run specific task(s) by ID/name"
            echo "  --no-bundle                Skip reproducibility bundle creation"
            echo "  --bundle-zip               Create zip archive of bundle"
            echo "  --model-profile <name>     Model profile (for bundle metadata)"
            echo "  --agent <name>             Agent to run (cuga, react; default: cuga)"
            echo "  --no-policies              Disable CUGA policies (for baselining)"
            echo "  --verbose, -v              Enable DEBUG-level output"
            echo "  --quiet, -q                Suppress INFO output (WARNING and above only)"
            echo ""
            echo "Examples:"
            echo "  ./eval.sh                                                        # default suite"
            echo "  ./eval.sh --tasks data/tasks_http_errors.json                    # error tests only"
            echo "  ./eval.sh --task 1 2 --bundle-zip                                # with zip bundle"
            exit 0
            ;;
        *)
            PASSTHROUGH_ARGS+=("$1")
            shift
            ;;
    esac
done

# Apply --model-profile after load_env + arg parsing. common.sh is sourced
# unconditionally above; hard-fail loudly if that ever stops being true
# instead of silently skipping model-profile application.
declare -F finalize_model_config >/dev/null || { echo "Error: common.sh not sourced (finalize_model_config unavailable)" >&2; exit 1; }
finalize_model_config || exit 1

# Validate --agent selection before any server/process side effects (fast-fail)
if [ "${AGENT:-cuga}" = "codeact" ]; then
    echo -e "${RED:-}Error: --agent codeact is supported only by the appworld benchmark.${NC:-}"
    exit 2
fi

# Build the --data arguments for eval_bench_sdk.py
if [ ${#TASK_FILES[@]} -eq 0 ]; then
    # Default: use the standard test suite
    DATA_ARGS=(--data "$SCRIPT_DIR/data/bpo_test_suite_v1.json")
else
    DATA_ARGS=(--data "${TASK_FILES[@]}")
fi

echo -e "${GREEN:-}✓${NC:-} Task files: ${DATA_ARGS[*]}"
echo ""

# Start servers unless SKIP_SERVER_START is set
if [ "${SKIP_SERVER_START:-false}" != "true" ]; then

    # Kill any stale process on the FastAPI port before starting
    if port_in_use $FASTAPI_PORT; then
        echo -e "${YELLOW:-}Killing existing process on port $FASTAPI_PORT...${NC:-}"
        lsof -ti :$FASTAPI_PORT | xargs kill 2>/dev/null || true
        sleep 1
    fi

    echo -e "${YELLOW:-}Starting FastAPI server on port $FASTAPI_PORT...${NC:-}"
    uv run uvicorn benchmarks.bpo.main:app --port $FASTAPI_PORT > /tmp/bpo_fastapi.log 2>&1 &
    FASTAPI_PID=$!

    if ! wait_for_server "http://127.0.0.1:$FASTAPI_PORT/health" "FastAPI server" 30; then
        echo -e "${RED:-}Error: FastAPI server failed to start${NC:-}"
        echo "Check logs at /tmp/bpo_fastapi.log"
        cat /tmp/bpo_fastapi.log | tail -20
        exit 1
    fi
    echo -e "${GREEN:-}✓${NC:-} FastAPI server started (PID: $FASTAPI_PID)"

    # Kill any stale process on the registry port before starting
    if port_in_use $REGISTRY_PORT; then
        echo -e "${YELLOW:-}Killing existing process on port $REGISTRY_PORT...${NC:-}"
        lsof -ti :$REGISTRY_PORT | xargs kill 2>/dev/null || true
        sleep 1
    fi

    echo -e "${YELLOW:-}Starting registry server on port $REGISTRY_PORT...${NC:-}"
    MCP_SERVERS_FILE="$MCP_SERVERS_FILE" uv run registry > /tmp/bpo_registry.log 2>&1 &
    REGISTRY_PID=$!

    if ! wait_for_server "http://127.0.0.1:$REGISTRY_PORT/" "registry server" 30; then
        echo -e "${RED:-}Error: Registry server failed to start${NC:-}"
        echo "Check logs at /tmp/bpo_registry.log"
        cat /tmp/bpo_registry.log | tail -20
        exit 1
    fi
    echo -e "${GREEN:-}✓${NC:-} Registry server started (PID: $REGISTRY_PID)"

    # Verify BPO app is registered
    echo -n "Verifying BPO app registration..."
    APPS=$(curl -s "http://127.0.0.1:$REGISTRY_PORT/applications" 2>/dev/null || echo "[]")
    if echo "$APPS" | grep -q '"name".*:.*"bpo"'; then
        echo -e " ${GREEN:-}verified${NC:-}"
    else
        echo -e " ${RED:-}not found${NC:-}"
        echo -e "${RED:-}Error: BPO app not registered in registry${NC:-}"
        echo "Registry returned: $APPS"
        echo "Check MCP_SERVERS_FILE: $MCP_SERVERS_FILE"
        exit 1
    fi

    # Give registry a moment to fully process and cache the tools
    echo -n "Waiting for registry to fully initialize tools..."
    sleep 2
    echo -e " ${GREEN:-}ready${NC:-}"

    echo ""
else
    echo -e "${YELLOW:-}Skipping server startup (SKIP_SERVER_START=true)${NC:-}"
    echo ""
fi

# Run evaluation
echo -e "${YELLOW:-}Starting evaluation...${NC:-}"
echo ""

# Unique per-process ID (timestamp + PID) so concurrent runs on this host never
# collide, even if started in the same wall-clock second. Exported so the SDK
# evaluator embeds it in its result filename (see save_evaluation_results).
RUN_ID="$(date +%Y%m%d_%H%M%S)_$$"
export EVAL_RUN_ID="$RUN_ID"

# Marker whose mtime marks the start of THIS run, used only as a fallback if
# for some reason the result file doesn't carry EVAL_RUN_ID. NOTE: mtime-newer
# alone is not run-scoped — it can still pick up a concurrent sibling run's
# report, not just a stale one. POSIX -newer is portable to BSD/macOS (unlike
# -newermt). Mirrors the AppWorld harness.
RUN_MARKER=$(mktemp "${TMPDIR:-/tmp}/bpo_run_marker.XXXXXX")

# Capture the evaluator's exit code instead of letting `set -e` + the ERR trap
# abort here — an abort would skip both the bundle and the failure banner below
# (the else branch was previously dead code).
set +e
# Run with resolved --data args and any remaining passthrough arguments
if [ "${AGENT:-cuga}" = "react" ]; then
    uv run python -m benchmarks.bpo.eval_bench_sdk_react "${DATA_ARGS[@]}" "${PASSTHROUGH_ARGS[@]}"
else
    uv run python -m benchmarks.bpo.eval_bench_sdk "${DATA_ARGS[@]}" "${PASSTHROUGH_ARGS[@]}"
fi
EVAL_EXIT_CODE=$?
set -e

# Select only a result file produced by this run. Prefer an exact match on our
# unique RUN_ID (true run-scoping, safe under concurrent runs); fall back to
# mtime-newer-than-marker otherwise. (stderr is not redirected to /dev/null
# here — a missing/unreadable results dir should surface as a real error, not
# silently look like "no fresh result".)
LATEST_RESULT=""
if [ -d "$SCRIPT_DIR/results" ]; then
    LATEST_RESULT=$(find "$SCRIPT_DIR/results" -name "bpo_${RUN_ID}.json" -type f | sort | tail -1)
    if [ -z "$LATEST_RESULT" ]; then
        LATEST_RESULT=$(find "$SCRIPT_DIR/results" -name 'bpo_*.json' -type f -newer "$RUN_MARKER" | sort | tail -1)
    fi
else
    echo -e "${RED:-}✗ $SCRIPT_DIR/results does not exist — the evaluator never got as far as writing a report.${NC:-}" >&2
fi

echo ""
if [ $EVAL_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
    echo -e "${GREEN:-}║  Evaluation completed successfully                         ║${NC:-}"
    echo -e "${GREEN:-}╚════════════════════════════════════════════════════════════╝${NC:-}"

    # A clean exit MUST come with a fresh result from this run. Refuse to bundle
    # otherwise: the old `ls -t | head -1` fallback silently bundled a previous
    # run's report as if it were this run's results.
    if [ -z "$LATEST_RESULT" ]; then
        echo -e "${RED:-}✗ Evaluator exited 0 but wrote no fresh result file — refusing to bundle stale results.${NC:-}"
        echo -e "${RED:-}  The evaluator was likely terminated before saving; check the console log above.${NC:-}"
        exit 1
    fi

    # Create reproducibility bundle unless skipped
    if [ "${NO_BUNDLE:-false}" != "true" ]; then
        echo ""
        echo -e "${YELLOW:-}Creating reproducibility bundle...${NC:-}"

        # Generate eval report
        REPORT_TMP=$(mktemp /tmp/bpo_eval_report_XXXXXX)
        uv run --no-sync python -m benchmarks.helpers.compare_report eval \
            --result-file "$LATEST_RESULT" --output "$REPORT_TMP"

        BUNDLE_ARGS=(assemble --benchmark bpo
            --result-files "$LATEST_RESULT"
            --task-files "${DATA_ARGS[@]:1}"
            --policies-dir "$SCRIPT_DIR/policies"
            --report "$REPORT_TMP")
        if [ -n "$MODEL_PROFILE" ]; then
            BUNDLE_ARGS+=(--model-profile "$MODEL_PROFILE")
        fi
        for arg in "${PASSTHROUGH_ARGS[@]}"; do
            if [[ "$arg" == "--no-policies" ]]; then
                BUNDLE_ARGS+=(--no-policies)
                break
            fi
        done
        if [ "${BUNDLE_ZIP:-false}" = "true" ]; then
            BUNDLE_ARGS+=(--zip)
        fi
        # Include cuga trajectories
        TRAJ_DIR=$(find_latest_trajectory "$SCRIPT_DIR/logging/trajectory_data")
        if [ -n "$TRAJ_DIR" ]; then
            BUNDLE_ARGS+=(--trajectory-dir "$TRAJ_DIR")
        fi
        # Include server and console logs
        BUNDLE_ARGS+=(--log-files /tmp/bpo_fastapi.log /tmp/bpo_registry.log "$CONSOLE_LOG")
        # Download Langfuse traces if available
        BUNDLE_ARGS+=(--fetch-langfuse)
        uv run python -m benchmarks.helpers.bundle "${BUNDLE_ARGS[@]}"
        rm -f "$REPORT_TMP"
    fi
else
    echo -e "${RED:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
    echo -e "${RED:-}║  Evaluation completed with errors (exit code: $EVAL_EXIT_CODE)           ║${NC:-}"
    echo -e "${RED:-}╚════════════════════════════════════════════════════════════╝${NC:-}"
fi

# Exit with evaluation exit code (cleanup will run via trap)
exit $EVAL_EXIT_CODE
