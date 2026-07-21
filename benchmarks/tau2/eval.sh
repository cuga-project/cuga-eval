#!/bin/bash
# tau2-bench (τ²) Benchmark Evaluation Script
#
# Runs CUGA on τ² customer-service tasks and (optionally) assembles a
# reproducibility bundle. Unlike bpo/appworld, τ² needs NO servers: its
# orchestrator + user simulator run in-process on a background thread, so there
# is no server lifecycle here. SKIP_SERVER_START / SKIP_SERVER_CLEANUP (set by
# compare.sh) are therefore accepted but no-ops — this is the one place τ² is
# simpler than the other benchmarks.
#
# Usage:
#   ./eval.sh                                              # default: mock subset, 1 task
#   ./eval.sh --subset airline --num-tasks 5              # 5 airline tasks
#   ./eval.sh --subset retail --task task_0 task_3        # specific task ids
#   ./eval.sh --user-simulator-model watsonx/meta-llama/... --verbose
#
# Options:
#   --subset <name>              mock | airline | retail | telecom (default: mock)
#   --task ID [ID ...]           run specific task id(s)
#   --num-tasks N                number of tasks (default: 1)
#   --user-simulator-model M     LiteLLM model string for τ²'s customer LLM
#                                (or set TAU2_USER_SIM_MODEL)
#   --max-steps N                per-task step cap (default: 30)
#   --no-bundle                  skip reproducibility bundle creation
#   --bundle-zip                 create zip archive of bundle
#   --model-profile <name>       model profile (for bundle metadata)
#   --agent <name>               agent to run (cuga; default: cuga)
#   --verbose, -v / --quiet, -q  logging level
#
# Environment variables:
#   TAU2_USER_SIM_MODEL          default user-simulator model
#   WATSONX_* / OPENAI_*         creds for the user-simulator LLM

set -e

# Script paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Source common helpers (colors, find_latest_trajectory, etc.)
if [ -f "$PROJECT_ROOT/benchmarks/helpers/common.sh" ]; then
    source "$PROJECT_ROOT/benchmarks/helpers/common.sh"
fi

# Print header
echo -e "${BLUE:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
echo -e "${BLUE:-}║  tau2-bench (τ²) Evaluation (CUGA)                         ║${NC:-}"
echo -e "${BLUE:-}╚════════════════════════════════════════════════════════════╝${NC:-}"
echo ""

# Change to project root (uv run + module dispatch expect it)
cd "$PROJECT_ROOT"

# Load environment configuration (.env, global.env, tau2.env)
echo -e "${YELLOW:-}Loading configuration...${NC:-}"
source "$SCRIPT_DIR/../helpers/load_env.sh" "tau2"

# Capture console output to a log file for reproducibility bundles. Unique per invocation
# (timestamp + PID) so a multi-subset sweep doesn't clobber earlier subsets' logs; override
# with TAU2_CONSOLE_LOG if you want a fixed path.
CONSOLE_LOG="${TAU2_CONSOLE_LOG:-/tmp/tau2_console_$(date +%Y%m%d_%H%M%S)_$$.log}"
exec > >(tee "$CONSOLE_LOG") 2>&1
echo "Console log: $CONSOLE_LOG"

# τ² runs in-process — no servers. SKIP_SERVER_START/SKIP_SERVER_CLEANUP may be
# exported by compare.sh; we accept them but do nothing, keeping the interface
# identical to bpo/appworld.
if [ "${SKIP_SERVER_START:-false}" = "true" ] || [ "${SKIP_SERVER_CLEANUP:-false}" = "true" ]; then
    echo -e "${BLUE:-}ℹ${NC:-} τ² runs in-process — server flags are no-ops."
    echo ""
fi

# Parse flags: bundle/profile/agent are consumed here; everything else (the τ²
# flags: --subset, --task, --num-tasks, --user-simulator-model, --max-steps,
# --run-id) passes straight through to eval_tau2_sdk.py.
PASSTHROUGH_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
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
            echo "Usage: ./eval.sh [--subset NAME] [--task ID ...] [--num-tasks N] [--user-simulator-model M] [options]"
            echo ""
            echo "Options:"
            echo "  --subset <name>            mock | airline | retail | telecom (default: mock)"
            echo "  --task ID [ID ...]         Run specific task id(s)"
            echo "  --num-tasks N              Number of tasks (default: 1)"
            echo "  --user-simulator-model M   LiteLLM model for τ²'s customer LLM (or TAU2_USER_SIM_MODEL)"
            echo "  --max-steps N              Per-task step cap (default: 30)"
            echo "  --no-bundle                Skip reproducibility bundle creation"
            echo "  --bundle-zip               Create zip archive of bundle"
            echo "  --model-profile <name>     Model profile (for bundle metadata)"
            echo "  --agent <name>             Agent to run (cuga; default: cuga)"
            echo "  --verbose, -v / --quiet, -q  Logging level"
            echo ""
            echo "Examples:"
            echo "  ./eval.sh                                        # default: mock subset, 1 task"
            echo "  ./eval.sh --subset airline --num-tasks 5         # 5 airline tasks"
            echo "  ./eval.sh --subset retail --task task_0 task_3   # specific task ids"
            exit 0
            ;;
        *)
            PASSTHROUGH_ARGS+=("$1")
            shift
            ;;
    esac
