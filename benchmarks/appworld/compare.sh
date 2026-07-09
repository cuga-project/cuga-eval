#!/bin/bash
# AppWorld benchmark multi-run comparison script.
#
# Orchestrates multiple eval.sh runs and collects results.
# Supports multi-model comparison.
#
# Usage:
#   ./compare.sh --runs 5                                    # 5 runs, default model
#   ./compare.sh --models gpt-oss,gpt4o --runs 2             # Compare 2 models
#   ./compare.sh --runs 3 --verbose                           # With verbose output
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
USE_DOTENV="${USE_DOTENV:-false}"
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
        --dry-run)
            DRY_RUN=true
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
        --dotenv)
            USE_DOTENV=true
            idx=$((idx+1))
            ;;
        --experiment)
            EXPERIMENT="${ARGS[$((idx+1))]}"
            idx=$((idx+2))
            ;;
        --resume)
            RESUME=true
            idx=$((idx+1))
            ;;
        --resume-experiment)
            RESUME_EXPERIMENT="${ARGS[$((idx+1))]}"
            idx=$((idx+2))
            ;;
        --status)
            STATUS=true
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

# --dotenv forces a single model from .env; reject multi-model comparisons.
if type require_single_model_for_dotenv &>/dev/null; then
    require_single_model_for_dotenv "${MODEL_LIST[@]}" || exit 1
fi

# Build CONFIGS as the cartesian product MODEL_LIST × AGENT_LIST, with labels "model:agent".
CONFIGS=()
for _m in "${MODEL_LIST[@]}"; do
    for _a in "${AGENT_LIST[@]}"; do
        CONFIGS+=("${_m}:${_a}")
    done
done

echo -e "${BLUE:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
echo -e "${BLUE:-}║  AppWorld Benchmark: Multi-Run Comparison                   ║${NC:-}"
echo -e "${BLUE:-}╚════════════════════════════════════════════════════════════╝${NC:-}"
echo ""
echo -e "  Agents:          ${CYAN:-}${AGENTS}${NC:-}"
echo -e "  Models:          ${CYAN:-}${MODELS}${NC:-}"
echo -e "  Configurations:  ${CYAN:-}${#CONFIGS[@]}${NC:-}"
echo -e "  Runs per config: ${CYAN:-}${RUNS}${NC:-}"
echo ""

if [[ "${STATUS:-false}" == "true" ]]; then
    dispatch_compare_status "appworld"
    exit 0
fi

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

COMPARE_EXPERIMENT=""
if prepare_compare_experiment_workspace "appworld"; then
    COMPARE_EXPERIMENT=$(resolve_compare_experiment_name)
    init_compare_state_for_run "$COMPARE_EXPERIMENT" "$TOTAL_PLANNED" "$RUNS" "${CONFIGS[@]}"
fi

compare_cleanup() {
    echo -e "${YELLOW:-}Stopping servers...${NC:-}"
    kill_port_processes 8000 8001
}
trap compare_cleanup EXIT INT TERM

# Collect result files and trajectories grouped by config label (parallel arrays, bash 3 compat).
# Label format: "model:agent" (extensible to "model:agent:policy" mirroring bpo).
CONFIG_RESULT_KEYS=()
CONFIG_RESULT_VALS=()
CONFIG_TRAJ_KEYS=()
CONFIG_TRAJ_VALS=()

