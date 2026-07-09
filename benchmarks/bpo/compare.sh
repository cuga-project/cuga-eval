#!/bin/bash
# Multi-run comparison script for cuga-eval BPO benchmark
#
# Orchestrates multiple eval.sh runs and produces a comparison report
# using compare_results.py. Supports multi-model and policies comparison.
#
# Usage:
#   ./compare.sh --runs 5                                    # 5 runs with default tasks
#   ./compare.sh --runs 3 --verbose                           # 3 runs with verbose output
#   ./compare.sh --runs 5 --output report.md                  # Save report to file
#   ./compare.sh --models gpt-oss,gpt4o --runs 2              # Compare 2 models
#   ./compare.sh --models gpt-oss --compare-policies --runs 2  # With/without policies
#   ./compare.sh --dry-run                                    # Preview commands
#
# Options:
#   --runs <N>            Number of runs per configuration (default: 1)
#   --models <list>       Comma-separated model profiles (default: gpt-oss)
#   --compare-policies    Run both with and without policies for each model
#   --output <file>       Save comparison report to file
#   --no-bundle           Skip reproducibility bundle creation
#   --dry-run             Print what would be run without executing
#   All other args forwarded to eval.sh (e.g. --verbose, --tasks, --task)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Source common helpers if available
if [ -f "$PROJECT_ROOT/benchmarks/helpers/common.sh" ]; then
    source "$PROJECT_ROOT/benchmarks/helpers/common.sh"
else
    # Fallback colors
    GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'
    RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
fi

# Source model profiles
if [ -f "$PROJECT_ROOT/scripts/model_profiles.sh" ]; then
    source "$PROJECT_ROOT/scripts/model_profiles.sh"
fi

# Use env vars from top-level if available, otherwise parse args
RUNS="${RUNS:-1}"
DRY_RUN="${DRY_RUN:-false}"
OUTPUT_FILE="${OUTPUT_FILE:-}"
MODELS="${MODELS:-gpt-oss}"
AGENT="${AGENT:-cuga}"
AGENTS="${AGENTS:-}"
COMPARE_AGENTS="${COMPARE_AGENTS:-false}"
COMPARE_POLICIES=false
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
        --compare-policies)
            COMPARE_POLICIES=true
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
        --dry-run)
            DRY_RUN=true
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

# Split models and agents into arrays
IFS=',' read -ra MODEL_LIST <<< "$MODELS"
IFS=',' read -ra AGENT_LIST <<< "$AGENTS"

# --dotenv forces a single model from .env; reject multi-model comparisons.
if type require_single_model_for_dotenv &>/dev/null; then
    require_single_model_for_dotenv "${MODEL_LIST[@]}" || exit 1
fi

# Build list of configurations: model:agent:policy_flag (3-D cartesian product).
# When --compare-policies is off, we still emit "policies" as the inner dim so
# label format stays consistent (always model:agent:policy).
CONFIGS=()
CONFIG_LABELS=()
for model in "${MODEL_LIST[@]}"; do
    for agent in "${AGENT_LIST[@]}"; do
        if [[ "$COMPARE_POLICIES" == "true" ]]; then
            CONFIGS+=("${model}:${agent}:policies")
            CONFIG_LABELS+=("${model}:${agent}:policies")
            CONFIGS+=("${model}:${agent}:no-policies")
            CONFIG_LABELS+=("${model}:${agent}:no-policies")
        else
            CONFIGS+=("${model}:${agent}:policies")
            CONFIG_LABELS+=("${model}:${agent}:policies")
        fi
    done
done

echo -e "${BLUE:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
echo -e "${BLUE:-}║  BPO Benchmark: Multi-Run Comparison (Internal)            ║${NC:-}"
echo -e "${BLUE:-}╚════════════════════════════════════════════════════════════╝${NC:-}"
echo ""
echo -e "  Agents:            ${CYAN:-}${AGENTS}${NC:-}"
echo -e "  Models:            ${CYAN:-}${MODELS}${NC:-}"
echo -e "  Runs per config:   ${CYAN:-}${RUNS}${NC:-}"
echo -e "  Configurations:    ${CYAN:-}${#CONFIGS[@]}${NC:-}"
if [[ "$COMPARE_AGENTS" == "true" || "$AGENTS" == *,* ]]; then
    echo -e "  Compare agents:    ${CYAN:-}yes${NC:-}"
fi
if [[ "$COMPARE_POLICIES" == "true" ]]; then
    echo -e "  Compare policies:  ${CYAN:-}yes${NC:-}"
fi
if [[ -n "$OUTPUT_FILE" ]]; then
    echo -e "  Output file:       ${CYAN:-}${OUTPUT_FILE}${NC:-}"
