#!/usr/bin/env bash
# One parity arm inside a cluster job (LSF or any batch node with rootless podman), then its scoring.
# usage (as the job's command): bash benchmarks/m3/parity/lsf_arm.sh <run_id> <subset> <preset> [--fc 0|1]
#          [--variant NAME] [--shard I/N] [--no-score] [--recover]
# --shard I/N: run only the I-th of N domain groups (balanced by task count) into the same run folder, without
#   scoring; N such jobs then one job without --shard (all domains already done: it only scores) fill a run.
# --recover: after scoring, the kit's recovery pass for tasks that died on infrastructure, then a re-score.
# Needs: VAKRA_SHARED (a setup_vakra.sh folder with --steps code,evaluator,data --data train,universes on shared
# storage), VAKRA_IMAGE_TAR (setup_vakra.sh image step's VAKRA_IMAGE_TAR), and the usual PARITY_KEY / PARITY_VENV /
# PARITY_MODEL / PARITY_APPWORLD_ENV. PARITY_JUDGE_MODEL is the judge (default azure/gpt-oss-120b, set explicitly:
# a key slot may pin another model).
# On the node, under ${VAKRA_WORK_BASE:-/tmp}: podman storage (no subuid ranges needed: ignore_chown_errors; no
# login session needed: own XDG_RUNTIME_DIR, cgroupfs), the image, and a VAKRA folder that links the shared code
# and train data and holds only the subset's databases (and the retrieval index for cap4). The arm, its results
# (parity/runs/<run_id>) and the scoring are the kit's own scripts; everything on the node is removed at the end.
set -uo pipefail
PARITY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$PARITY_DIR/../../.." && pwd)"
RUN_ID="${1:?run_id}"; SUBSET="${2:?subset}"; PRESET="${3:?preset}"; shift 3
FC=0; VARIANT=""; SCORE=1; SHARD=""; RECOVER=0
while [ $# -gt 0 ]; do
    case "$1" in
        --fc) FC="$2"; shift 2;;
        --variant) VARIANT="$2"; shift 2;;
        --shard) SHARD="$2"; SCORE=0; shift 2;;
        --no-score) SCORE=0; shift;;
        --recover) RECOVER=1; shift;;
        *) echo "unknown flag $1" >&2; exit 2;;
    esac
done
: "${VAKRA_SHARED:?set VAKRA_SHARED}" "${VAKRA_IMAGE_TAR:?set VAKRA_IMAGE_TAR}"
MAN="$PARITY_DIR/manifests/$SUBSET.json"; [ -f "$MAN" ] || { echo "no manifest $MAN" >&2; exit 2; }
if [ -n "$SHARD" ]; then
    # A sub-subset of the I-th domain group, written the way recover.py writes recovery subsets: a manifest and
    # uuid map in manifests/ (zz_*) and the eval key in a TOML that M3_EVAL_CONFIG_EXTRA points eval_m3 at.
    SH="zz_shard_$(printf '%s' "$RUN_ID" | tr -c 'A-Za-z0-9' _)_${SHARD%/*}of${SHARD#*/}"
    python3 - "$PARITY_DIR" "$SUBSET" "${SHARD%/*}" "${SHARD#*/}" "$SH" <<'PY' || { echo "shard setup failed" >&2; exit 2; }
import json, os, sys

pdir, base, i, n, name = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
man = json.load(open(f"{pdir}/manifests/{base}.json"))
umap = json.load(open(f"{pdir}/manifests/uuid_map_{base}.json"))
loads, parts = [0] * n, [[] for _ in range(n)]
for dom, ids in sorted(man["ids_by_domain"].items(), key=lambda kv: (-len(kv[1]), kv[0])):
    j = min(range(n), key=lambda k: (loads[k], k))
    parts[j].append(dom)
    loads[j] += len(ids)
keep = {d: man["ids_by_domain"][d] for d in sorted(parts[i - 1])}
ids = {u.lower() for v in keep.values() for u in v}
json.dump(dict(man, subset=name, n=len(ids), ids_by_domain=keep), open(f"{pdir}/manifests/{name}.json", "w"), indent=1)
zmap = {k: v for k, v in umap.get("zip_to_vakra", {}).items() if k.lower() in ids}
json.dump(dict(umap, subset=name, zip_to_vakra=zmap), open(f"{pdir}/manifests/uuid_map_{name}.json", "w"), indent=1)
os.makedirs(f"{pdir}/.local/shards", exist_ok=True)
with open(f"{pdir}/.local/shards/{name}.toml", "w") as f:
    f.write(f"{name} = [\n" + "".join(f'  "{u}",\n' for v in keep.values() for u in v) + "]\n")
