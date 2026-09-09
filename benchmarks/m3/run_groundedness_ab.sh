#!/bin/bash
# A/B harness for Wave-1 Change #1 — the evidence-chain / groundedness rider.
#
# Runs the M3 compare.sh twice over the SAME slice with IDENTICAL code, toggling
# ONLY the eval-only system rider (eval_m3.py M3_GROUNDEDNESS_INSTRUCTIONS):
#
#   arm A  (baseline)  : M3_GROUNDEDNESS_PROMPT=off
#                        -> tool-output (crash-free) section only; no groundedness rider.
#   arm B  (with #1)   : M3_GROUNDEDNESS_PROMPT=on
#                        -> tool-output section + the evidence-chain groundedness rider.
#
# The tool-output section is constant in both arms, so the ONLY differentiator is
# Change #1. Each arm produces its own compare bundle; diff Pass@1 + groundedness
# between the two.
#
# Usage:
#   ./run_groundedness_ab.sh --eval-key wave1_c1_filtered --runs 3
#   ./run_groundedness_ab.sh --eval-key wave1_c1_4cases   --runs 5
#   ./run_groundedness_ab.sh --eval-key wave1_c1_n1       --runs 1   # 1-task smoke
#
# Any flags other than --eval-key/--runs pass through to compare.sh (and on to
# eval.sh): --capability, --domain, --models, etc.
# NOTE: --m3-data, --no-policies, and --dotenv are added automatically.
#       --dotenv makes the agent use the .env model config (aws/gpt-oss-120b via
#       the LiteLLM proxy) rather than the default Groq gpt-oss profile.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RUNS=1
EVAL_KEY=""
PASS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --eval-key) EVAL_KEY="$2"; shift 2 ;;
        --runs)     RUNS="$2";     shift 2 ;;
        *)          PASS+=("$1");  shift ;;
    esac
done

if [[ -z "$EVAL_KEY" ]]; then
    echo "Error: --eval-key is required (e.g. wave1_c1_filtered / wave1_c1_4cases)." >&2
    exit 2
fi

# Always run with --dotenv so the agent picks up the .env model config
# (aws/gpt-oss-120b via the LiteLLM proxy + settings.openai.toml) instead of the
# default Groq gpt-oss profile. Idempotent: skip if the caller already passed it.
DOTENV=(--dotenv)
for _a in "${PASS[@]}"; do
    [[ "$_a" == "--dotenv" ]] && DOTENV=() && break
done

COMMON=(--runs "$RUNS" --no-policies --m3-data --eval-key "$EVAL_KEY" "${DOTENV[@]}" "${PASS[@]}")

# Hold the rule-8 trim rider constant across both arms so the A/B isolates
# ONLY M3_GROUNDEDNESS_PROMPT. Honour an explicit caller override, otherwise
# pin to off — without this the arms would silently inherit any ambient
# M3_GROUNDEDNESS_TRIM and conflate two independent changes.
TRIM="${M3_GROUNDEDNESS_TRIM:-off}"

# Run-scoped temp dir shared with the compare.sh/eval.sh runs below (issue
# #115). The current-arm marker lives here so two concurrent A/B comparisons
# on one host don't clobber each other's breadcrumb.
M3_RUN_TMP_DIR="${M3_RUN_TMP_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/m3_ab_XXXXXX")}"
export M3_RUN_TMP_DIR
echo "Run-scoped temp dir (arm marker + logs): $M3_RUN_TMP_DIR"

run_arm() {
    local label="$1" ground="$2"
    echo ""
    echo "############################################################"
    echo "# ARM: ${label}"
    echo "#   M3_GROUNDEDNESS_PROMPT=${ground}"
    echo "#   M3_GROUNDEDNESS_TRIM=${TRIM}  (pinned across both arms)"
    echo "#   eval-key=${EVAL_KEY}  runs=${RUNS}  extra=${PASS[*]:-none}"
    echo "############################################################"
    echo "arm=${label} groundedness=${ground} trim=${TRIM} eval_key=${EVAL_KEY} ts=$(date -u +%FT%TZ)" \
        > "$M3_RUN_TMP_DIR/m3_groundedness_arm.txt"
    M3_GROUNDEDNESS_PROMPT="$ground" M3_GROUNDEDNESS_TRIM="$TRIM" \
        bash "$SCRIPT_DIR/compare.sh" "${COMMON[@]}"
}

run_arm "A_baseline" off
run_arm "B_with_change1" on

echo ""
echo "Both arms complete. Compare the two newest compare bundles under"
echo "  $(cd "$SCRIPT_DIR/../.." && pwd)/benchmarks/m3/evaluation_bundles/"
echo "Arm A = baseline (groundedness rider OFF); arm B = Change #1 ON."