fi
if [[ ${#FORWARDED_ARGS[@]} -gt 0 ]]; then
    echo -e "  Extra eval args:   ${CYAN:-}${FORWARDED_ARGS[*]}${NC:-}"
fi
echo ""

# Compare experiment status short-circuit.
if [[ "${STATUS:-false}" == "true" ]]; then
    dispatch_compare_status "bpo"
    exit 0
fi

# Results directory
RESULTS_DIR="$SCRIPT_DIR/results"
mkdir -p "$RESULTS_DIR"

if [[ "$DRY_RUN" == "true" ]]; then
    echo -e "${YELLOW:-}DRY RUN — showing planned commands:${NC:-}"
    echo ""
    for config in "${CONFIGS[@]}"; do
        # config is "model:agent:policy_mode"
        IFS=':' read -r model agent policy_mode <<< "$config"
        for ((r=1; r<=RUNS; r++)); do
            eval_args="--model-profile $model --agent $agent"
            if [[ "$policy_mode" == "no-policies" ]]; then
                eval_args+=" --no-policies"
            fi
            echo -e "  [${config} run ${r}/${RUNS}] ./eval.sh ${eval_args} ${FORWARDED_ARGS[*]}"
        done
    done
    echo ""
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
if prepare_compare_experiment_workspace "bpo"; then
    COMPARE_EXPERIMENT=$(resolve_compare_experiment_name)
    init_compare_state_for_run "$COMPARE_EXPERIMENT" "$TOTAL_PLANNED" "$RUNS" "${CONFIGS[@]}"
fi

compare_cleanup() {
    echo -e "${YELLOW:-}Stopping servers...${NC:-}"
    kill_port_processes 8095 8001
}
trap compare_cleanup EXIT INT TERM

# Collect result files and trajectories grouped by config label (bash 3 compat)
CONFIG_RESULT_KEYS=()
CONFIG_RESULT_VALS=()
CONFIG_TRAJ_KEYS=()
CONFIG_TRAJ_VALS=()

for config in "${CONFIGS[@]}"; do
    # config is "model:agent:policy_mode"
    IFS=':' read -r model agent policy_mode <<< "$config"

    echo -e "${BLUE:-}══════════════════════════════════════════════════════════════${NC:-}"
    echo -e "${CYAN:-}Configuration: ${config}${NC:-}"
    echo -e "${BLUE:-}══════════════════════════════════════════════════════════════${NC:-}"

    # Apply model config (profile + optional .env overrides)
    if type apply_model_config &>/dev/null; then
        if ! apply_model_config "$model"; then
            echo -e "${RED:-}Error: Failed to apply model config '$model'${NC:-}"
            echo -e "${YELLOW:-}Valid profiles: gpt-oss, gpt4o, gpt4.1, opus4.5${NC:-}"
            exit 1
        fi
    fi

    # Build eval args for this configuration
    eval_args=()
    if [[ "$policy_mode" == "no-policies" ]]; then
        eval_args+=(--no-policies)
    fi
    if [[ "$NO_BUNDLE" == "true" ]]; then
        eval_args+=(--no-bundle)
    fi

    # Snapshot existing result files and trajectory folders before running
    before_files=$(ls -1 "$RESULTS_DIR"/bpo_*.json 2>/dev/null | sort)
    before_trajs=$(find "$SCRIPT_DIR/logging/trajectory_data" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)

    for ((r=1; r<=RUNS; r++)); do
        if [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]] && compare_combo_is_done "$config" "$r"; then
            echo -e "${YELLOW:-}Skipping completed combo ${config} run ${r}/${RUNS}${NC:-}"
            runs_done=$(( runs_done + 1 ))
            total_runs=$((total_runs+1))
            continue
        fi

        total_runs=$((total_runs+1))
        echo -e "${BLUE:-}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC:-}"
        echo -e "${CYAN:-}[${config}]${NC:-} Run ${GREEN:-}${r}/${RUNS}${NC:-} (overall ${total_runs}/${TOTAL_PLANNED})"
        if (( runs_done > 0 )); then
            echo -e "  ${YELLOW:-}$(fmt_eta $runs_elapsed_total $runs_done $(( TOTAL_PLANNED - runs_done )))${NC:-}"
        fi

        combo_eval_args=()
        if [[ -n "${COMPARE_EXPERIMENT:-}" ]]; then
            read -r -a combo_eval_args <<< "$(compare_combo_eval_flags "$COMPARE_EXPERIMENT" "$config" "$r")"
            sub_exp=$(uv run python -m benchmarks.helpers.compare_state sub-name \
                --compare-experiment "$COMPARE_EXPERIMENT" --config "$config" --run "$r")
            compare_mark_combo_started "$config" "$r" "$sub_exp"
        fi

        run_t0=$(date +%s)
        run_exit=0
        if "$SCRIPT_DIR/eval.sh" --agent "$agent" "${eval_args[@]}" "${combo_eval_args[@]}" "${FORWARDED_ARGS[@]}"; then
            run_dur=$(( $(date +%s) - run_t0 ))
            echo -e "${GREEN:-}✓${NC:-} Run ${r} complete in $(fmt_duration $run_dur)"
        else
            run_exit=$?
            run_dur=$(( $(date +%s) - run_t0 ))
            echo -e "${RED:-}✗ Run ${r} failed after $(fmt_duration $run_dur)${NC:-}"
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

    # Collect only the NEW result files produced by this config's runs
    after_files=$(ls -1 "$RESULTS_DIR"/bpo_*.json 2>/dev/null | sort)
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

echo -e "${BLUE:-}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC:-}"
total_dur=$(( $(date +%s) - compare_t0 ))
echo -e "${GREEN:-}All runs complete.${NC:-} (${failed} failed out of ${total_runs}) — total $(fmt_duration $total_dur)"
echo ""

if [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]]; then
    # Workspace mode: each combo writes into its own sub-experiment bundle (a
    # sibling of WORKSPACE_BUNDLE_DIR), not into this benchmark's flat
    # results/ scratch dir — the before/after diff above collects nothing for
    # ANY combo, executed or resumed-and-skipped. Source directly from
    # compare_state.json's recorded sub-bundles instead.
    JSON_INPUT=$(cd "$PROJECT_ROOT" && uv run python -m benchmarks.helpers.compare_state \
        bundle-inputs --compare-dir "$WORKSPACE_BUNDLE_DIR" --field config-results)
else
    # Build JSON input for compare_results.py
    # Format: {"model:policies": ["file1.json", ...], "model:no-policies": [...]}
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

    # Join JSON parts
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

echo -e "${YELLOW:-}Generating comparison report...${NC:-}"
echo ""

# Build analysis command
ANALYZE_ARGS=()
if [[ -n "$OUTPUT_FILE" ]]; then
    ANALYZE_ARGS+=(--output "$OUTPUT_FILE")
fi

# Run compare_results.py (synced from BPO-benchmark)
COMPARE_SCRIPT="$SCRIPT_DIR/compare_results.py"
if [[ ! -f "$COMPARE_SCRIPT" ]]; then
    echo -e "${RED:-}Error: compare_results.py not found at ${COMPARE_SCRIPT}${NC:-}"
    echo -e "${YELLOW:-}Run generate_internal.py from BPO-benchmark to sync it.${NC:-}"
    exit 1
fi

# Always save report to temp file for bundle; also to OUTPUT_FILE if specified
REPORT_TMP=$(mktemp /tmp/bpo_report_XXXXXX)
ANALYZE_ARGS+=(--output "$REPORT_TMP")

echo "$JSON_INPUT" | uv run --no-sync python "$COMPARE_SCRIPT" "${ANALYZE_ARGS[@]}"

if [[ -n "$OUTPUT_FILE" ]]; then
    cp "$REPORT_TMP" "$OUTPUT_FILE"
    echo -e "${GREEN:-}✓${NC:-} Report saved to: ${OUTPUT_FILE}"
fi

echo ""
echo -e "${GREEN:-}✓${NC:-} Comparison complete!"

# Create reproducibility bundle unless skipped
if [[ "${NO_BUNDLE:-false}" != "true" ]]; then
    echo ""
    echo -e "${YELLOW:-}Creating comparison bundle...${NC:-}"

    # Find the task files that were used
    TASK_FILE_ARGS=()
    DEFAULT_TASKS="$SCRIPT_DIR/data/bpo_test_suite_v1.json"
    if [[ -f "$DEFAULT_TASKS" ]]; then
        TASK_FILE_ARGS+=(--task-files "$DEFAULT_TASKS")
    fi

    # Build per-model env snapshot for bundle
    MODEL_ENVS_JSON=""
    if type build_model_envs_json &>/dev/null; then
        MODEL_ENVS_JSON=$(build_model_envs_json "${MODEL_LIST[@]}")
    fi

    if [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]]; then
        TRAJ_JSON_INPUT=$(cd "$PROJECT_ROOT" && uv run python -m benchmarks.helpers.compare_state \
            bundle-inputs --compare-dir "$WORKSPACE_BUNDLE_DIR" --field trajectory-dirs)
    else
        # Build per-config trajectory dirs JSON: {"config": ["/path/run1", ...]}
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
        --benchmark bpo
        --config-results "$JSON_INPUT"
        --report "$REPORT_TMP"
        --policies-dir "$SCRIPT_DIR/policies"
        "${TASK_FILE_ARGS[@]}")

    if [[ -n "$MODEL_ENVS_JSON" ]]; then
        BUNDLE_CMD+=(--model-envs "$MODEL_ENVS_JSON")
    fi
    if [[ "$TRAJ_JSON_INPUT" != "{}" ]]; then
        BUNDLE_CMD+=(--trajectory-dirs "$TRAJ_JSON_INPUT")
    fi
    if [[ -n "${WORKSPACE_BUNDLE_DIR:-}" ]]; then
        LOG_JSON=$(cd "$PROJECT_ROOT" && uv run python -m benchmarks.helpers.compare_state \
            bundle-inputs --compare-dir "$WORKSPACE_BUNDLE_DIR" --field log-files)
        [[ "$LOG_JSON" == "{}" ]] && LOG_JSON="{\"shared\":[\"/tmp/bpo_fastapi.log\",\"/tmp/bpo_registry.log\",\"/tmp/bpo_console.log\"]}"
    else
        # Include server logs (from last run)
        LOG_JSON="{\"shared\":[\"/tmp/bpo_fastapi.log\",\"/tmp/bpo_registry.log\",\"/tmp/bpo_console.log\"]}"
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
fi

rm -f "$REPORT_TMP"