PY
    export M3_EVAL_CONFIG_EXTRA="$PARITY_DIR/.local/shards/$SH.toml" PARITY_WORKER="shard${SHARD%/*}"
    SUBSET="$SH"; MAN="$PARITY_DIR/manifests/$SUBSET.json"
fi
read -r TASK CTR DOMS <<<"$(python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print(m['task_id'], m['capability_dir'], '+'.join(sorted(m['ids_by_domain'])))" "$MAN")"
say() { echo "[lsf_arm] $(date '+%F %T') $*"; }

W="${VAKRA_WORK_BASE:-/tmp}/${USER}-vakra-${LSB_JOBID:-$$}"
mkdir -p "$W/xdg" "$W/cfg/containers" "$W/cache" "$W/storage" "$W/run"; chmod 700 "$W/xdg"
# podman keeps locks in XDG_CACHE_HOME too: a home on shared storage refused them (permission denied).
export XDG_RUNTIME_DIR="$W/xdg" XDG_CONFIG_HOME="$W/cfg" XDG_CACHE_HOME="$W/cache"
# Config files rather than flags, so the kit's plain `docker ...` / `podman ...` calls get them too.
printf '[engine]\ncgroup_manager = "cgroupfs"\nevents_logger = "file"\n' > "$W/cfg/containers/containers.conf"
printf '[storage]\ndriver = "overlay"\ngraphroot = "%s"\nrunroot = "%s"\n[storage.options]\nignore_chown_errors = "true"\n' \
    "$W/storage" "$W/run" > "$W/cfg/containers/storage.conf"
touch "$W/cfg/containers/nodocker"   # silence the podman-docker shim's notice where it honors the user file
# The registry starts each MCP server (`docker exec -i ...`) through the MCP SDK's stdio transport, which passes
# only HOME/PATH/USER-style variables: podman lost XDG_RUNTIME_DIR and failed on /run/user/<uid>. Wrappers first on
# PATH set the job's podman environment for every caller.
mkdir -p "$W/bin"
for name in docker podman; do
    printf '#!/bin/bash\nexport XDG_RUNTIME_DIR="%s" XDG_CONFIG_HOME="%s" XDG_CACHE_HOME="%s"\nexec %s "$@"\n' \
        "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$(command -v podman)" > "$W/bin/$name"
    chmod +x "$W/bin/$name"
done
export PATH="$W/bin:$PATH"
cleanup() {
    podman rm -f "$CTR" >/dev/null 2>&1
    # Last: any podman call after this would start a new pause process (that kept a job running for hours).
    kill "$(cat "$XDG_RUNTIME_DIR/libpod/tmp/pause.pid" 2>/dev/null)" 2>/dev/null
    rm -rf "$W" 2>/dev/null   # ignore_chown_errors: every file is the job user's
}
trap cleanup EXIT
# The first podman call starts the rootless pause process, which inherits that call's output: with the job's
# stdout it kept the job running after the script ended. Start it with no inherited output.
podman info >/dev/null 2>&1 </dev/null
say "node $(hostname -s): $SUBSET (task $TASK, ${DOMS//+/ }), preset $PRESET fc=$FC${VARIANT:+ variant $VARIANT}"

podman load -q -i "$VAKRA_IMAGE_TAR" >/dev/null || { echo "podman load failed" >&2; exit 3; }

