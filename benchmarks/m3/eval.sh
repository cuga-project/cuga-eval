#!/bin/bash
# M3 benchmark eval script (called by top-level scripts/eval.sh or directly).
#
# Starts the registry server, runs M3 evaluation, and cleans up.
# Works from any directory — just run ./eval.sh
#
# Usage:
#   ./eval.sh                        # Default evaluation
#   ./eval.sh --multiturn             # Multi-turn evaluation
#   ./eval.sh --task hockey_395_0     # Single task

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
        echo "Usage: ./eval.sh [--multiturn] [--m3-data PATH] [--capability NAME] [--task TASK] [--difficulty LEVEL] [--no-bundle] [--bundle-zip] [--model-profile NAME]"
        echo ""
        echo "Options:"
        echo "  --multiturn                 Run multi-turn evaluation"
        echo "  --m3-data PATH              Load merged samples from an M3 data source — either a"
        echo "                              .zip or a directory containing capability_<id>_* subdirs."
        echo "                              Uses config/m3_registry_m3_data.yaml. Scores by tool-call count."
        echo "  --no-ground-truth           Run --m3-data on input-only data (no output/ folder)."
        echo "                              Skips evaluation/scoring; collects predictions only into"
        echo "                              results/_vakra/prediction/<domain>.json."
        echo "  --capability NAME           Filter by capability/service (e.g. 'm3_task_2'). Preferred."
        echo "                              --task is kept as an alias."
        echo "  --domain DOMAIN             Filter by domain (e.g. 'hockey'). Combine with --capability."
        echo "  --task TASK                 Alias of --capability; also accepts test-case IDs like 'hockey_395_0'"
        echo "  --difficulty LEVEL          Filter by difficulty level (easy, medium, hard)"
        echo "  --no-bundle                 Skip reproducibility bundle creation"
        echo "  --bundle-zip                Create zip archive of bundle"
        echo "  --model-profile <name>      Model profile (for bundle metadata)"
        echo ""
        echo "Examples:"
        echo "  ./eval.sh                                                          # Default evaluation"
        echo "  ./eval.sh --multiturn                                              # Multi-turn evaluation"
        echo "  ./eval.sh --m3-data /some/dir                                      # Directory of input/output files"
        echo "  ./eval.sh --m3-data some.zip                                       # Zip archive of input/output files"
        echo "  ./eval.sh --m3-data some.zip --capability m3_task_2 --domain hockey  # One capability, one domain"
        echo "  ./eval.sh --task hockey_395_0                                      # Single test case"
        exit 0
    fi
done

# Parse args
MULTITURN=false
M3_DATA=false
M3_DATA_PATH=""
NO_GROUND_TRUTH=false
PASSTHROUGH_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --multiturn)
            MULTITURN=true
            shift
            ;;
        --m3-data)
            M3_DATA=true
            if [[ -z "${2:-}" || "$2" == --* ]]; then
                echo "Error: --m3-data requires a path (zip file or directory)" >&2
                exit 2
            fi
            M3_DATA_PATH="$2"
            shift 2
            ;;
        --no-ground-truth)
            NO_GROUND_TRUTH=true
            shift
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
        *)
            PASSTHROUGH_ARGS+=("$1")
            shift
            ;;
    esac
done


REGISTRY_PORT=8001
REGISTRY_PID=""

# Timestamp captured before the eval starts. Used by create_bundle to pick
# only the result file(s) produced by *this* run, not a leftover from earlier.
RUN_START_TS=$(date +%s)
BUNDLE_DONE=false