for config in "${CONFIGS[@]}"; do
    model="${config%%:*}"
    agent="${config##*:}"

    echo -e "${BLUE:-}══════════════════════════════════════════════════════════════${NC:-}"
    echo -e "${CYAN:-}Configuration: ${config}${NC:-}"
    echo -e "${BLUE:-}══════════════════════════════════════════════════════════════${NC:-}"

    if type apply_model_config &>/dev/null; then
        if ! apply_model_config "$model"; then
            echo -e "${RED:-}Error: Failed to apply model config '$model'${NC:-}"
            echo -e "${YELLOW:-}Valid profiles: gpt-oss, gpt4o, gpt4.1, opus4.5${NC:-}"
            exit 1
        fi
    fi

    # Snapshot existing result files before this config's runs
    before_files=$(find "$SCRIPT_DIR/experiments/outputs" -name "*_final_report.json" -type f 2>/dev/null | sort)
    # Snapshot existing trajectory folders before this config's runs
    before_trajs=$(find "$SCRIPT_DIR/logging/trajectory_data" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)

    for ((r=1; r<=RUNS; r++)); do
        if [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]] && compare_combo_is_done "$config" "$r"; then
            echo -e "${YELLOW:-}Skipping completed combo ${config} run ${r}/${RUNS}${NC:-}"
            runs_done=$(( runs_done + 1 ))
            total_runs=$((total_runs+1))
            continue
        fi

        total_runs=$((total_runs+1))
        echo -e "${CYAN:-}[${config}]${NC:-} Run ${GREEN:-}${r}/${RUNS}${NC:-} (overall ${total_runs}/${TOTAL_PLANNED})"
        if (( runs_done > 0 )); then
            echo -e "  ${YELLOW:-}$(fmt_eta $runs_elapsed_total $runs_done $(( TOTAL_PLANNED - runs_done )))${NC:-}"
        fi

        combo_eval_args=()
        if [[ -n "${COMPARE_EXPERIMENT:-}" ]]; then
            read -r -a combo_eval_args <<< "$(compare_combo_eval_flags "$COMPARE_EXPERIMENT" "$config" "$r")"
            sub_exp=$(uv run --no-sync python -m benchmarks.helpers.compare_state sub-name \
                --compare-experiment "$COMPARE_EXPERIMENT" --config "$config" --run "$r")
            compare_mark_combo_started "$config" "$r" "$sub_exp"
        fi

        run_t0=$(date +%s)
        run_exit=0
        eval_extra=(--no-bundle)
        [[ -n "${COMPARE_EXPERIMENT:-}" ]] && eval_extra=()
        if bash "$SCRIPT_DIR/eval.sh" --agent "$agent" "${eval_extra[@]}" "${combo_eval_args[@]}" "${FORWARDED_ARGS[@]}"; then
            run_dur=$(( $(date +%s) - run_t0 ))
            echo -e "${GREEN:-}✓${NC:-} Run $r complete in $(fmt_duration $run_dur)"
        else
            run_exit=$?
            run_dur=$(( $(date +%s) - run_t0 ))
            echo -e "${RED:-}✗ Run $r failed after $(fmt_duration $run_dur)${NC:-}"
            failed=$((failed+1))
        fi
        if [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]]; then
            compare_mark_combo_completed "$config" "$r" "$run_exit"
        fi
        runs_done=$(( runs_done + 1 ))
        runs_elapsed_total=$(( runs_elapsed_total + run_dur ))

        # After first run, reuse servers for all subsequent runs
        export SKIP_SERVER_START="true"
        echo ""
    done

    # Collect only NEW result files produced by this config's runs
    after_files=$(find "$SCRIPT_DIR/experiments/outputs" -name "*_final_report.json" -type f 2>/dev/null | sort)
    recent_files=$(comm -13 <(echo "$before_files") <(echo "$after_files"))
    bundle_config=$(resolve_config_key_for_bundle "$config")
    CONFIG_RESULT_KEYS+=("$bundle_config")
    CONFIG_RESULT_VALS+=("$recent_files")

    # Collect only NEW trajectory folders produced by this config's runs
    after_trajs=$(find "$SCRIPT_DIR/logging/trajectory_data" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
    recent_trajs=$(comm -13 <(echo "$before_trajs") <(echo "$after_trajs"))
    CONFIG_TRAJ_KEYS+=("$bundle_config")
    CONFIG_TRAJ_VALS+=("$recent_trajs")
done

total_dur=$(( $(date +%s) - compare_t0 ))
echo -e "${GREEN:-}All runs complete.${NC:-} ($failed failed out of $total_runs) — total $(fmt_duration $total_dur)"
echo ""

# Generate comparison report and create bundle
if [[ "${NO_BUNDLE:-false}" != "true" ]]; then
    echo -e "${YELLOW:-}Creating comparison bundle...${NC:-}"

    if [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]]; then
        # Workspace mode: each combo writes into its own sub-experiment bundle
        # (a sibling of WORKSPACE_BUNDLE_DIR), not into this benchmark's flat
        # results/ scratch dir — the before/after diff above collects nothing
        # for ANY combo, executed or resumed-and-skipped. Source directly from
        # compare_state.json's recorded sub-bundles instead.
        JSON_INPUT=$(cd "$PROJECT_ROOT" && uv run --no-sync python -m benchmarks.helpers.compare_state \
            bundle-inputs --compare-dir "$WORKSPACE_BUNDLE_DIR" --field config-results)
    else
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
    fi

    if [[ "$JSON_INPUT" != "{}" ]]; then
        # Generate comparison report
        echo -e "${YELLOW:-}Generating comparison report...${NC:-}"
        REPORT_TMP=$(mktemp /tmp/appworld_report_XXXXXX)
        echo "$JSON_INPUT" | (cd "$PROJECT_ROOT" && uv run --no-sync python -m benchmarks.helpers.compare_report --output "$REPORT_TMP")
        echo ""

        # Build per-model env snapshot for bundle
        MODEL_ENVS_JSON=""
        if type build_model_envs_json &>/dev/null; then
            MODEL_ENVS_JSON=$(build_model_envs_json "${MODEL_LIST[@]}")
        fi

        if [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]]; then
            TRAJ_JSON_INPUT=$(cd "$PROJECT_ROOT" && uv run --no-sync python -m benchmarks.helpers.compare_state \
                bundle-inputs --compare-dir "$WORKSPACE_BUNDLE_DIR" --field trajectory-dirs)
        else
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
        fi

        BUNDLE_CMD=(uv run --no-sync python -m benchmarks.helpers.bundle assemble-compare
            --benchmark appworld
            --config-results "$JSON_INPUT"
            --report "$REPORT_TMP"
            --task-files "$SCRIPT_DIR/eval_config.toml")

        if [[ -n "$MODEL_ENVS_JSON" ]]; then
            BUNDLE_CMD+=(--model-envs "$MODEL_ENVS_JSON")
        fi
        if [[ "$TRAJ_JSON_INPUT" != "{}" ]]; then
            BUNDLE_CMD+=(--trajectory-dirs "$TRAJ_JSON_INPUT")
        fi
        if [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]]; then
            LOG_JSON=$(cd "$PROJECT_ROOT" && uv run --no-sync python -m benchmarks.helpers.compare_state \
                bundle-inputs --compare-dir "$WORKSPACE_BUNDLE_DIR" --field log-files)
            [[ "$LOG_JSON" == "{}" ]] && LOG_JSON="{\"shared\":[\"/tmp/appworld.log\",\"/tmp/appworld_registry.log\",\"/tmp/appworld_console.log\"]}"
        else
            # Include server logs (from last run)
            LOG_JSON="{\"shared\":[\"/tmp/appworld.log\",\"/tmp/appworld_registry.log\",\"/tmp/appworld_console.log\"]}"
        fi
        BUNDLE_CMD+=(--log-files "$LOG_JSON")
        # Download Langfuse traces if available
        BUNDLE_CMD+=(--fetch-langfuse)
        if [[ "${BUNDLE_ZIP:-false}" == "true" ]]; then
            BUNDLE_CMD+=(--zip)
        fi
        if [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]]; then
            # Finalize in place into the already-existing named compare bundle
            # instead of creating a second, separate timestamped directory.
            BUNDLE_CMD+=(--bundle-dir "$WORKSPACE_BUNDLE_DIR")
        fi

        # Bundle CLI needs project root on PYTHONPATH
        (cd "$PROJECT_ROOT" && "${BUNDLE_CMD[@]}")
        rm -f "$REPORT_TMP"
    fi
fi
