#!/usr/bin/env bash
# benchmarks/m3/clean.sh
#
# Reset the M3 environment to a clean slate before a fresh eval / compare run.
# - Kills any running compare.sh / eval.sh / eval_m3 / registry / docker-exec
#   processes (those that survive past prior runs and corrupt subsequent ones).
# - Frees port 8001 (the registry port).
# - Restarts the four capability_* Docker containers (their internal uvicorn
#   on :8000 has been observed to die silently after long runs; a fresh
#   restart guarantees /openapi.json is reachable inside each container).
# - Removes m3 result JSONs and the _vakra/ intermediate directory from
#   benchmarks/m3/results/. Leaves evaluation_bundles/ alone.
#
# Use:  bash benchmarks/m3/clean.sh           (interactive confirm)
#       bash benchmarks/m3/clean.sh --yes     (no prompt — for scripts)

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
M3_DIR="$PROJECT_ROOT/benchmarks/m3"
RESULTS_DIR="$M3_DIR/results"

CAPABILITY_CONTAINERS=(
    capability_1_bi_apis
    capability_2_dashboard_apis
    capability_3_multihop_reasoning
    capability_4_multiturn
)

# ---- colors ---------------------------------------------------------------
if [[ -t 1 ]]; then
    GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
    BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
else
    GREEN=''; YELLOW=''; RED=''; BLUE=''; CYAN=''; NC=''
fi
say() { printf "${CYAN}%s${NC}\n" "$*"; }
ok()  { printf "${GREEN}✓${NC} %s\n" "$*"; }
warn(){ printf "${YELLOW}⚠${NC} %s\n" "$*"; }
err() { printf "${RED}✗${NC} %s\n" "$*" >&2; }

YES=false
if [[ "${1:-}" == "-y" || "${1:-}" == "--yes" ]]; then
    YES=true
fi

# ---- 0. show what's about to happen, optionally confirm -------------------
echo
printf "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}\n"
printf "${BLUE}║  M3 environment reset                                      ║${NC}\n"
printf "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}\n"
echo
echo "Will:"
echo "  1) kill running compare.sh / eval.sh / eval_m3 / registry processes"
echo "  2) free port 8001"
echo "  3) restart capability containers: ${CAPABILITY_CONTAINERS[*]}"
echo "  4) wipe $RESULTS_DIR/m3_*.json, m3_config_*.json, multiturn_*.json, _vakra/"
echo
echo "Will NOT touch:"
echo "  - $M3_DIR/evaluation_bundles/   (historical bundles preserved)"
echo "  - any code, config, or .env files"
echo
if [[ "$YES" != "true" ]]; then
    read -r -p "Proceed? [y/N] " ans
    case "$ans" in
        y|Y|yes|YES) ;;
        *) echo "Aborted."; exit 0 ;;
    esac
fi

# ---- 1. kill processes ----------------------------------------------------
say "1) killing m3 eval / compare / registry processes"

# Order: outermost wrappers first, then python drivers, then registry, then strays.
PATTERNS=(
    'caffeinate.*benchmarks/m3/(eval|compare)\.sh'
    'bash benchmarks/m3/(eval|compare)\.sh'
    'benchmarks\.m3\.eval_m3'
    'benchmarks\.m3\.eval_m3_react'
    'benchmarks\.m3\.eval_m3_multiturn'
    'uv run.*registry'
    'uvicorn.*api_registry_server'
    'docker exec.*mcp_dispatch'
)

killed=0
for sig in TERM KILL; do
    for pat in "${PATTERNS[@]}"; do
        # macOS pkill -f matches against the command line.
        if pkill -"$sig" -f "$pat" 2>/dev/null; then
            killed=1
        fi
    done
    sleep 1
done
if [[ $killed -eq 1 ]]; then
    ok "process cleanup signals sent"
else
    ok "no matching processes were running"
fi

# Verify nothing's left
remaining=$(ps -ef | grep -iE 'compare\.sh|eval_m3|caffeinate.*compare|caffeinate.*eval\.sh|api_registry_server|mcp_dispatch' | grep -v grep | wc -l | tr -d ' ')
if [[ "$remaining" != "0" ]]; then
    warn "$remaining process(es) still running after kill — listing:"
    ps -ef | grep -iE 'compare\.sh|eval_m3|caffeinate.*compare|caffeinate.*eval\.sh|api_registry_server|mcp_dispatch' | grep -v grep
fi

# ---- 2. free port 8001 ----------------------------------------------------
say "2) freeing port 8001"
PIDS=$(lsof -ti :8001 2>/dev/null || true)
if [[ -n "$PIDS" ]]; then
    # shellcheck disable=SC2086
    kill -9 $PIDS 2>/dev/null || true
    sleep 1
fi
if lsof -ti :8001 >/dev/null 2>&1; then
    err "port 8001 still in use:"
    lsof -i :8001
else
    ok "port 8001 free"
fi

# ---- 3. restart capability containers -------------------------------------
say "3) restarting capability containers (each ~5s)"
for c in "${CAPABILITY_CONTAINERS[@]}"; do
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${c}$"; then
        if docker restart "$c" >/dev/null 2>&1; then
            printf "    ${GREEN}restarted${NC} %s\n" "$c"
        else
            err "failed to restart $c"
        fi
    elif docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${c}$"; then
        warn "$c exists but is not running — starting it"
        docker start "$c" >/dev/null 2>&1 || err "failed to start $c"
    else
        warn "$c not found (skipping)"
    fi
done

# Wait for internal uvicorn to come back up; poll /openapi.json over docker exec.
say "   waiting for internal /openapi.json to respond inside each container"
for c in "${CAPABILITY_CONTAINERS[@]}"; do
    if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${c}$"; then
        continue
    fi
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
        http=$(docker exec "$c" curl -s -o /dev/null -w "%{http_code}" \
              http://localhost:8000/openapi.json --max-time 3 2>/dev/null || echo "EXEC_FAIL")
        if [[ "$http" == "200" ]]; then
            ok "$c → http=200 (after ${attempt}s)"
            break
        fi
        if [[ "$attempt" == "10" ]]; then
            warn "$c → http=$http after 10s (may need more time)"
        fi
        sleep 1
    done
done

# ---- 4. clean results -----------------------------------------------------
say "4) cleaning $RESULTS_DIR"
mkdir -p "$RESULTS_DIR"
removed=0
for pattern in 'm3_*.json' 'm3_config_*.json' 'multiturn_*.json'; do
    for f in "$RESULTS_DIR"/$pattern; do
        [[ -e "$f" ]] || continue
        rm -f "$f" && removed=$((removed + 1))
    done
done
if [[ -d "$RESULTS_DIR/_vakra" ]]; then
    rm -rf "$RESULTS_DIR/_vakra"
    printf "    ${GREEN}removed${NC} _vakra/\n"
fi
if [[ $removed -gt 0 ]]; then
    ok "removed $removed result file(s)"
else
    ok "no result files to remove"
fi

# ---- summary --------------------------------------------------------------
echo
ok "M3 environment reset complete. Ready for a fresh run."
echo