# Best-effort bundle creation. Called from the success path AND from the
# cleanup trap on Ctrl-C / crash / non-zero exit (issues #91, #92), so a
# long run that is interrupted still leaves logs + trajectories + any
# results that were already written. Skips silently if --no-bundle was
# passed, or if nothing from this run was produced yet.
create_bundle() {
    [ "$BUNDLE_DONE" = "true" ] && return 0
    [ "${NO_BUNDLE:-false}" = "true" ] && return 0
    BUNDLE_DONE=true

    echo ""
    echo -e "${YELLOW:-}Creating reproducibility bundle...${NC:-}"

    # Find the most recent result file produced by *this* run (mtime newer
    # than RUN_START_TS). If the run was killed before any save, there'll be
    # nothing here and we skip the bundle — there's nothing meaningful to
    # bundle without at least one results JSON.
    local latest_result=""
    local f
    for f in $(ls -t "$SCRIPT_DIR/results"/m3_*.json "$SCRIPT_DIR/results"/multiturn_*.json 2>/dev/null); do
        local f_mtime
        f_mtime=$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null)
        if [ -n "$f_mtime" ] && [ "$f_mtime" -ge "$RUN_START_TS" ]; then
            latest_result="$f"
            break
        fi
    done

    if [ -z "$latest_result" ]; then
        echo -e "${YELLOW:-}No result file from this run was found — skipping bundle.${NC:-}"
        echo -e "${YELLOW:-}(Console log is still at $CONSOLE_LOG.)${NC:-}"
        return 0
    fi

    # Determine task file used
    local task_file
    if [ "$MULTITURN" = "true" ]; then
        task_file="$SCRIPT_DIR/data/olympics_mutliturn.json"
    else
        task_file="$SCRIPT_DIR/data/hockey.json"
    fi

    # Generate eval report (best effort — if report generation fails we still
    # want the bundle, so don't let `set -e` abort here).
    local report_tmp
    report_tmp=$(mktemp /tmp/m3_eval_report_XXXXXX)
    uv run --no-sync python -m benchmarks.helpers.compare_report eval \
        --result-file "$latest_result" --output "$report_tmp" || \
        echo -e "${YELLOW:-}Report generation failed — bundling without report.${NC:-}"

    local bundle_args=(assemble --benchmark m3
        --result-files "$latest_result"
        --task-files "$task_file"
        --report "$report_tmp")
    if [ -n "$MODEL_PROFILE" ]; then
        bundle_args+=(--model-profile "$MODEL_PROFILE")
    fi
    if [ "${BUNDLE_ZIP:-false}" = "true" ]; then
        bundle_args+=(--zip)
    fi
    # Include cuga trajectories
    local traj_dir
    traj_dir=$(find_latest_trajectory "$SCRIPT_DIR/logging/trajectory_data")
    if [ -n "$traj_dir" ]; then
        bundle_args+=(--trajectory-dir "$traj_dir")
    fi
    # Include server and console logs (whichever exists)
    local registry_log="$SCRIPT_DIR/registry_server.log"
    if [ -f "$registry_log" ]; then
        bundle_args+=(--log-files "$registry_log" "$CONSOLE_LOG")
    else
        bundle_args+=(--log-files /tmp/m3_registry.log "$CONSOLE_LOG")
    fi
    # Download Langfuse traces if available
    bundle_args+=(--fetch-langfuse)

    uv run --no-sync python -m benchmarks.helpers.bundle "${bundle_args[@]}" || \
        echo -e "${YELLOW:-}Bundle creation reported errors (best-effort).${NC:-}"

    rm -f "$report_tmp"
}

cleanup() {
    local exit_code=$?
    echo ""
    echo -e "${YELLOW:-}Cleaning up...${NC:-}"

    # Best-effort bundle on interrupt/crash. Idempotent (no-op if already
    # created on the success path below). Wrapped in `|| true` so a bundle
    # failure can't override the original exit code.
    create_bundle || true

    if [ "${SKIP_SERVER_CLEANUP:-false}" != "true" ]; then
        if [ -n "$REGISTRY_PID" ] && kill -0 "$REGISTRY_PID" 2>/dev/null; then
            echo -e "${BLUE:-}Stopping registry server (PID: $REGISTRY_PID)${NC:-}"
            kill "$REGISTRY_PID" 2>/dev/null || true
            wait "$REGISTRY_PID" 2>/dev/null || true
        fi
    fi
    exit $exit_code
}

trap cleanup EXIT INT TERM ERR

cd "$PROJECT_ROOT"

# Load environment
source "$PROJECT_ROOT/benchmarks/helpers/load_env.sh" "m3"

# Make sure Python doesn't block-buffer stdout when it's piped through `tee`.
# Without this, print() output from the summary can land after the process
# exits, long after the surrounding loguru stderr stream, making it look like
# the summary never printed.
export PYTHONUNBUFFERED=1

# Capture console output to a log file for reproducibility bundles
CONSOLE_LOG="/tmp/m3_console.log"
exec > >(tee "$CONSOLE_LOG") 2>&1

# Clear stale FINAL SUMMARY from a previous run — only the path that writes
# /tmp/m3_summary.txt (cuga --m3-data) should leave content for the tail block
# below to echo. Without this clear, a react run picks up a cuga run's summary.
rm -f /tmp/m3_summary.txt

echo -e "${BLUE:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
echo -e "${BLUE:-}║  M3 Benchmark Evaluation                                   ║${NC:-}"
echo -e "${BLUE:-}╚════════════════════════════════════════════════════════════╝${NC:-}"
echo ""

