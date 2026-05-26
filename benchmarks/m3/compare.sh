#!/bin/bash
# M3 benchmark multi-run comparison script.
#
# Orchestrates multiple eval.sh runs and collects results.
# Supports multi-model comparison.
#
# Usage:
#   ./compare.sh --runs 5                                    # 5 runs, default model
#   ./compare.sh --models gpt-oss,gpt4o --runs 2             # Compare 2 models
#   ./compare.sh --runs 3 --multiturn                         # Multi-turn evaluation
#   ./compare.sh --runs 5 --output report.md                  # Save report
#   ./compare.sh --dry-run                                    # Preview commands
#
# Unrecognized flags pass through to eval.sh, e.g.:
#   ./compare.sh --runs 1 --m3-data <path> --no-ground-truth --capability m3_task_2 --domain X
#   (forwards --m3-data, --no-ground-truth, --capability, --domain to eval.sh)

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

# Resolve AGENTS: --compare-agents implies cuga,react; default to singular AGENT.
if [[ "$COMPARE_AGENTS" == "true" && -z "$AGENTS" ]]; then
    AGENTS="cuga,react"
fi
if [[ -z "$AGENTS" ]]; then
    AGENTS="$AGENT"
fi

IFS=',' read -ra MODEL_LIST <<< "$MODELS"
IFS=',' read -ra AGENT_LIST <<< "$AGENTS"

# Build CONFIGS as the cartesian product MODEL_LIST × AGENT_LIST, with labels "model:agent".
CONFIGS=()
for _m in "${MODEL_LIST[@]}"; do
    for _a in "${AGENT_LIST[@]}"; do
        CONFIGS+=("${_m}:${_a}")
    done
done

echo -e "${BLUE:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
echo -e "${BLUE:-}║  M3 Benchmark: Multi-Run Comparison                        ║${NC:-}"
echo -e "${BLUE:-}╚════════════════════════════════════════════════════════════╝${NC:-}"
echo ""
echo -e "  Agents:          ${CYAN:-}${AGENTS}${NC:-}"
echo -e "  Models:          ${CYAN:-}${MODELS}${NC:-}"
echo -e "  Configurations:  ${CYAN:-}${#CONFIGS[@]}${NC:-}"
echo -e "  Runs per config: ${CYAN:-}${RUNS}${NC:-}"
echo ""

