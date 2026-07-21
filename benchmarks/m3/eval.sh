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
        echo "Usage: ./eval.sh [--multiturn] [--m3-data [PATH]] [--eval-key KEY] [--capability NAME] [--task TASK] [--difficulty LEVEL] [--no-bundle] [--bundle-zip] [--model-profile NAME]"
        echo ""
        echo "Options:"
        echo "  --multiturn                 Run multi-turn evaluation"
        echo "  --m3-data [PATH]            Load merged samples from an M3 data source — either a"
        echo "                              .zip or a directory containing capability_<id>_* subdirs."
        echo "                              If PATH is omitted, defaults to the bundled"
        echo "                              data/small_train.zip (CC BY-NC-SA 4.0; see"
        echo "                              benchmarks/m3/data/NOTICE)."
        echo "                              Uses config/m3_registry_m3_data.yaml. Scores by tool-call count."
        echo "  --eval-key KEY              Restrict --m3-data to a named split from"
        echo "                              benchmarks/m3/eval_config.toml (e.g. 'train' or 'test'),"
        echo "                              applied before --task/--domain/--capability filters."
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
        echo "  --no-policies               Disable CUGA policies (for baselining; default: enabled)"
        echo "  --model-profile <name>      Model profile (for bundle metadata)"
        echo ""
        echo "Examples:"
        echo "  ./eval.sh                                                          # Default evaluation"
        echo "  ./eval.sh --multiturn                                              # Multi-turn evaluation"
        echo "  ./eval.sh --m3-data                                                # Bundled small_train.zip (default)"
        echo "  ./eval.sh --m3-data /some/dir                                      # Directory of input/output files"
        echo "  ./eval.sh --m3-data some.zip                                       # Zip archive of input/output files"
        echo "  ./eval.sh --m3-data some.zip --capability m3_task_2 --domain hockey  # One capability, one domain"
        echo "  ./eval.sh --m3-data some.zip --eval-key train                      # Train split only"
        echo "  ./eval.sh --task hockey_395_0                                      # Single test case"
        exit 0
    fi
done

# Parse args
MULTITURN=false
M3_DATA=false
M3_DATA_PATH=""
EVAL_KEY=""
NO_GROUND_TRUTH=false
NO_POLICIES=false
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
                # No path supplied — fall back to the bundled VAKRA-derived
                # dataset (issue #61). CC BY-NC-SA 4.0; see
                # benchmarks/m3/data/NOTICE and benchmarks/m3/data/LICENSE.
                M3_DATA_PATH="$SCRIPT_DIR/data/small_train.zip"
            else
                M3_DATA_PATH="$2"
                shift
            fi
            shift
            ;;
        --eval-key)
            if [[ -z "${2:-}" || "$2" == --* ]]; then
                echo "Error: --eval-key requires a name (e.g. 'train' or 'test')" >&2
                exit 2
            fi
            EVAL_KEY="$2"
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
        --no-policies)
            NO_POLICIES=true
            shift
            ;;
        --model-profile)
            MODEL_PROFILE="$2"
            shift 2
            ;;
        --experiment)
            EXPERIMENT="$2"
            shift 2
            ;;
        --resume)
            RESUME=true
            shift
            ;;
        --resume-experiment)
            RESUME_EXPERIMENT="$2"
            shift 2
            ;;
        --background)
            BACKGROUND=true
            shift
            ;;
        --stop)
            STOP=true
            shift
            ;;
        --restart)
            RESTART=true
            shift
            ;;
        --status)
            STATUS=true
            shift
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

# Validate --agent selection before any server/process side effects (fast-fail)
if [ "${AGENT:-cuga}" = "codeact" ]; then
    echo -e "${RED:-}Error: --agent codeact is supported only by the appworld benchmark.${NC:-}"
    exit 2
fi

if handle_eval_lifecycle "m3" "$0" "${PASSTHROUGH_ARGS[@]}"; then
    exit 0
