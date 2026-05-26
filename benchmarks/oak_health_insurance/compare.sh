#!/bin/bash
# Oak Health Insurance benchmark multi-run comparison script.
#
# Orchestrates multiple eval.sh runs and collects results.
# Supports multi-model comparison.
#
# Usage:
#   ./compare.sh --runs 5                                    # 5 runs, default model
#   ./compare.sh --models gpt-oss,gpt4o --runs 2             # Compare 2 models
#   ./compare.sh --runs 3 --difficulty easy                   # Filter by difficulty
#   ./compare.sh --runs 5 --output report.md                  # Save report
#   ./compare.sh --dry-run                                    # Preview commands

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Source common helpers
if [ -f "$PROJECT_ROOT/benchmarks/helpers/common.sh" ]; then
    source "$PROJECT_ROOT/benchmarks/helpers/common.sh"
fi

# Source model profiles
if [ -f "$PROJECT_ROOT/scripts/model_profiles.sh" ]; then
    source "$PROJECT_ROOT/scripts/model_profiles.sh"
fi

# Defaults
RUNS="${RUNS:-1}"
DRY_RUN="${DRY_RUN:-false}"
OUTPUT_FILE="${OUTPUT_FILE:-}"
MODELS="${MODELS:-gpt-oss}"
AGENT="${AGENT:-cuga}"
AGENTS="${AGENTS:-}"
COMPARE_AGENTS="${COMPARE_AGENTS:-false}"
NO_BUNDLE="${NO_BUNDLE:-false}"
BUNDLE_ZIP="${BUNDLE_ZIP:-false}"
FORWARDED_ARGS=()

# Parse arguments
ARGS=("$@")
idx=0
while [[ $idx -lt ${#ARGS[@]} ]]; do
    arg="${ARGS[$idx]}"
    case "$arg" in
        --runs)
            RUNS="${ARGS[$((idx+1))]}"
            idx=$((idx+2))
            ;;
        --output)
            OUTPUT_FILE="${ARGS[$((idx+1))]}"
            idx=$((idx+2))
            ;;
        --models)
            MODELS="${ARGS[$((idx+1))]}"
            idx=$((idx+2))
            ;;
        --agent)
            AGENT="${ARGS[$((idx+1))]}"
            idx=$((idx+2))
            ;;
        --agents)
            AGENTS="${ARGS[$((idx+1))]}"
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
        --dry-run)
            DRY_RUN=true
            idx=$((idx+1))
            ;;
        *)
            FORWARDED_ARGS+=("${ARGS[$idx]}")
            idx=$((idx+1))
            ;;
    esac
done

# Oak's eval.sh has no --agent flag (only cuga is wired up), so reject any
# attempt to compare agents. Surface the limitation early instead of producing
# duplicate cuga runs labeled as different agents.
if [[ "$COMPARE_AGENTS" == "true" || "$AGENTS" == *,* ]]; then
    echo -e "${RED:-}Error: oak does not support agent comparison.${NC:-}" >&2
    echo "       benchmarks/oak_health_insurance/eval.sh has no --agent flag." >&2
    echo "       Drop --compare-agents / --agents to run a single-agent comparison." >&2
    exit 1
fi
# Single-agent path: relabel runs as "model:cuga" for downstream consistency.
if [[ -z "$AGENTS" ]]; then
    AGENTS="$AGENT"
fi

IFS=',' read -ra MODEL_LIST <<< "$MODELS"

echo -e "${BLUE:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
echo -e "${BLUE:-}║  Oak Health Insurance: Multi-Run Comparison                ║${NC:-}"
echo -e "${BLUE:-}╚════════════════════════════════════════════════════════════╝${NC:-}"
echo ""
echo -e "  Agent:           ${CYAN:-}${AGENTS}${NC:-}"
echo -e "  Models:          ${CYAN:-}${MODELS}${NC:-}"
echo -e "  Runs per model:  ${CYAN:-}${RUNS}${NC:-}"
echo ""

if [[ "$DRY_RUN" == "true" ]]; then
    echo -e "${YELLOW:-}DRY RUN — showing planned commands:${NC:-}"
    for model in "${MODEL_LIST[@]}"; do
        for ((r=1; r<=RUNS; r++)); do
            echo "  [${model}:${AGENTS} run ${r}/${RUNS}] ./eval.sh ${FORWARDED_ARGS[*]}"
        done
    done
    exit 0
fi

