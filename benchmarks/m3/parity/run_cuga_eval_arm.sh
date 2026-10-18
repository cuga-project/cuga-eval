#!/usr/bin/env bash
# One parity arm on THIS stack (cuga main + cuga-eval adapter), domain by domain, resumable.
# usage: run_cuga_eval_arm.sh <run_id> <subset> <preset: off|cap1|cap2|cap3> [extra eval.sh args...]
# Requires: source benchmarks/m3/parity/env.sh (and a PASSing preflight).
# PARITY_FC=1 adds native function calling (arm suffix _fc); PARITY_VARIANT=<name> applies
# variants/<name>.env on top of the preset (arm suffix @<name>).
# For every domain of the subset: eval.sh over the subset's eval-key restricted to that
# domain, policies OFF (the campaign ran DYNACONF_POLICY__ENABLED=false), then a snapshot
# into parity/runs/<run_id>/cuga_eval_<preset>/. A domain whose prediction file already
# exists is skipped, so re-running the same run_id resumes after an interruption; an
# environment failure (eval.sh exit 3: containers/daemon down) stops the arm immediately.
set -uo pipefail
PARITY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$PARITY_DIR/../../.." && pwd)"
RUN_ID="${1:?run_id}"; SUBSET="${2:?subset}"; PRESET="${3:?preset}"; shift 3
[ -n "${AGENT_SETTING_CONFIG:-}" ] && [ -n "${PARITY_B1:-}" ] || { echo "source benchmarks/m3/parity/env.sh first" >&2; exit 2; }
MAN="$PARITY_DIR/manifests/$SUBSET.json"; [ -f "$MAN" ] || { echo "no manifest $MAN" >&2; exit 2; }
TASK_ID=$(python3 -c "import json;print(json.load(open('$MAN'))['task_id'])")
DOMS=$(python3 -c "import json;print(' '.join(json.load(open('$MAN'))['ids_by_domain']))")
CONTAINER=$(python3 -c "import json;print(json.load(open('$MAN'))['capability_dir'])")
FC="${PARITY_FC:-0}"
VARIANT="${PARITY_VARIANT:-}"
ARM="cuga_eval_${PRESET}"; [ "$FC" = "1" ] && ARM="${ARM}_fc"
VFILES=()
if [ -n "$VARIANT" ]; then
    for _p in ${VARIANT//+/ }; do   # stacked variants apply left to right
        VFILE="$PARITY_DIR/variants/$_p.env"; [ -f "$VFILE" ] || { echo "no variant $VFILE" >&2; exit 2; }
        set -a; source "$VFILE"; set +a   # M3_ADAPTER_* overrides of the preset
        VFILES+=("$VFILE")
    done
    ARM="${ARM}@${VARIANT}"
fi
OUT="$PARITY_DIR/runs/$RUN_ID/$ARM"; mkdir -p "$OUT/prediction"
ARM_START=$(date +%s); FINAL_RC=0

# Execution mode. The settings key reaches every agent (also the plain `off` one); the
# adapter's execution_mode sets the per-invoke keys for presets. Non-FC arms must UNSET the
# settings key: cuga resolves configurable > model profile > settings, and a CodeAct preset
# sets nothing per invoke.
if [ "$FC" = "1" ]; then
    export DYNACONF_ADVANCED_FEATURES__CUGA_LITE_EXECUTION_MODE=function_calling
    export M3_ADAPTER_EXECUTION_MODE=function_calling
else
    unset DYNACONF_ADVANCED_FEATURES__CUGA_LITE_EXECUTION_MODE
    export M3_ADAPTER_EXECUTION_MODE=codeact
fi

# Data + demo source from the manifest: default the bundled small_train.zip; "local:<name>" means
# parity/.local/<name> (vakra-main train data converted by prepare_vakra_train.py; gitignored).
read -r M3DATA DEMODATA NOGT <<<"$(python3 - "$MAN" "$PARITY_DIR" "$ROOT" <<'PY'
import json, sys
m, parity, root = json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3]
res = lambda v: f"{parity}/.local/{v[6:]}" if v.startswith("local:") else v
print(res(m.get("m3_data") or f"{root}/benchmarks/m3/data/small_train.zip"), res(m.get("demo_data") or "-"), "1" if m.get("no_ground_truth") else "0")
PY
)"
[ -e "$M3DATA" ] || { echo "data source $M3DATA missing — run: uv run --frozen python -m benchmarks.m3.parity.prepare_vakra_train --manifest $MAN --vakra-main \$VAKRA_MAIN --out <dir>" >&2; exit 2; }
BASE_ARGS=(--m3-data "$M3DATA" --capability "m3_task_$TASK_ID" --eval-key "$SUBSET" --no-policies --no-bundle)
# predictions only: eval_m3's ground-truth mode only runs the registry YAML's small_train domains
[ "$NOGT" = "1" ] && BASE_ARGS+=(--no-ground-truth)
[ "$PRESET" != "off" ] && BASE_ARGS+=(--adapter-preset "$PRESET")
[ "$PRESET" != "off" ] && [ "$DEMODATA" != "-" ] && BASE_ARGS+=(--demo-data "$DEMODATA")
echo "bash benchmarks/m3/eval.sh ${BASE_ARGS[*]} --domain <domain> $*" > "$OUT/command.txt"
for VFILE in ${VFILES[@]+"${VFILES[@]}"}; do grep -E '^M3_ADAPTER_' "$VFILE" | sed "s|^|variant $(basename "$VFILE" .env): |" >> "$OUT/command.txt"; done
echo "[$ARM] start $(date '+%F %T')  temperature=$PARITY_TEMPERATURE model=$PARITY_MODEL fc=$FC domains: $DOMS" | tee -a "$OUT/console.log"