# Local VAKRA folder: the shared code, venv and train data through links; databases (and the index) on local disk.
VM="$W/vakra"; mkdir -p "$VM/data/queries"
for e in "$VAKRA_SHARED"/* "$VAKRA_SHARED"/.venv; do
    case "$(basename "$e")" in data|PINS.json) continue;; esac
    ln -s "$e" "$VM/$(basename "$e")"
done
ln -s "$VAKRA_SHARED/data/train" "$VM/data/train"
PARTS="databases:$DOMS"; [ "$TASK" = "4" ] && PARTS="$PARTS,index"
bash "$PARITY_DIR/setup_vakra.sh" --dir "$VM" --steps data --data "$PARTS" | tail -1 || { echo "data download failed" >&2; exit 3; }

mounts=(-v "$VM/data/databases:/app/db:ro" -v "$VM/environment/configs:/app/environment/configs:ro")
[ "$TASK" = "4" ] && mounts+=(-v "$VM/data/indexed_documents:/app/retrievers/chroma_data" -v "$VM/data/queries:/app/retrievers/queries:ro")
podman run -d --name "$CTR" -e MCP_VERIFY_CHECKSUMS=1 "${mounts[@]}" benchmark_environ:latest >/dev/null || { echo "container start failed" >&2; exit 3; }
for _ in $(seq 1 60); do podman logs --tail 3 "$CTR" 2>&1 | grep -q "ready for exec" && break; sleep 3; done
say "container $CTR up"

export VAKRA_MAIN="$VM"
# Subsets on vakra-main data read a converted copy (as run_parity.sh prepares it); cheap and idempotent.
LOCAL_DATA=$(python3 -c "import json,sys;v=json.load(open(sys.argv[1])).get('m3_data','');print(v[6:] if v.startswith('local:') else '')" "$MAN")
if [ -n "$LOCAL_DATA" ]; then
    (cd "$ROOT" && UV_PROJECT_ENVIRONMENT="${PARITY_VENV:?}" uv run --frozen --no-sync python -m benchmarks.m3.parity.prepare_vakra_train \
        --manifest "$MAN" --vakra-main "$VM" --out "$PARITY_DIR/.local/$LOCAL_DATA") >/dev/null || { echo "prepare failed" >&2; exit 3; }
fi
(
    source "$PARITY_DIR/env.sh" "${PARITY_TEMPERATURE:-1.0}" || exit 1
    PARITY_FC="$FC" bash "$PARITY_DIR/preflight.sh" "$TASK" || exit 1
    PARITY_FC="$FC" PARITY_VARIANT="$VARIANT" bash "$PARITY_DIR/run_cuga_eval_arm.sh" "$RUN_ID" "$SUBSET" "$PRESET"
)
rc=$?; say "arm rc=$rc"
if [ "$SCORE" = "1" ]; then
    (
        export PARITY_MODEL="${PARITY_JUDGE_MODEL:-azure/gpt-oss-120b}"
        source "$PARITY_DIR/env.sh" "${PARITY_TEMPERATURE:-1.0}" >/dev/null || exit 1
        echo "JUDGE_MODEL=$JUDGE_MODEL"
        bash "$PARITY_DIR/rescore.sh" "$RUN_ID" "$SUBSET"
    )
    say "scoring rc=$?"
fi
if [ "$RECOVER" = "1" ]; then
    ARM="cuga_eval_$PRESET"; [ "$FC" = "1" ] && ARM="${ARM}_fc"; [ -n "$VARIANT" ] && ARM="$ARM@$VARIANT"
    A="$PARITY_DIR/runs/$RUN_ID/$ARM"
    cp "$A/vendor_results.json" "$A/vendor_results.pre_recover.json" 2>/dev/null
    (
        source "$PARITY_DIR/env.sh" "${PARITY_TEMPERATURE:-1.0}" >/dev/null || exit 1
        bash "$PARITY_DIR/recover_arm.sh" "$RUN_ID" "$ARM"
    ) > "$A/recover_pass.log" 2>&1
    if grep -q 'nothing to recover' "$A/recover_pass.log"; then
        say "recovery: nothing to recover"
    else
        # recover_arm.sh swapped in verdicts judged by the agent model: keep them aside and re-judge the whole run.
        [ -f "$A/vendor_results.recovered.json" ] && mv "$A/vendor_results.recovered.json" "$A/vendor_results.recovered_agentjudge.json"
        say "recovery: $(grep -E '"replaced"|"still_failed"' "$A/recover_pass.log" | tr -d ' \n')"
        (
            export PARITY_MODEL="${PARITY_JUDGE_MODEL:-azure/gpt-oss-120b}"
            source "$PARITY_DIR/env.sh" "${PARITY_TEMPERATURE:-1.0}" >/dev/null || exit 1
            bash "$PARITY_DIR/rescore.sh" "$RUN_ID" "$SUBSET"
        )
        say "re-scoring after recovery rc=$?"
    fi
fi
exit "$rc"