RESULTS_DIR="$SCRIPT_DIR/results"
mkdir -p "$RESULTS_DIR"

# Server lifecycle: first eval.sh starts servers; SKIP_SERVER_CLEANUP keeps them
# alive across all runs. compare.sh kills them in its own cleanup trap.
export SKIP_SERVER_START="false"
export SKIP_SERVER_CLEANUP="true"
failed=0
total_runs=0

# ETA bookkeeping (fmt_eta / fmt_duration live in benchmarks/helpers/common.sh).
TOTAL_PLANNED=$(( ${#MODEL_LIST[@]} * RUNS ))
runs_done=0
runs_elapsed_total=0
compare_t0=$(date +%s)

compare_cleanup() {
    echo -e "${YELLOW:-}Stopping servers...${NC:-}"
    kill_port_processes 8090 8001
}
trap compare_cleanup EXIT INT TERM

# Collect result files and trajectories grouped by model (bash 3 compat)
MODEL_RESULT_KEYS=()
MODEL_RESULT_VALS=()
MODEL_TRAJ_KEYS=()
MODEL_TRAJ_VALS=()

for model in "${MODEL_LIST[@]}"; do
    echo -e "${BLUE:-}══════════════════════════════════════════════════════════════${NC:-}"
    echo -e "${CYAN:-}Model: ${model}${NC:-}"
    echo -e "${BLUE:-}══════════════════════════════════════════════════════════════${NC:-}"

    if type apply_model_profile &>/dev/null; then
        apply_model_profile "$model"
    fi

    # Snapshot existing result files and trajectory folders before this model's runs
    before_files=$(ls -1 "$RESULTS_DIR"/oak_health_*.json 2>/dev/null | sort)
    before_trajs=$(find "$SCRIPT_DIR/logging/trajectory_data" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)

    for ((r=1; r<=RUNS; r++)); do
        total_runs=$((total_runs+1))
        echo -e "${CYAN:-}[${model}]${NC:-} Run ${GREEN:-}${r}/${RUNS}${NC:-} (overall ${total_runs}/${TOTAL_PLANNED})"
        if (( runs_done > 0 )); then
            echo -e "  ${YELLOW:-}$(fmt_eta $runs_elapsed_total $runs_done $(( TOTAL_PLANNED - runs_done )))${NC:-}"
        fi

        run_t0=$(date +%s)
        if bash "$SCRIPT_DIR/eval.sh" --no-bundle "${FORWARDED_ARGS[@]}"; then
            run_dur=$(( $(date +%s) - run_t0 ))
            echo -e "${GREEN:-}✓${NC:-} Run $r complete in $(fmt_duration $run_dur)"
        else
            run_dur=$(( $(date +%s) - run_t0 ))
            echo -e "${RED:-}✗ Run $r failed after $(fmt_duration $run_dur)${NC:-}"
            failed=$((failed+1))
        fi
        runs_done=$(( runs_done + 1 ))
        runs_elapsed_total=$(( runs_elapsed_total + run_dur ))

        # After first run, reuse servers for all subsequent runs
        export SKIP_SERVER_START="true"
        echo ""
    done

    # Collect only NEW result files produced by this model's runs
    after_files=$(ls -1 "$RESULTS_DIR"/oak_health_*.json 2>/dev/null | sort)
    recent_files=$(comm -13 <(echo "$before_files") <(echo "$after_files"))
    # Use model:agent label for consistency with m3/appworld/bpo. Oak only ever runs cuga
    # (single-agent path enforced above), so $AGENTS is the resolved single agent.
    MODEL_RESULT_KEYS+=("${model}:${AGENTS}")
    MODEL_RESULT_VALS+=("$recent_files")

    # Collect only NEW trajectory folders produced by this model's runs
    after_trajs=$(find "$SCRIPT_DIR/logging/trajectory_data" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
    recent_trajs=$(comm -13 <(echo "$before_trajs") <(echo "$after_trajs"))
    MODEL_TRAJ_KEYS+=("${model}:${AGENTS}")
    MODEL_TRAJ_VALS+=("$recent_trajs")
done

total_dur=$(( $(date +%s) - compare_t0 ))
echo -e "${GREEN:-}All runs complete.${NC:-} ($failed failed out of $total_runs) — total $(fmt_duration $total_dur)"

if [ -n "$OUTPUT_FILE" ]; then
    echo -e "${GREEN:-}✓${NC:-} Results in: $RESULTS_DIR"
fi

# Create reproducibility bundle unless skipped
if [[ "${NO_BUNDLE:-false}" != "true" ]]; then
    echo ""
    echo -e "${YELLOW:-}Creating comparison bundle...${NC:-}"

    # Build JSON input: {"model": ["file1.json", ...]}
    JSON_PARTS=()
    for ci in "${!MODEL_RESULT_KEYS[@]}"; do
        model="${MODEL_RESULT_KEYS[$ci]}"
        files="${MODEL_RESULT_VALS[$ci]}"
        if [[ -z "$files" ]]; then
            continue
        fi
        file_list=""
        pfirst=true
        for f in $files; do
            if [[ "$pfirst" != "true" ]]; then
                file_list+=","
            fi
            pfirst=false
            file_list+="\"${f}\""
        done
        JSON_PARTS+=("\"${model}\":[${file_list}]")
    done

    JSON_INPUT="{"
    jfirst=true
    for part in "${JSON_PARTS[@]}"; do
        if [[ "$jfirst" != "true" ]]; then
            JSON_INPUT+=","
        fi
        jfirst=false
        JSON_INPUT+="$part"
    done
    JSON_INPUT+="}"

    if [[ "$JSON_INPUT" != "{}" ]]; then
        # Generate comparison report
        echo -e "${YELLOW:-}Generating comparison report...${NC:-}"
        REPORT_TMP=$(mktemp /tmp/oak_report_XXXXXX)
        echo "$JSON_INPUT" | (cd "$PROJECT_ROOT" && uv run --no-sync python -m benchmarks.helpers.compare_report --output "$REPORT_TMP")
        echo ""

        # Build per-model env snapshot for bundle
        MODEL_ENVS_JSON=""
        if type build_model_envs_json &>/dev/null; then
            MODEL_ENVS_JSON=$(build_model_envs_json "${MODEL_LIST[@]}")
        fi

        # Build per-model trajectory dirs JSON
        TRAJ_JSON_PARTS=()
        for ci in "${!MODEL_TRAJ_KEYS[@]}"; do
            tmodel="${MODEL_TRAJ_KEYS[$ci]}"
            tfiles="${MODEL_TRAJ_VALS[$ci]}"
            if [[ -z "$tfiles" ]]; then
                continue
            fi
            tfile_list=""
            tfirst=true
            for f in $tfiles; do
                if [[ "$tfirst" != "true" ]]; then
                    tfile_list+=","
                fi
                tfirst=false
                tfile_list+="\"${f}\""
            done
            TRAJ_JSON_PARTS+=("\"${tmodel}\":[${tfile_list}]")
        done

        TRAJ_JSON_INPUT="{"
        tjfirst=true
        for part in "${TRAJ_JSON_PARTS[@]}"; do
            if [[ "$tjfirst" != "true" ]]; then
                TRAJ_JSON_INPUT+=","
            fi
            tjfirst=false
            TRAJ_JSON_INPUT+="$part"
        done
        TRAJ_JSON_INPUT+="}"

        BUNDLE_CMD=(uv run --no-sync python -m benchmarks.helpers.bundle assemble-compare
            --benchmark oak_health_insurance
            --config-results "$JSON_INPUT"
            --report "$REPORT_TMP"
            --task-files "$SCRIPT_DIR/oak_health_test_suite_v1.json")

        if [[ -n "$MODEL_ENVS_JSON" ]]; then
            BUNDLE_CMD+=(--model-envs "$MODEL_ENVS_JSON")
        fi
        if [[ "$TRAJ_JSON_INPUT" != "{}" ]]; then
            BUNDLE_CMD+=(--trajectory-dirs "$TRAJ_JSON_INPUT")
        fi
        # Include server logs (from last run)
        LOG_JSON="{\"shared\":[\"/tmp/oak_fastapi.log\",\"/tmp/oak_registry.log\",\"/tmp/oak_console.log\"]}"
        BUNDLE_CMD+=(--log-files "$LOG_JSON")
        # Download Langfuse traces if available
        BUNDLE_CMD+=(--fetch-langfuse)
        if [[ "${BUNDLE_ZIP:-false}" == "true" ]]; then
            BUNDLE_CMD+=(--zip)
        fi

        # Bundle CLI needs project root on PYTHONPATH
        (cd "$PROJECT_ROOT" && "${BUNDLE_CMD[@]}")
        rm -f "$REPORT_TMP"
    fi
fi