if [[ "$DRY_RUN" == "true" ]]; then
    echo -e "${YELLOW:-}DRY RUN — showing planned commands:${NC:-}"
    for config in "${CONFIGS[@]}"; do
        model="${config%%:*}"
        agent="${config##*:}"
        for ((r=1; r<=RUNS; r++)); do
            echo "  [${config} run ${r}/${RUNS}] ./eval.sh --agent ${agent} ${FORWARDED_ARGS[*]}"
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
TOTAL_PLANNED=$(( ${#CONFIGS[@]} * RUNS ))
runs_done=0
runs_elapsed_total=0
compare_t0=$(date +%s)

compare_cleanup() {
    echo -e "${YELLOW:-}Stopping servers...${NC:-}"
    kill_port_processes 8001
}
trap compare_cleanup EXIT INT TERM

# Collect result files and trajectories grouped by config label (bash 3 compat).
# Label format: "model:agent" (extensible to "model:agent:policy" for benchmarks
# that compare additional dimensions, mirroring bpo).
CONFIG_RESULT_KEYS=()
CONFIG_RESULT_VALS=()
CONFIG_TRAJ_KEYS=()
CONFIG_TRAJ_VALS=()

# Per-agent filename discrimination. cuga's eval_m3.py saves result files
# with prefix m3_config_*.json; eval_m3_react.py saves m3_*.json. The plain
# `m3_*.json` glob matches both, so previously a stray react file could land
# in a cuga config's recent_files (and vice-versa). The function below picks
# the right glob for each agent.
_list_results_for_agent() {
    local agent="$1"
    if [[ "$agent" == "cuga" ]]; then
        ls -1 "$RESULTS_DIR"/m3_config_*.json 2>/dev/null | sort
    else
        # react: m3_*.json but NOT m3_config_*.json (and not multiturn either,
        # which is a separate flow).
        ls -1 "$RESULTS_DIR"/m3_*.json 2>/dev/null \
            | grep -vE '/m3_config_|/multiturn_' \
            | sort
    fi
}

for config in "${CONFIGS[@]}"; do
    model="${config%%:*}"
    agent="${config##*:}"

    echo -e "${BLUE:-}══════════════════════════════════════════════════════════════${NC:-}"
    echo -e "${CYAN:-}Configuration: ${config}${NC:-}"
    echo -e "${BLUE:-}══════════════════════════════════════════════════════════════${NC:-}"

    if type apply_model_profile &>/dev/null; then
        apply_model_profile "$model"
    fi

    # Snapshot agent-specific result files and trajectory folders before this
    # config's runs. Filtering by agent prevents stale files from the OTHER
    # agent leaking into this config's recent_files.
    before_files=$(_list_results_for_agent "$agent")
    before_trajs=$(find "$SCRIPT_DIR/logging/trajectory_data" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)

    for ((r=1; r<=RUNS; r++)); do
        total_runs=$((total_runs+1))
        echo -e "${CYAN:-}[${config}]${NC:-} Run ${GREEN:-}${r}/${RUNS}${NC:-} (overall ${total_runs}/${TOTAL_PLANNED})"
        if (( runs_done > 0 )); then
            echo -e "  ${YELLOW:-}$(fmt_eta $runs_elapsed_total $runs_done $(( TOTAL_PLANNED - runs_done )))${NC:-}"
        fi

        run_t0=$(date +%s)
        if bash "$SCRIPT_DIR/eval.sh" --agent "$agent" --no-bundle "${FORWARDED_ARGS[@]}"; then
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

    # Collect only NEW result files produced by this config's runs
    # (matched against this agent's filename pattern).
    after_files=$(_list_results_for_agent "$agent")
    recent_files=$(comm -13 <(echo "$before_files") <(echo "$after_files"))
    CONFIG_RESULT_KEYS+=("$config")
    CONFIG_RESULT_VALS+=("$recent_files")

    # Collect only NEW trajectory folders produced by this config's runs
    after_trajs=$(find "$SCRIPT_DIR/logging/trajectory_data" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
    recent_trajs=$(comm -13 <(echo "$before_trajs") <(echo "$after_trajs"))
    CONFIG_TRAJ_KEYS+=("$config")
    CONFIG_TRAJ_VALS+=("$recent_trajs")
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

    # Build JSON input: {"model:agent": ["file1.json", ...]}
    JSON_PARTS=()
    for ci in "${!CONFIG_RESULT_KEYS[@]}"; do
        config="${CONFIG_RESULT_KEYS[$ci]}"
        files="${CONFIG_RESULT_VALS[$ci]}"
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
        JSON_PARTS+=("\"${config}\":[${file_list}]")
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
        REPORT_TMP=$(mktemp /tmp/m3_report_XXXXXX)
        echo "$JSON_INPUT" | (cd "$PROJECT_ROOT" && uv run --no-sync python -m benchmarks.helpers.compare_report --output "$REPORT_TMP")
        echo ""

        # Build per-model env snapshot for bundle
        MODEL_ENVS_JSON=""
        if type build_model_envs_json &>/dev/null; then
            MODEL_ENVS_JSON=$(build_model_envs_json "${MODEL_LIST[@]}")
        fi

        # Build per-config trajectory dirs JSON: {"model:agent": ["/path/run1", ...]}
        TRAJ_JSON_PARTS=()
        for ci in "${!CONFIG_TRAJ_KEYS[@]}"; do
            tconfig="${CONFIG_TRAJ_KEYS[$ci]}"
            tfiles="${CONFIG_TRAJ_VALS[$ci]}"
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
            TRAJ_JSON_PARTS+=("\"${tconfig}\":[${tfile_list}]")
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

        # Determine task file
        TASK_FILE="$SCRIPT_DIR/data/hockey.json"
        for arg in "${FORWARDED_ARGS[@]}"; do
            if [[ "$arg" == "--multiturn" ]]; then
                TASK_FILE="$SCRIPT_DIR/data/olympics_mutliturn.json"
                break
            fi
        done

        BUNDLE_CMD=(uv run --no-sync python -m benchmarks.helpers.bundle assemble-compare
            --benchmark m3
            --config-results "$JSON_INPUT"
            --report "$REPORT_TMP"
            --task-files "$TASK_FILE")

        if [[ -n "$MODEL_ENVS_JSON" ]]; then
            BUNDLE_CMD+=(--model-envs "$MODEL_ENVS_JSON")
        fi
        if [[ "$TRAJ_JSON_INPUT" != "{}" ]]; then
            BUNDLE_CMD+=(--trajectory-dirs "$TRAJ_JSON_INPUT")
        fi
        # Include server logs (from last run)
        LOG_JSON="{\"shared\":[\"/tmp/m3_registry.log\",\"/tmp/m3_console.log\"]}"
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
