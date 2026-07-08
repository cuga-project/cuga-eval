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

# Align cleanup port with eval.sh / cuga-agent (DYNACONF_SERVER_PORTS__REGISTRY).
source "$PROJECT_ROOT/benchmarks/helpers/load_env.sh" "m3"
REGISTRY_PORT="${REGISTRY_PORT:-${DYNACONF_SERVER_PORTS__REGISTRY:-8001}}"
export REGISTRY_PORT
export DYNACONF_SERVER_PORTS__REGISTRY="$REGISTRY_PORT"

# Capture the cuga-agent checkout's git state now, before any eval.sh run
# starts — not at bundle-assembly time (after every run finishes). A
# multi-run comparison can take a long time; if the cuga-agent checkout is
# shared (e.g. someone switches branches in it for unrelated work) while
# runs are in flight, a live git query at the end would silently mislabel
# the whole bundle with whatever happens to be checked out by then.
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
COMPARE_POLICIES="${COMPARE_POLICIES:-false}"
GLOBAL_NO_POLICIES="${GLOBAL_NO_POLICIES:-false}"
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
        --no-policies)
            GLOBAL_NO_POLICIES=true
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

# Build CONFIGS as the cartesian product MODEL_LIST × AGENT_LIST × POLICY_MODE.
# When --compare-policies is off, the inner dim collapses to a single "policies"
# entry so the label format stays consistent (always model:agent:policy).
CONFIGS=()
for _m in "${MODEL_LIST[@]}"; do
    for _a in "${AGENT_LIST[@]}"; do
        if [[ "$COMPARE_POLICIES" == "true" ]]; then
            CONFIGS+=("${_m}:${_a}:policies")
            CONFIGS+=("${_m}:${_a}:no-policies")
        elif [[ "$GLOBAL_NO_POLICIES" == "true" ]]; then
            CONFIGS+=("${_m}:${_a}:no-policies")
        else
            CONFIGS+=("${_m}:${_a}:policies")
        fi
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
if [[ "$COMPARE_POLICIES" == "true" ]]; then
    echo -e "  Compare policies:  ${CYAN:-}yes (policies vs no-policies)${NC:-}"
elif [[ "$GLOBAL_NO_POLICIES" == "true" ]]; then
    echo -e "  Policies:          ${CYAN:-}disabled (--no-policies)${NC:-}"
fi
echo ""

if [[ "$DRY_RUN" == "true" ]]; then
    echo -e "${YELLOW:-}DRY RUN — showing planned commands:${NC:-}"
    for config in "${CONFIGS[@]}"; do
        IFS=':' read -r model agent policy_mode <<< "$config"
        extra=""
        if [[ "$policy_mode" == "no-policies" ]]; then
            extra=" --no-policies"
        fi
        for ((r=1; r<=RUNS; r++)); do
            echo "  [${config} run ${r}/${RUNS}] ./eval.sh --agent ${agent}${extra} ${FORWARDED_ARGS[*]}"
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

BUNDLE_DONE=false