fi

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
    if [ -n "${WORKSPACE_BUNDLE_DIR:-}" ]; then
        echo -e "${YELLOW:-}Finalizing experiment workspace...${NC:-}"

        local task_file
        if [ "$M3_DATA" = "true" ] && [ -n "$M3_DATA_PATH" ]; then
            # Record the actual --m3-data source used for this run, not the
            # hard-coded example corpus below (which this run didn't read from).
            task_file="$M3_DATA_PATH"
        elif [ "$MULTITURN" = "true" ]; then
            task_file="$SCRIPT_DIR/data/olympics_multiturn.json"
        else
            task_file="$SCRIPT_DIR/data/hockey.json"
        fi

        local fin_extra=(--task-file "$task_file")
        if [ "$NO_POLICIES" != "true" ]; then
            fin_extra+=(--policies-dir "$POLICIES_DIR")
        fi
        local traj_dir
        traj_dir=$(find_latest_trajectory "$SCRIPT_DIR/logging/trajectory_data")
        if [ -n "$traj_dir" ]; then
            fin_extra+=(--trajectory-dir "$traj_dir")
        fi
        local registry_log="$SCRIPT_DIR/registry_server.log"
        local logs=()
        if [ -f "$registry_log" ]; then
            logs+=("$registry_log")
        elif [ -n "${REGISTRY_LOG:-}" ]; then
            logs+=("$REGISTRY_LOG")
        fi
        if [ -n "${CONSOLE_LOG:-}" ]; then
            logs+=("$CONSOLE_LOG")
        fi
        for log in "${logs[@]}"; do
            fin_extra+=(--log-file "$log")
        done
        if [ "${PARTIAL_FINALIZE:-false}" = "true" ]; then
            fin_extra+=(--partial)
        fi

        if ! finalize_experiment_workspace "m3" "${fin_extra[@]}"; then
            echo -e "${YELLOW:-}Experiment workspace finalization reported errors.${NC:-}"
            [ "${PARTIAL_FINALIZE:-false}" = "true" ] || return 1
        fi
        return 0
    fi

    echo -e "${YELLOW:-}Creating reproducibility bundle...${NC:-}"

    # Find the most recent result file produced by *this* run (mtime newer
    # than RUN_START_TS). If the run was killed before any save, there'll be
    # nothing here and we skip the bundle — there's nothing meaningful to
    # bundle without at least one results JSON.
    local latest_result=""
    local f
    for f in $(ls -t "$SCRIPT_DIR/results"/m3_*.json "$SCRIPT_DIR/results"/multiturn_*.json 2>/dev/null); do
        local f_mtime
        f_mtime=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null)
        if [ -n "$f_mtime" ] && [ "$f_mtime" -ge "$RUN_START_TS" ]; then
            latest_result="$f"
            break
        fi
    done

    if [ -z "$latest_result" ]; then
        echo -e "${YELLOW:-}No result file from this run was found — skipping bundle.${NC:-}"
        echo -e "${YELLOW:-}(Console log is still at ${CONSOLE_LOG:-<not set>}.)${NC:-}"
        return 0
    fi

    # Determine task file used
    local task_file
    if [ "$MULTITURN" = "true" ]; then
        task_file="$SCRIPT_DIR/data/olympics_multiturn.json"
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
    if [ -n "$EVAL_KEY" ]; then
        bundle_args+=(--eval-key "$EVAL_KEY")
    fi
    if [ "$NO_POLICIES" = "true" ]; then
        bundle_args+=(--no-policies)
    fi
    if [ -n "$CUGA_GIT_INFO_JSON" ]; then
        bundle_args+=(--cuga-git-info "$CUGA_GIT_INFO_JSON")
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
    local logs=()
    if [ -f "$registry_log" ]; then
        logs+=("$registry_log")
    elif [ -n "${REGISTRY_LOG:-}" ]; then
        logs+=("$REGISTRY_LOG")
    fi
    if [ -n "${CONSOLE_LOG:-}" ]; then
        logs+=("$CONSOLE_LOG")
    fi
    if [ ${#logs[@]} -gt 0 ]; then
        bundle_args+=(--log-files "${logs[@]}")
    fi
    # Download Langfuse traces if available
    bundle_args+=(--fetch-langfuse)

    local bundle_out
    bundle_out=$(uv run --no-sync python -m benchmarks.helpers.bundle "${bundle_args[@]}" 2>&1 | tee /dev/stderr) || \
        echo -e "${YELLOW:-}Bundle creation reported errors (best-effort).${NC:-}"

    rm -f "$report_tmp"

    local bundle_path
    bundle_path=$(echo "$bundle_out" | sed -n 's/^Bundle created: //p' | tail -1)
    if [ -n "$bundle_path" ]; then
        write_legacy_experiment_pointer "m3" "$bundle_path"
    fi
}

cleanup() {
    local exit_code=$?
    finalize_run_state_on_exit "$exit_code"
    echo ""
    echo -e "${YELLOW:-}Cleaning up...${NC:-}"

    if [ $exit_code -ne 0 ] && [ -n "${WORKSPACE_BUNDLE_DIR:-}" ]; then
        PARTIAL_FINALIZE=true
    fi

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

# Apply --model-profile after load_env + arg parsing. common.sh is sourced
# unconditionally above; hard-fail loudly if that ever stops being true
# instead of silently skipping model-profile application.
declare -F finalize_model_config >/dev/null || { echo "Error: common.sh not sourced (finalize_model_config unavailable)" >&2; exit 1; }
finalize_model_config || exit 1

# Single registry port for shell helpers and Python (eval_m3 / cuga-agent both
# read DYNACONF_SERVER_PORTS__REGISTRY via settings.server_ports.registry).
REGISTRY_PORT="${REGISTRY_PORT:-${DYNACONF_SERVER_PORTS__REGISTRY:-8001}}"
export REGISTRY_PORT
export DYNACONF_SERVER_PORTS__REGISTRY="$REGISTRY_PORT"

# Capture the cuga-agent checkout's git state now, before the eval run starts
# — not at bundle-assembly time (after the run finishes). If the checkout is
# shared (e.g. someone switches branches in it for unrelated work) while a
# long run is in flight, a live git query at the end would silently mislabel
# the bundle with whatever happens to be checked out by then.
CUGA_REPO_PATH_RESOLVED="${CUGA_REPO_PATH:-$HOME/workspace/cuga-agent}"
CUGA_GIT_INFO_JSON=""
if [ -d "$CUGA_REPO_PATH_RESOLVED" ]; then
    _cuga_commit=$(git -C "$CUGA_REPO_PATH_RESOLVED" rev-parse --short HEAD 2>/dev/null || echo "")
    _cuga_branch=$(git -C "$CUGA_REPO_PATH_RESOLVED" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    _cuga_dirty=false
    [ -n "$(git -C "$CUGA_REPO_PATH_RESOLVED" status --short 2>/dev/null)" ] && _cuga_dirty=true
    CUGA_GIT_INFO_JSON=$(jq -cn \
        --arg git_commit "$_cuga_commit" \
        --arg git_branch "$_cuga_branch" \
        --argjson git_dirty "$_cuga_dirty" \
        '{"git_commit":$git_commit,"git_branch":$git_branch,"git_dirty":$git_dirty}')
fi
export CUGA_GIT_INFO_JSON

# Make sure Python doesn't block-buffer stdout when it's piped through `tee`.
# Without this, print() output from the summary can land after the process
# exits, long after the surrounding loguru stderr stream, making it look like
# the summary never printed.
export PYTHONUNBUFFERED=1

# Run-scoped directory for artifacts that used to live at fixed /tmp paths
# (issue #115): console log, FINAL SUMMARY hand-off file, outer registry log.
# A pre-set M3_RUN_TMP_DIR wins (compare.sh exports one so it knows where to
# stage logs from after each run); otherwise each run gets a private mktemp
# dir, so concurrent runs on one host can't interleave or clobber each
# other's artifacts.
M3_RUN_TMP_DIR="${M3_RUN_TMP_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/m3_run_XXXXXX")}"
export M3_RUN_TMP_DIR
# eval_m3.py writes its FINAL SUMMARY here (reads M3_SUMMARY_FILE from env).
M3_SUMMARY_FILE="${M3_SUMMARY_FILE:-$M3_RUN_TMP_DIR/m3_summary.txt}"
export M3_SUMMARY_FILE
REGISTRY_LOG="$M3_RUN_TMP_DIR/m3_registry.log"

# Capture console output to a log file for reproducibility bundles
CONSOLE_LOG="$M3_RUN_TMP_DIR/m3_console.log"
exec > >(tee "$CONSOLE_LOG") 2>&1

# Clear stale FINAL SUMMARY from a previous run — only the path that writes
# $M3_SUMMARY_FILE (cuga --m3-data) should leave content for the tail block
# below to echo. Without this clear, a react run picks up a cuga run's summary
# (compare.sh reuses one M3_RUN_TMP_DIR across its sequential runs).
rm -f "$M3_SUMMARY_FILE"

echo -e "${BLUE:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
echo -e "${BLUE:-}║  M3 Benchmark Evaluation                                   ║${NC:-}"
echo -e "${BLUE:-}╚════════════════════════════════════════════════════════════╝${NC:-}"
echo ""

# Kill any stale process on the registry port before delegating to the eval
# script. eval_m3.py / eval_m3_react.py / eval_m3_multiturn all spin up their
# own per-service registry on $REGISTRY_PORT (see start_registry_server() in
# eval_m3.py), so starting another registry here would just collide on the
# port. Opt-in: set SKIP_SERVER_START=false explicitly if you want this script
# to also start an "outer" registry (legacy flow).
if port_in_use $REGISTRY_PORT 2>/dev/null; then
    echo -e "${YELLOW:-}Killing existing process on port $REGISTRY_PORT...${NC:-}"
    lsof -ti :$REGISTRY_PORT | xargs kill 2>/dev/null || true
    sleep 1
fi

# Only the multiturn flow relies on an externally-started ("outer") registry.
# The single-turn and --m3-data flows (eval_m3.py / eval_m3_react.py) start and
# manage their OWN per-service registries on $REGISTRY_PORT, so starting an
# outer registry here would just collide on the port (e.g. compare.sh forces
# SKIP_SERVER_START=false on its first run). Force-skip unless multiturn.
if [ "$MULTITURN" != "true" ]; then
    SKIP_SERVER_START="true"
fi

if [ "${SKIP_SERVER_START:-true}" = "false" ]; then
    echo -e "${YELLOW:-}Starting registry server on port $REGISTRY_PORT...${NC:-}"
    bash "$SCRIPT_DIR/run_registry.sh" > "$REGISTRY_LOG" 2>&1 &
    REGISTRY_PID=$!

    if wait_for_server "http://127.0.0.1:$REGISTRY_PORT/" "registry server" 60; then
        echo -e "${GREEN:-}✓${NC:-} Registry server started (PID: $REGISTRY_PID)"
    else
        echo -e "${RED:-}Error: Registry server failed to start${NC:-}"
        tail -20 "$REGISTRY_LOG"
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

# --eval-key only makes sense against an --m3-data corpus (it restricts that
# corpus to a named train/test split before --task/--domain/--capability).
if [ -n "$EVAL_KEY" ] && [ "$M3_DATA" != "true" ]; then
    echo -e "${RED:-}Error: --eval-key requires --m3-data <path>${NC:-}" >&2
    exit 2
fi

EVAL_M3_EXTRA=()
if [ "$NO_GROUND_TRUTH" = "true" ]; then
    EVAL_M3_EXTRA+=(--no-ground-truth)
fi
if [ -n "$EVAL_KEY" ]; then
    EVAL_M3_EXTRA+=(--eval-key "$EVAL_KEY")
fi
if [ "$NO_POLICIES" = "true" ]; then
    EVAL_M3_EXTRA+=(--no-policies)
    export DYNACONF_POLICY__ENABLED=false
    echo -e "${YELLOW:-}Policy engine disabled (--no-policies)${NC:-}"
fi

# Compile policy markdowns -> policies.json (unless policies are disabled).
# CUGA's policy engine is turned on in benchmarks/m3/config/m3.env via
# DYNACONF_POLICY__ENABLED=true (mirrors bpo). With --no-policies, the engine
# is still on but no policies get loaded — same pattern as benchmarks/bpo.
# Same pattern as benchmarks/bpo: the json is what CUGA loads; the .md files
# are the human-readable source of truth.
POLICIES_DIR="$SCRIPT_DIR/policies"
if [ "$NO_POLICIES" != "true" ] && [ -d "$POLICIES_DIR" ]; then
    if ls "$POLICIES_DIR"/*.md >/dev/null 2>&1; then
        echo -e "${YELLOW:-}Compiling policy markdowns -> policies.json...${NC:-}"
        uv run --no-sync python "$PROJECT_ROOT/scripts/policies_md_to_json.py" \
            --policies-dir "$POLICIES_DIR" \
            --output "$POLICIES_DIR/policies.json"
    fi
fi

if prepare_experiment_workspace "m3"; then
    PASSTHROUGH_ARGS+=(--bundle-dir "$WORKSPACE_BUNDLE_DIR")
    mark_run_state_started
fi

# Select eval script
#
# The evaluator may exit non-zero (task failures, agent crashes, etc.). With
# `set -e` and `trap cleanup ERR` active (see top of script), a non-zero exit
# from the commands below would immediately invoke cleanup() — which calls
# `exit` — before EVAL_EXIT=$? and the success/failure banners below ever run
# (issue #55). Suppress both around the invocation so the exit status falls
# through to the explicit handling; cleanup() still runs via the EXIT trap at
# the bottom of this script.
trap '' ERR
set +e
if [ "$M3_DATA" = "true" ]; then
    if [ "${AGENT:-cuga}" = "react" ]; then
        if [ "$NO_GROUND_TRUTH" = "true" ]; then
            echo -e "${YELLOW:-}Running --m3-data --no-ground-truth with react agent (predictions only)...${NC:-}"
        else
            echo -e "${YELLOW:-}Running --m3-data evaluation with react agent...${NC:-}"
        fi
        uv run --no-sync python -m benchmarks.m3.eval_m3_react \
            --m3-data "$M3_DATA_PATH" \
            "${EVAL_M3_EXTRA[@]}" \
            "${PASSTHROUGH_ARGS[@]}"
    else
        if [ "$NO_GROUND_TRUTH" = "true" ]; then
            echo -e "${YELLOW:-}Running --m3-data --no-ground-truth with cuga agent (predictions only)...${NC:-}"
        else
            echo -e "${YELLOW:-}Running --m3-data evaluation with cuga agent...${NC:-}"
        fi
        uv run --no-sync python -m benchmarks.m3.eval_m3 \
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
        uv run --no-sync python -m benchmarks.m3.eval_m3_multiturn --from-config "$SCRIPT_DIR/config/m3_registry.yaml" "${EVAL_M3_EXTRA[@]}" "${PASSTHROUGH_ARGS[@]}"
    fi
else
    echo -e "${YELLOW:-}Running single-turn evaluation with agent ${AGENT:-cuga}...${NC:-}"
    if [ "${AGENT:-cuga}" = "react" ]; then
        uv run --no-sync python -m benchmarks.m3.eval_m3_react --from-config "$SCRIPT_DIR/config/m3_registry.yaml" "${EVAL_M3_EXTRA[@]}" "${PASSTHROUGH_ARGS[@]}"
    else
        uv run --no-sync python -m benchmarks.m3.eval_m3 --from-config "$SCRIPT_DIR/config/m3_registry.yaml" "${EVAL_M3_EXTRA[@]}" "${PASSTHROUGH_ARGS[@]}"
    fi
fi

EVAL_EXIT=$?
set -e
trap cleanup ERR

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
if [ "$M3_DATA" = "true" ] && [ -s "$M3_SUMMARY_FILE" ]; then
    echo ""
    echo -e "${GREEN:-}============================== FINAL SUMMARY ==============================${NC:-}"
    cat "$M3_SUMMARY_FILE"
    echo -e "${GREEN:-}===========================================================================${NC:-}"
fi

exit $EVAL_EXIT