# Start registry if not skipped
if [ "${SKIP_SERVER_START:-false}" != "true" ]; then
    # Kill any stale process on the registry port before starting
    if port_in_use $REGISTRY_PORT 2>/dev/null; then
        echo -e "${YELLOW:-}Killing existing process on port $REGISTRY_PORT...${NC:-}"
        lsof -ti :$REGISTRY_PORT | xargs kill 2>/dev/null || true
        sleep 1
    fi

    echo -e "${YELLOW:-}Starting registry server on port $REGISTRY_PORT...${NC:-}"
    bash "$SCRIPT_DIR/run_registry.sh" > /tmp/m3_registry.log 2>&1 &
    REGISTRY_PID=$!

    if wait_for_server "http://127.0.0.1:$REGISTRY_PORT/" "registry server" 60; then
        echo -e "${GREEN:-}✓${NC:-} Registry server started (PID: $REGISTRY_PID)"
    else
        echo -e "${RED:-}Error: Registry server failed to start${NC:-}"
        cat /tmp/m3_registry.log | tail -20
        exit 1
    fi
fi

echo ""

# --no-ground-truth implies --m3-data routing. Validate up-front so the
# user gets a useful error before we spin up registry/agent.
if [ "$NO_GROUND_TRUTH" = "true" ] && [ "$M3_DATA" != "true" ]; then
    echo -e "${RED:-}Error: --no-ground-truth requires --m3-data <path>${NC:-}" >&2
    exit 2
fi

EVAL_M3_EXTRA=()
if [ "$NO_GROUND_TRUTH" = "true" ]; then
    EVAL_M3_EXTRA+=(--no-ground-truth)
fi

# Select eval script
if [ "$M3_DATA" = "true" ]; then
    if [ "${AGENT:-cuga}" = "react" ]; then
        if [ "$NO_GROUND_TRUTH" = "true" ]; then
            echo -e "${YELLOW:-}Running --m3-data --no-ground-truth with react agent (predictions only)...${NC:-}"
        else
            echo -e "${YELLOW:-}Running --m3-data evaluation with react agent...${NC:-}"
        fi
        uv run python -m benchmarks.m3.eval_m3_react \
            --m3-data "$M3_DATA_PATH" \
            "${EVAL_M3_EXTRA[@]}" \
            "${PASSTHROUGH_ARGS[@]}"
    else
        if [ "$NO_GROUND_TRUTH" = "true" ]; then
            echo -e "${YELLOW:-}Running --m3-data --no-ground-truth with cuga agent (predictions only)...${NC:-}"
        else
            echo -e "${YELLOW:-}Running --m3-data evaluation with cuga agent...${NC:-}"
        fi
        uv run python -m benchmarks.m3.eval_m3 \
            --from-config "$SCRIPT_DIR/config/m3_registry_m3_data.yaml" \
            --m3-data "$M3_DATA_PATH" \
            "${EVAL_M3_EXTRA[@]}" \
            "${PASSTHROUGH_ARGS[@]}"
    fi
elif [ "$MULTITURN" = "true" ]; then
    echo -e "${YELLOW:-}Running multi-turn evaluation with agent ${AGENT:-cuga}...${NC:-}"
    if [ "${AGENT:-cuga}" = "react" ]; then
        echo -e "${RED:-}Error: M3 multi-turn evaluation is not available for the react agent${NC:-}"
        exit 1
    else
        uv run python -m benchmarks.m3.eval_m3_multiturn --from-config "$SCRIPT_DIR/config/m3_registry.yaml" "${PASSTHROUGH_ARGS[@]}"
    fi
else
    echo -e "${YELLOW:-}Running single-turn evaluation with agent ${AGENT:-cuga}...${NC:-}"
    if [ "${AGENT:-cuga}" = "react" ]; then
        uv run python -m benchmarks.m3.eval_m3_react --from-config "$SCRIPT_DIR/config/m3_registry.yaml" "${PASSTHROUGH_ARGS[@]}"
    else
        uv run python -m benchmarks.m3.eval_m3 --from-config "$SCRIPT_DIR/config/m3_registry.yaml" "${PASSTHROUGH_ARGS[@]}"
    fi
fi

EVAL_EXIT=$?

if [ $EVAL_EXIT -eq 0 ]; then
    echo -e "${GREEN:-}✓${NC:-} M3 evaluation completed successfully"
    # Create reproducibility bundle (idempotent — cleanup trap also calls
    # this on interrupt/crash, see #91, #92).
    create_bundle
else
    echo -e "${RED:-}✗ M3 evaluation failed (exit code: $EVAL_EXIT)${NC:-}"
    # cleanup trap will call create_bundle to salvage what we have.
fi

# Re-echo the --m3-data summary as the very last thing on screen, so it's
# visible without scrolling past the bundle-creation noise.
if [ "$M3_DATA" = "true" ] && [ -s /tmp/m3_summary.txt ]; then
    echo ""
    echo -e "${GREEN:-}============================== FINAL SUMMARY ==============================${NC:-}"
    cat /tmp/m3_summary.txt
    echo -e "${GREEN:-}===========================================================================${NC:-}"
fi

exit $EVAL_EXIT