# Best-effort comparison bundle. Defined as a function so it can be called
# from both the success path at the bottom of the script AND from the
# compare_cleanup trap on interrupt/crash (issues #91, #92). Idempotent via
# BUNDLE_DONE. Reads CONFIG_RESULT_KEYS/VALS and CONFIG_TRAJ_KEYS/VALS which
# are populated by the per-config loop below — on early interrupt those
# arrays may be empty, in which case the function exits cleanly.
create_compare_bundle() {
    [ "$BUNDLE_DONE" = "true" ] && return 0
    [[ "${NO_BUNDLE:-false}" == "true" ]] && return 0
    BUNDLE_DONE=true

    echo ""
    echo -e "${YELLOW:-}Creating comparison bundle...${NC:-}"

    # Build JSON input: {"model:agent": ["file1.json", ...]}
    local JSON_PARTS=()
    local ci config files file_list pfirst f
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

    local JSON_INPUT="{"
    local jfirst=true part
    for part in "${JSON_PARTS[@]}"; do
        if [[ "$jfirst" != "true" ]]; then
            JSON_INPUT+=","
        fi
        jfirst=false
        JSON_INPUT+="$part"
    done
    JSON_INPUT+="}"

    if [[ "$JSON_INPUT" == "{}" ]]; then
        echo -e "${YELLOW:-}No completed runs to bundle — skipping.${NC:-}"
        return 0
    fi

    # Generate comparison report (best-effort)
    echo -e "${YELLOW:-}Generating comparison report...${NC:-}"
    local REPORT_TMP
    REPORT_TMP=$(mktemp /tmp/m3_report_XXXXXX)
    echo "$JSON_INPUT" | (cd "$PROJECT_ROOT" && uv run --no-sync python -m benchmarks.helpers.compare_report --output "$REPORT_TMP") \
        || echo -e "${YELLOW:-}Report generation failed — bundling without comparison report.${NC:-}"
    echo ""

    # Build per-model env snapshot for bundle
    local MODEL_ENVS_JSON=""
    if type build_model_envs_json &>/dev/null; then
        MODEL_ENVS_JSON=$(build_model_envs_json "${MODEL_LIST[@]}")
    fi

    # Build per-config trajectory dirs JSON grouped by run:
    # {"model:agent:policy": [["/run1/domA", ...], ["/run2/domA", ...]]}
    # CONFIG_TRAJ_VALS holds sentinel-delimited groups (one per eval run).
    local TRAJ_JSON_PARTS=()
    local tconfig tgroups groups_json cur_group in_group line
    for ci in "${!CONFIG_TRAJ_KEYS[@]}"; do
        tconfig="${CONFIG_TRAJ_KEYS[$ci]}"
        tgroups="${CONFIG_TRAJ_VALS[$ci]}"
        if [[ -z "$tgroups" ]]; then
            continue
        fi
        groups_json=""
        cur_group=""
        in_group=false
        while IFS= read -r line; do
            if [[ "$line" == "$TRAJ_GROUP_SEP" ]]; then
                if [[ "$in_group" == "true" ]]; then
                    if [[ -n "$groups_json" ]]; then groups_json+=","; fi
                    groups_json+="[${cur_group}]"
                fi
                cur_group=""
                in_group=true
                continue
            fi
            [[ -z "$line" ]] && continue
            if [[ -n "$cur_group" ]]; then cur_group+=","; fi
            cur_group+="\"${line}\""
        done <<< "$tgroups"
        if [[ "$in_group" == "true" ]]; then
            if [[ -n "$groups_json" ]]; then groups_json+=","; fi
            groups_json+="[${cur_group}]"
        fi
        if [[ -z "$groups_json" ]]; then
            continue
        fi
        TRAJ_JSON_PARTS+=("\"${tconfig}\":[${groups_json}]")
    done

    local TRAJ_JSON_INPUT="{"
    local tjfirst=true
    for part in "${TRAJ_JSON_PARTS[@]}"; do
        if [[ "$tjfirst" != "true" ]]; then
            TRAJ_JSON_INPUT+=","
        fi
        tjfirst=false
        TRAJ_JSON_INPUT+="$part"
    done
    TRAJ_JSON_INPUT+="}"

    # Determine task file, and pick up --eval-key (forwarded to each eval.sh
    # run already; captured here too so the compare bundle records it).
    local TASK_FILE="$SCRIPT_DIR/data/hockey.json"
    local EVAL_KEY=""
    local arg i
    for ((i = 0; i < ${#FORWARDED_ARGS[@]}; i++)); do
        arg="${FORWARDED_ARGS[$i]}"
        if [[ "$arg" == "--multiturn" ]]; then
            TASK_FILE="$SCRIPT_DIR/data/olympics_multiturn.json"
        elif [[ "$arg" == "--eval-key" ]]; then
            EVAL_KEY="${FORWARDED_ARGS[$((i+1))]:-}"
        fi
    done

    local BUNDLE_CMD=(uv run --no-sync python -m benchmarks.helpers.bundle assemble-compare
        --benchmark m3
        --config-results "$JSON_INPUT"
        --report "$REPORT_TMP"
        --task-files "$TASK_FILE")
    if [[ -n "$EVAL_KEY" ]]; then
        BUNDLE_CMD+=(--eval-key "$EVAL_KEY")
    fi
    if [[ -n "$CUGA_GIT_INFO_JSON" ]]; then
        BUNDLE_CMD+=(--cuga-git-info "$CUGA_GIT_INFO_JSON")
    fi

    if [[ -n "$MODEL_ENVS_JSON" ]]; then
        BUNDLE_CMD+=(--model-envs "$MODEL_ENVS_JSON")
    fi
    if [[ "$TRAJ_JSON_INPUT" != "{}" ]]; then
        BUNDLE_CMD+=(--trajectory-dirs "$TRAJ_JSON_INPUT")
    fi
    # Build per-config log JSON grouped by run (one console+registry log set
    # per eval run) so each run folder gets its OWN logs:
    # {"model:agent:policy": [["/run1/console.log", ...], ["/run2/...", ...]]}
    local LOG_JSON_PARTS=()
    local lconfig lgroups lgroups_json lcur_group lin_group
    for ci in "${!CONFIG_LOG_KEYS[@]}"; do
        lconfig="${CONFIG_LOG_KEYS[$ci]}"
        lgroups="${CONFIG_LOG_VALS[$ci]}"
        if [[ -z "$lgroups" ]]; then
            continue
        fi
        lgroups_json=""
        lcur_group=""
        lin_group=false
        while IFS= read -r line; do
            if [[ "$line" == "$LOG_GROUP_SEP" ]]; then
                if [[ "$lin_group" == "true" ]]; then
                    if [[ -n "$lgroups_json" ]]; then lgroups_json+=","; fi
                    lgroups_json+="[${lcur_group}]"
                fi
                lcur_group=""
                lin_group=true
                continue
            fi
            [[ -z "$line" ]] && continue
            if [[ -n "$lcur_group" ]]; then lcur_group+=","; fi
            lcur_group+="\"${line}\""
        done <<< "$lgroups"
        if [[ "$lin_group" == "true" ]]; then
            if [[ -n "$lgroups_json" ]]; then lgroups_json+=","; fi
            lgroups_json+="[${lcur_group}]"
        fi
        if [[ -z "$lgroups_json" ]]; then
            continue
        fi
        LOG_JSON_PARTS+=("\"${lconfig}\":[${lgroups_json}]")
    done
    local LOG_JSON="{"
    local ljfirst=true
    for part in "${LOG_JSON_PARTS[@]}"; do
        if [[ "$ljfirst" != "true" ]]; then LOG_JSON+=","; fi
        ljfirst=false
        LOG_JSON+="$part"
    done
    LOG_JSON+="}"
    if [[ "$LOG_JSON" != "{}" ]]; then
        BUNDLE_CMD+=(--log-files "$LOG_JSON")
    fi
    # Download Langfuse traces if available
    BUNDLE_CMD+=(--fetch-langfuse)
    if [[ "${BUNDLE_ZIP:-false}" == "true" ]]; then
        BUNDLE_CMD+=(--zip)
    fi

    # Bundle CLI needs project root on PYTHONPATH
    (cd "$PROJECT_ROOT" && "${BUNDLE_CMD[@]}") \
        || echo -e "${YELLOW:-}Bundle creation reported errors (best-effort).${NC:-}"
    rm -f "$REPORT_TMP"
}

compare_cleanup() {
    # Best-effort comparison bundle on interrupt/crash (issues #91, #92).
    # If we made it past the per-config loop the success path below will have
    # already created the bundle; BUNDLE_DONE makes this idempotent.
    create_compare_bundle || true

    echo -e "${YELLOW:-}Stopping servers...${NC:-}"
    kill_port_processes "${REGISTRY_PORT:-8001}"
    # Staged per-run logs were already copied into the bundle by now.
    [[ -n "${LOG_STAGE_DIR:-}" && -d "$LOG_STAGE_DIR" ]] && rm -rf "$LOG_STAGE_DIR"
}
trap compare_cleanup EXIT INT TERM

# Collect result files and trajectories grouped by config label (bash 3 compat).
# Label format: "model:agent" (extensible to "model:agent:policy" for benchmarks
# that compare additional dimensions, mirroring bpo).
CONFIG_RESULT_KEYS=()
CONFIG_RESULT_VALS=()
CONFIG_TRAJ_KEYS=()
CONFIG_TRAJ_VALS=()
CONFIG_LOG_KEYS=()
CONFIG_LOG_VALS=()

# Per-run logs are snapshotted into this staging dir after each eval.sh run.
# The /tmp console/registry logs are overwritten by the next run, so without a
# snapshot a multi-run bundle would only keep the LAST run's logs. Sentinel
# grouping (one group per run) mirrors the trajectory collection below.
LOG_STAGE_DIR="$(mktemp -d 2>/dev/null || echo "/tmp/m3_log_stage_$$")"
mkdir -p "$LOG_STAGE_DIR"
LOG_GROUP_SEP="@@RUN@@"

# Per-agent filename discrimination. cuga's eval_m3.py saves result files
# with prefix m3_config_*.json; eval_m3_react.py saves m3_*.json. The plain
# `m3_*.json` glob matches both, so previously a stray react file could land
# in a cuga config's recent_files (and vice-versa). The function below picks
# the right glob for each agent.
_list_results_for_agent() {
    local agent="$1"
    # Exclude interrupt/crash partial saves (m3_config_partial_*,
    # m3_config_no_gt_partial_*) — they're incomplete runs and would skew
    # compare_report's totals/pass-rate aggregates if folded in alongside
    # complete runs.
    if [[ "$agent" == "cuga" ]]; then
        ls -1 "$RESULTS_DIR"/m3_config_*.json 2>/dev/null \
            | grep -vE '/m3_config_(no_gt_)?partial_' \
            | sort
    else
        # react: m3_*.json but NOT m3_config_*.json (and not multiturn either,
        # which is a separate flow).
        ls -1 "$RESULTS_DIR"/m3_*.json 2>/dev/null \
            | grep -vE '/m3_config_|/multiturn_' \
            | sort
    fi
}

for config in "${CONFIGS[@]}"; do
    IFS=':' read -r model agent policy_mode <<< "$config"

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

    # Per-config extra args (e.g., --no-policies when comparing policy modes).
    config_extra_args=()
    if [[ "$policy_mode" == "no-policies" ]] || [[ "$GLOBAL_NO_POLICIES" == "true" ]]; then
        config_extra_args+=(--no-policies)
    fi

    # Snapshot agent-specific result files and trajectory folders before this
    # config's runs. Filtering by agent prevents stale files from the OTHER
    # agent leaking into this config's recent_files.
    before_files=$(_list_results_for_agent "$agent")

    # Trajectory dirs are grouped per eval.sh run: cuga writes one folder per
    # domain, so we snapshot before/after EACH run and record that run's new
    # folders as one group. Groups are separated by a sentinel line so the JSON
    # builder below can emit a list-of-lists (one inner list per run). This
    # keeps "one eval.sh run = one bundle run" instead of one run per domain.
    run_before_trajs=$(find "$SCRIPT_DIR/logging/trajectory_data" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
    config_traj_groups=""
    config_log_groups=""
    TRAJ_GROUP_SEP="@@RUN@@"

    for ((r=1; r<=RUNS; r++)); do
        total_runs=$((total_runs+1))
        echo -e "${CYAN:-}[${config}]${NC:-} Run ${GREEN:-}${r}/${RUNS}${NC:-} (overall ${total_runs}/${TOTAL_PLANNED})"
        if (( runs_done > 0 )); then
            echo -e "  ${YELLOW:-}$(fmt_eta $runs_elapsed_total $runs_done $(( TOTAL_PLANNED - runs_done )))${NC:-}"
        fi

        run_t0=$(date +%s)
        if bash "$SCRIPT_DIR/eval.sh" --agent "$agent" --no-bundle "${config_extra_args[@]}" "${FORWARDED_ARGS[@]}"; then
            run_dur=$(( $(date +%s) - run_t0 ))
            echo -e "${GREEN:-}✓${NC:-} Run $r complete in $(fmt_duration $run_dur)"
        else
            run_dur=$(( $(date +%s) - run_t0 ))
            echo -e "${RED:-}✗ Run $r failed after $(fmt_duration $run_dur)${NC:-}"
            failed=$((failed+1))
        fi
        runs_done=$(( runs_done + 1 ))
        runs_elapsed_total=$(( runs_elapsed_total + run_dur ))

        # Record the trajectory folders this single run produced as one group.
        run_after_trajs=$(find "$SCRIPT_DIR/logging/trajectory_data" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
        run_new_trajs=$(comm -13 <(echo "$run_before_trajs") <(echo "$run_after_trajs"))
        config_traj_groups+="${TRAJ_GROUP_SEP}"$'\n'"${run_new_trajs}"$'\n'
        run_before_trajs="$run_after_trajs"

        # Snapshot THIS run's logs before the next eval.sh run overwrites them.
        # Console: eval.sh tees stdout to /tmp/m3_console.log (truncated each
        # run, so it holds exactly this run). Registry: the --m3-data flow lets
        # eval_m3.py manage per-service registries and write to
        # benchmarks/m3/registry_server.log; the multiturn flow uses the outer
        # /tmp/m3_registry.log. Prefer the former, fall back to the latter.
        run_log_dir="$LOG_STAGE_DIR/$(echo "$config" | tr ':/' '__')_run${r}"
        mkdir -p "$run_log_dir"
        run_log_lines=""
        if [[ -f /tmp/m3_console.log ]]; then
            cp -f /tmp/m3_console.log "$run_log_dir/m3_console.log" 2>/dev/null \
                && run_log_lines+="$run_log_dir/m3_console.log"$'\n'
        fi
        reg_src=""
        if [[ -s "$SCRIPT_DIR/registry_server.log" ]]; then
            reg_src="$SCRIPT_DIR/registry_server.log"
        elif [[ -s /tmp/m3_registry.log ]]; then
            reg_src="/tmp/m3_registry.log"
        fi
        if [[ -n "$reg_src" ]]; then
            cp -f "$reg_src" "$run_log_dir/m3_registry.log" 2>/dev/null \
                && run_log_lines+="$run_log_dir/m3_registry.log"$'\n'
        fi
        config_log_groups+="${LOG_GROUP_SEP}"$'\n'"${run_log_lines}"

        # After first run, reuse servers for all subsequent runs
        export SKIP_SERVER_START="true"
        echo ""
    done

    # Collect only NEW result files produced by this config's runs
    # (matched against this agent's filename pattern).
    after_files=$(_list_results_for_agent "$agent")
    recent_files=$(comm -13 <(echo "$before_files") <(echo "$after_files"))
    bundle_config=$(resolve_config_key_for_bundle "$config")
    CONFIG_RESULT_KEYS+=("$bundle_config")
    CONFIG_RESULT_VALS+=("$recent_files")

    # Store the per-run trajectory groups (sentinel-delimited) for this config.
    CONFIG_TRAJ_KEYS+=("$bundle_config")
    CONFIG_TRAJ_VALS+=("$config_traj_groups")

    # Store the per-run log groups (sentinel-delimited) for this config.
    CONFIG_LOG_KEYS+=("$bundle_config")
    CONFIG_LOG_VALS+=("$config_log_groups")
done

total_dur=$(( $(date +%s) - compare_t0 ))
echo -e "${GREEN:-}All runs complete.${NC:-} ($failed failed out of $total_runs) — total $(fmt_duration $total_dur)"

if [ -n "$OUTPUT_FILE" ]; then
    echo -e "${GREEN:-}✓${NC:-} Results in: $RESULTS_DIR"
fi

# Create the comparison bundle (success path). Idempotent — if the cleanup
# trap already created it on interrupt, this is a no-op. See create_compare_bundle
# definition near the top of this script and #91, #92.
create_compare_bundle