# Campaign hygiene (cap_estimate.sh did both before every 8-item batch): a fresh task container
# and a live proxy. Transient proxy blips are waited out; a proxy still down after ~10 min stops
# the arm (resumable) instead of failing every remaining task.
restart_ctr() { docker restart "$1" >/dev/null 2>&1; for _ in $(seq 1 20); do docker logs --tail 3 "$1" 2>&1 | grep -q "ready for exec" && break; sleep 3; done; sleep 2; }
proxy_up() {
    local code try
    for try in $(seq 1 10); do
        code=$(curl -s -m 25 -o /dev/null -w "%{http_code}" "$PARITY_B1/v1/chat/completions" \
            -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
            -d "{\"model\":\"$PARITY_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_completion_tokens\":8,\"reasoning_effort\":\"low\"}")
        case "$code" in 200|429) return 0;; esac
        echo "[$ARM] proxy probe HTTP $code (try $try/10) — waiting 60s" | tee -a "$OUT/console.log"; sleep 60
    done
    return 1
}

# cap1 has its own harness (eval_m3_task_1_enterprise_style.py: direct MCP to the container and a
# universe switch per item, no registry): run it on the manifest's items for the domain with the
# campaign's main-pass universe-switch timeout (150 s); its submission file is the prediction file.
CAP1_INPUT="$VAKRA_MAIN/$(python3 -c "import json;print(json.load(open('$MAN')).get('vakra_train_data','data/train/capability_1_bi_apis'))")/input"
run_cap1_domain() {
    local dom="$1" raw="$OUT/raw/$1" ids latest rc
    ids=$(python3 -c "import json,sys;print(','.join(json.load(open(sys.argv[1]))['ids_by_domain'][sys.argv[2]]))" "$MAN" "$dom")
    mkdir -p "$raw"
    local args=(--container "$CONTAINER" --domain "$dom" --item-ids "$ids" --switch-timeout 150 --output "$raw")
    # The runner's own per-item limit (default 300s) must outlast the adapter's agent_timeout,
    # or a variant that raises the agent limit (variants/t400.env) is cut off by the runner.
    [ -n "${M3_ADAPTER_AGENT_TIMEOUT:-}" ] && args+=(--agent-timeout "$((M3_ADAPTER_AGENT_TIMEOUT + 60))")
    [ "$PRESET" != "off" ] && args+=(--adapter-preset "$PRESET")
    [ "$PRESET" != "off" ] && [ "$DEMODATA" != "-" ] && args+=(--demo-data "$DEMODATA")
    # LOGURU_LEVEL=INFO: load_env.sh defaults it to WARNING, which hid the adapter's decisions (gate
    # retries, checks) from cap1 console logs; the caps 2-4 runners log at INFO already.
    (cd "$ROOT" && LOGURU_LEVEL=INFO M3_DATA_DIR="$CAP1_INPUT" uv run --frozen python benchmarks/m3/eval_m3_task_1_enterprise_style.py "${args[@]}") 2>&1 | tee -a "$OUT/console.log"
    rc=${PIPESTATUS[0]}
    latest=$(ls -td "$raw"/*/task_1 2>/dev/null | head -1)
    if [ -n "$latest" ] && [ -f "$latest/$dom.json" ]; then cp "$latest/$dom.json" "$OUT/prediction/$dom.json"; fi
    return "$rc"
}

# cap4 runs eval_m3 directly (eval.sh --multiturn is broken) through eval_m3_cap4.py, the
# campaign's protocol: one agent call per item with the earlier turns' gold answers as history.
# m3.env is loaded the way eval.sh loads it (never overriding what is already exported), with the
# kit's own registry port and CUGA's policy system off.
run_cap4_domain() {
    local dom="$1" rc
    local args=(--from-config "$PARITY_DIR/m3_registry_cap4.yaml" --m3-data "$M3DATA" --capability m3_task_4
        --eval-key "$SUBSET" --no-ground-truth --no-policies --domain "$dom")
    [ "$PRESET" != "off" ] && args+=(--adapter-preset "$PRESET")
    [ "$PRESET" != "off" ] && [ "$DEMODATA" != "-" ] && args+=(--demo-data "$DEMODATA")
    # load_env.sh reads unset variables (eval.sh runs without set -u): relax -u in this subshell only
    (cd "$ROOT" && set +u && export DYNACONF_SERVER_PORTS__REGISTRY="$REGISTRY_PORT" DYNACONF_POLICY__ENABLED=false \
        && source benchmarks/helpers/load_env.sh m3 >/dev/null \
        && uv run --frozen python -m benchmarks.m3.parity.eval_m3_cap4 "${args[@]}") 2>&1 | tee -a "$OUT/console.log"
    rc=${PIPESTATUS[0]}
    return "$rc"
}

# The CUGA this arm runs; checked again before every domain. A change (branch switch, new
# commit, edits) stops the arm — the 2026-10-13 stage-2 run lost half an arm to one.
cuga_id() { (cd "$ROOT" && uv run --frozen python -m benchmarks.m3.parity.cuga_identity --line 2>/dev/null); }
CUGA_ID0="$(cuga_id)"
echo "[$ARM] cuga: $CUGA_ID0" | tee -a "$OUT/console.log"

for dom in $DOMS; do
    if [ -f "$OUT/prediction/$dom.json" ]; then
        echo "[$ARM] $dom already done (resume)" | tee -a "$OUT/console.log"; continue
    fi
    if [ "$(cuga_id)" != "$CUGA_ID0" ]; then
        echo "[$ARM] CUGA changed since the arm started ($CUGA_ID0 -> $(cuga_id)) — stopping this arm" | tee -a "$OUT/console.log"
        FINAL_RC=3; break
    fi
    if ! proxy_up; then
        echo "[$ARM] proxy still down before $dom — stopping this arm; re-run the same run_id to resume" | tee -a "$OUT/console.log"
        FINAL_RC=3; break
    fi
    restart_ctr "$CONTAINER"
    if lsof -nP -iTCP:"${REGISTRY_PORT:-8001}" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "[$ARM] registry port ${REGISTRY_PORT:-8001} still busy before $dom — waiting 30s" | tee -a "$OUT/console.log"; sleep 30
    fi
    DOM_START=$(date +%s)
    echo "[$ARM] $dom start $(date '+%T')" | tee -a "$OUT/console.log"
    if [ "$TASK_ID" = "1" ]; then
        run_cap1_domain "$dom"; RC=$?
    else
        if [ "$TASK_ID" = "4" ]; then
            run_cap4_domain "$dom"; RC=$?
        else
            (cd "$ROOT" && bash benchmarks/m3/eval.sh "${BASE_ARGS[@]}" --domain "$dom" "$@") 2>&1 | tee -a "$OUT/console.log"
            RC=${PIPESTATUS[0]}
        fi
        (cd "$ROOT" && uv run --frozen python -m benchmarks.m3.parity.snapshot snapshot-cuga-eval \
            --manifest "$MAN" --results-dir "$ROOT/benchmarks/m3/results" --since "$DOM_START" --out "$OUT" --domains "$dom") | tee -a "$OUT/snapshot.jsonl"
    fi
    echo "[$ARM] $dom done rc=$RC in $(( $(date +%s) - DOM_START ))s" | tee -a "$OUT/console.log"
    if [ "$RC" = "3" ]; then
        echo "[$ARM] environment failure at $dom (containers/daemon) — stopping this arm; re-run the same run_id to resume" | tee -a "$OUT/console.log"
        FINAL_RC=3; break
    fi
    [ "$RC" != "0" ] && FINAL_RC=$RC
done
ARM_END=$(date +%s)

_git() { git -C "$1" rev-parse --abbrev-ref HEAD 2>/dev/null; git -C "$1" rev-parse --short HEAD 2>/dev/null; git -C "$1" status --porcelain 2>/dev/null | wc -l | tr -d ' '; }
read -r AB AC AD <<<"$(_git "$ROOT" | tr '\n' ' ')"
read -r CB CC CD <<<"$(_git "${CUGA_AGENT_DIR:-$ROOT/../cuga-agent}" | tr '\n' ' ')"
DONE_DOMS=$(ls "$OUT/prediction" 2>/dev/null | sed 's/.json$//' | tr '\n' ' ')
python3 - "$OUT" <<PY
import json, sys
json.dump({
    "arm": "$ARM", "stack": "cuga-eval", "subset": "$SUBSET", "task_id": $TASK_ID, "adapter_preset": "$PRESET",
    "variant": "$VARIANT",
    "execution_mode": "${M3_ADAPTER_EXECUTION_MODE:-n/a}", "fc": "$FC", "policies": "off", "temperature": "$PARITY_TEMPERATURE",
    "model": "$PARITY_MODEL", "models_toml": "$AGENT_SETTING_CONFIG",
    "cuga_eval": {"branch": "$AB", "commit": "$AC", "dirty_files": "$AD"},
    "cuga_agent": {"branch": "$CB", "commit": "$CC", "dirty_files": "$CD"},
    "domains_done": "$DONE_DOMS".split(), "started": $ARM_START, "finished": $ARM_END, "eval_exit_code": $FINAL_RC,
}, open(sys.argv[1] + "/meta.json", "w"), indent=1)
PY
echo "[$ARM] done rc=$FINAL_RC in $((ARM_END-ARM_START))s (domains done: $DONE_DOMS) -> $OUT" | tee -a "$OUT/console.log"
exit $FINAL_RC