done

# Only CUGA is supported on τ² today (the proxy agent is CUGA-specific).
if [ -n "${AGENT:-}" ] && [ "$AGENT" != "cuga" ]; then
    echo -e "${RED:-}Error: --agent '$AGENT' is not supported by the tau2 benchmark (only 'cuga').${NC:-}"
    exit 2
fi

# Apply --model-profile after load_env + arg parsing so the profile actually takes
# effect (sets AGENT_SETTING_CONFIG / MODEL_NAME / OPENAI_* for the run). common.sh is
# sourced unconditionally above; hard-fail loudly if that ever stops being true rather
# than silently skipping model-profile application.
declare -F finalize_model_config >/dev/null || { echo "Error: common.sh not sourced (finalize_model_config unavailable)" >&2; exit 1; }
finalize_model_config || exit 1

# Run evaluation. --max-workers 1 is mandatory: one bridge / "current bridge"
# per process (the entrypoint also enforces it).
echo -e "${YELLOW:-}Starting evaluation...${NC:-}"
echo ""
# Unlike bpo/appworld (which capture the exit code via a `trap ... ERR` cleanup
# handler), τ² has no servers and thus no trap — so drop out of `set -e` here to
# capture the eval's exit code and still run the bundle / error branches below.
set +e
uv run python -m benchmarks.tau2.eval_tau2_sdk --max-workers 1 "${PASSTHROUGH_ARGS[@]}"
EVAL_EXIT_CODE=$?
set -e

echo ""
if [ $EVAL_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
    echo -e "${GREEN:-}║  Evaluation completed successfully                         ║${NC:-}"
    echo -e "${GREEN:-}╚════════════════════════════════════════════════════════════╝${NC:-}"

    # Create reproducibility bundle unless skipped
    if [ "${NO_BUNDLE:-false}" != "true" ]; then
        echo ""
        echo -e "${YELLOW:-}Creating reproducibility bundle...${NC:-}"

        # Results land in CUGA_LOGGING_DIR/results (benchmarks/tau2/logging/results).
        RESULTS_DIR="$SCRIPT_DIR/logging/results"
        LATEST_RESULT=$(ls -t "$RESULTS_DIR"/tau2_*.json 2>/dev/null | head -1)
        if [ -n "$LATEST_RESULT" ]; then
            # Generate eval report
            REPORT_TMP=$(mktemp /tmp/tau2_eval_report_XXXXXX)
            uv run --no-sync python -m benchmarks.helpers.compare_report eval \
                --result-file "$LATEST_RESULT" --output "$REPORT_TMP"

            # τ² tasks come from the τ² data dir (selected by --subset), not local
            # JSON files. --task-files is required by `bundle assemble`, so point it
            # at the run's config manifest — the closest local descriptor of the run
            # (same approach appworld takes with its eval_config.toml).
            BUNDLE_ARGS=(assemble --benchmark tau2
                --result-files "$LATEST_RESULT"
                --task-files "$SCRIPT_DIR/config/tau2.env"
                --report "$REPORT_TMP")
            if [ -n "${MODEL_PROFILE:-}" ]; then
                BUNDLE_ARGS+=(--model-profile "$MODEL_PROFILE")
            fi
            if [ "${BUNDLE_ZIP:-false}" = "true" ]; then
                BUNDLE_ARGS+=(--zip)
            fi
            # Include cuga trajectories if present
            TRAJ_DIR=$(find_latest_trajectory "$SCRIPT_DIR/logging/trajectory_data" 2>/dev/null)
            if [ -n "$TRAJ_DIR" ]; then
                BUNDLE_ARGS+=(--trajectory-dir "$TRAJ_DIR")
            fi
            # Include the console log
            BUNDLE_ARGS+=(--log-files "$CONSOLE_LOG")
            # Download Langfuse traces if available
            BUNDLE_ARGS+=(--fetch-langfuse)
            uv run python -m benchmarks.helpers.bundle "${BUNDLE_ARGS[@]}"
            rm -f "$REPORT_TMP"
        else
            echo -e "${YELLOW:-}No results/tau2_*.json found — skipping bundle.${NC:-}"
        fi
    fi
else
    echo -e "${RED:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
    echo -e "${RED:-}║  Evaluation completed with errors (exit code: $EVAL_EXIT_CODE)           ║${NC:-}"
    echo -e "${RED:-}╚════════════════════════════════════════════════════════════╝${NC:-}"
fi

exit $EVAL_EXIT_CODE
