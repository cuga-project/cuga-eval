#!/usr/bin/env bash
# Parity preflight: everything both stacks need, checked before any LLM call.
# usage: source benchmarks/m3/parity/env.sh && bash benchmarks/m3/parity/preflight.sh [task_id ...]
# Exit 1 on any blocker. Never prints credentials or proxy hostnames.
set -uo pipefail
TASKS=("${@:-2 3}")
[ -n "${PARITY_B1:-}" ] || { echo "FAIL  source benchmarks/m3/parity/env.sh first"; exit 1; }
ROOT="$PARITY_ROOT"; FAIL=0
ok()   { echo "ok    $*"; }
bad()  { echo "FAIL  $*"; FAIL=1; }
info() { echo "info  $*"; }

# --- containers (shared by both stacks) --------------------------------------
if docker ps >/dev/null 2>&1; then
    ok "docker daemon reachable"
    for t in "${TASKS[@]}"; do
        case "$t" in 1) c=capability_1_bi_apis;; 2) c=capability_2_dashboard_apis;; 3) c=capability_3_multihop_reasoning;; 4) c=capability_4_multiturn;; *) c="";; esac
        [ -z "$c" ] && continue
        if docker ps --format '{{.Names}}' | grep -qx "$c"; then ok "container $c running"; else bad "container $c not running (cd $VAKRA_MAIN && docker compose up -d)"; fi
    done
else
    bad "docker daemon not reachable — start Docker (Desktop/colima) before any run"
fi

# --- this stack --------------------------------------------------------------
[ -L "$ROOT/vendor/vakra" ] || [ -d "$ROOT/vendor/vakra" ] && ok "vendor/vakra -> $(readlink "$ROOT/vendor/vakra" 2>/dev/null || echo dir)" || bad "vendor/vakra missing (ln -sfn $VAKRA_MAIN vendor/vakra)"
[ -f "$ROOT/benchmarks/m3/data/small_train.zip" ] && ok "small_train.zip present" || bad "benchmarks/m3/data/small_train.zip missing"
if [ -d "$CUGA_AGENT_DIR/.git" ]; then
    _b=$(git -C "$CUGA_AGENT_DIR" rev-parse --abbrev-ref HEAD); _c=$(git -C "$CUGA_AGENT_DIR" rev-parse --short HEAD); _d=$(git -C "$CUGA_AGENT_DIR" status --porcelain | wc -l | tr -d ' ')
    info "cuga-agent (this stack): $_b@$_c dirty_files=$_d"
    [ "$_d" = "0" ] || info "  ^ dirty checkout: the parity report will carry this; prefer a clean origin/main (or the merged FC commit)"
else
    bad "cuga-agent checkout not found at $CUGA_AGENT_DIR"
fi
_fc=$(cd "$ROOT" && uv run --frozen python - <<'PY' 2>/dev/null
import importlib
try:
    m = importlib.import_module("cuga.backend.cuga_graph.nodes.cuga_lite.model_runtime_profile")
    print("available" if hasattr(m, "resolve_execution_mode") else "absent")
except Exception:
    print("absent")
PY
)
info "native function calling in this cuga checkout: ${_fc:-unknown} (PARITY_FC=1 needs 'available')"
[ "${PARITY_FC:-0}" = "1" ] && [ "$_fc" != "available" ] && bad "PARITY_FC=1 but this cuga checkout has no native FC (cuga-agent#777 not merged/checked out)"
[ -f "$AGENT_SETTING_CONFIG" ] && ok "AGENT_SETTING_CONFIG=$AGENT_SETTING_CONFIG ($(grep -c '^temperature' "$AGENT_SETTING_CONFIG") model blocks at temperature $PARITY_TEMPERATURE)" || bad "AGENT_SETTING_CONFIG file missing"
if lsof -nP -iTCP:"${REGISTRY_PORT:-8001}" -sTCP:LISTEN >/dev/null 2>&1; then bad "port ${REGISTRY_PORT:-8001} busy (stale registry?) — eval.sh needs it"; else ok "registry port ${REGISTRY_PORT:-8001} free"; fi

# --- the other stack -----------------------------------------------------------
[ -d "$VAKRA_MAIN" ] && ok "vakra-main at $VAKRA_MAIN" || bad "vakra-main not found at $VAKRA_MAIN"
[ -x "$VAKRA_MAIN/.venv-cuga/bin/python" ] && ok "vakra-main .venv-cuga (runner)" || bad "vakra-main/.venv-cuga missing"
[ -x "$VAKRA_MAIN/.venv/bin/python" ] && ok "vakra-main .venv (evaluator)" || bad "vakra-main/.venv missing"
for t in "${TASKS[@]}"; do
    case "$t" in 1) d=capability_1_bi_apis;; 2) d=capability_2_dashboard_apis;; 3) d=capability_3_multihop_reasoning;; *) d="";; esac
    [ -z "$d" ] && continue
    [ -d "$VAKRA_MAIN/data/train/$d/input" ] && [ -d "$VAKRA_MAIN/data/train/$d/output" ] && ok "vakra-main data/train/$d" || bad "vakra-main data/train/$d incomplete"
done
_oc="$VAKRA_MAIN/.venv-cuga/bin/python"
_ocuga=$($_oc -c "import cuga, os; print(os.path.dirname(os.path.dirname(cuga.__file__)))" 2>/dev/null)
if [ -n "$_ocuga" ] && git -C "$_ocuga/.." rev-parse --git-dir >/dev/null 2>&1; then
    _r="$(cd "$_ocuga/.." && pwd)"; info "cuga (other stack): $(git -C "$_r" rev-parse --abbrev-ref HEAD)@$(git -C "$_r" rev-parse --short HEAD) dirty_files=$(git -C "$_r" status --porcelain | wc -l | tr -d ' ') at $_r"
else
    info "cuga (other stack): could not resolve checkout (${_ocuga:-import failed})"
fi

# --- proxy (agent + judge) ---------------------------------------------------------
_code=$(curl -s -m 25 -o /dev/null -w "%{http_code}" "$PARITY_B1/v1/chat/completions" \
    -H "Authorization: Bearer $OPENAI_API_KEY" -H "Content-Type: application/json" \
    -d "{\"model\":\"$PARITY_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_completion_tokens\":8,\"reasoning_effort\":\"low\"}")
case "$_code" in
    200|429) ok "proxy probe for $PARITY_MODEL: HTTP $_code";;
    *) bad "proxy probe returned HTTP ${_code:-000} — STOP: VPN/proxy is down; do not try to fix it here";;
esac

echo "----"
if [ "$FAIL" = "0" ]; then echo "PREFLIGHT PASS"; else echo "PREFLIGHT FAIL (see FAIL lines)"; fi
exit $FAIL
