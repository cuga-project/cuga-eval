#!/usr/bin/env bash
# One parity arm inside a cluster job (LSF or any batch node with rootless podman), then its scoring.
# usage (as the job's command): bash benchmarks/m3/parity/lsf_arm.sh <run_id> <subset> <preset> [--fc 0|1]
#          [--variant NAME] [--no-score]
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
FC=0; VARIANT=""; SCORE=1
while [ $# -gt 0 ]; do
    case "$1" in
        --fc) FC="$2"; shift 2;;
        --variant) VARIANT="$2"; shift 2;;
        --no-score) SCORE=0; shift;;
        *) echo "unknown flag $1" >&2; exit 2;;
    esac
done
: "${VAKRA_SHARED:?set VAKRA_SHARED}" "${VAKRA_IMAGE_TAR:?set VAKRA_IMAGE_TAR}"
MAN="$PARITY_DIR/manifests/$SUBSET.json"; [ -f "$MAN" ] || { echo "no manifest $MAN" >&2; exit 2; }
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
exit "$rc"
