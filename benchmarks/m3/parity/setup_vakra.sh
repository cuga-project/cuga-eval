#!/usr/bin/env bash
# Build the VAKRA side of the kit from public, pinned sources: IBM/vakra code, ibm-research/VAKRA data, the
# evaluator venv and the tool-container image. With the default pins the result equals the vakra-main copy the
# reported runs used (checked file by file on 2026-10-22); point the kit at it with: export VAKRA_MAIN=<dir>.
# usage: bash benchmarks/m3/parity/setup_vakra.sh [--dir DIR] [--steps LIST] [--force-link]
#   --dir    target folder (default ../vakra next to cuga-eval). The data needs ~37 GB: keep it off backed-up homes.
#   --steps  comma list, run in this order (default code,evaluator,data,universes,image; link is opt-in):
#     code       clone IBM/vakra at VAKRA_REF, take evaluator/ from VAKRA_EVALUATOR_REF, apply vakra/patches/
#                (resets the tool-universe mapping to upstream: run universes after it)
#     evaluator  <dir>/.venv: Python 3.11.13 with vakra/evaluator.requirements.txt
#     data       databases/, indexed_documents/ and train/ of the dataset at VAKRA_DATA_REV, plus cap4_train/data
#     universes  add the cap1 TRAIN tool universes to the mapping (upstream ships the test ones only); generated
#                with upstream's own script from the train outputs, so test answers are never read
#     image      build benchmark_environ with the package versions of the image the runs used
#                (CONTAINER_CMD picks the runtime, e.g. "podman --storage-opt ignore_chown_errors=true";
#                VAKRA_IMAGE_PLATFORM=linux/amd64 cross-builds; VAKRA_IMAGE_TAR=<file.tar.gz> also saves it)
#     link       point cuga-eval's vendor/vakra at <dir> (an existing link elsewhere is kept unless --force-link)
# Every step writes <dir>/PINS.json, the provenance record of what was built.
set -euo pipefail
PARITY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$PARITY_DIR/../../.." && pwd)"
PINS="$PARITY_DIR/vakra"

VAKRA_REPO="${VAKRA_REPO:-https://github.com/IBM/vakra.git}"
# tool servers, docker/ and benchmark/: identical to the runs' copy
VAKRA_REF="${VAKRA_REF:-00dc68febdc28f5c3498ac00e2cd7d7b89dee315}"
# the evaluator the runs scored with (upstream changed scoring on 2026-07-21/22, after it)
VAKRA_EVALUATOR_REF="${VAKRA_EVALUATOR_REF:-99847464a7b0fca05413b53ad8a7714d9a9279e9}"
VAKRA_DATA_REPO="${VAKRA_DATA_REPO:-ibm-research/VAKRA}"
VAKRA_DATA_REV="${VAKRA_DATA_REV:-1388b9f1aaed887a73957eba651a6c2034010476}"
VAKRA_BASE_IMAGE="${VAKRA_BASE_IMAGE:-docker.io/library/python:3.11.15-slim}"
VAKRA_IMAGE="${VAKRA_IMAGE:-benchmark_environ}"
EVAL_PYTHON="3.11.13"
MAPPING=environment/configs/mcp_tool_universe_id_mapping.yaml
MAPPING_SHA256=101297c41fb81ebad774aefff7f87fd1de9ff973d8390d91e238bf6bb6d11909   # the runs' mapping
EMBEDDING_REV=47ea694b257b703fee9253d75c2b1f2985180498   # ibm-granite/granite-embedding-english-r2 in the image

DIR="$ROOT/../vakra"; STEPS="code,evaluator,data,universes,image"; FORCE_LINK=0
while [ $# -gt 0 ]; do
    case "$1" in
        --dir) DIR="$2"; shift 2;;
        --steps) STEPS="$2"; shift 2;;
        --force-link) FORCE_LINK=1; shift;;
        -h|--help) sed -n '2,20p' "$0"; exit 0;;
        *) echo "unknown flag $1" >&2; exit 2;;
    esac
done
mkdir -p "$DIR"; DIR="$(cd "$DIR" && pwd)"
PY="$DIR/.venv/bin/python"
has() { case ",$STEPS," in *",$1,"*) return 0;; *) return 1;; esac; }
say() { echo "[setup_vakra] $*"; }
need_venv() { [ -x "$PY" ] || { echo "no evaluator venv at $DIR/.venv: run the evaluator step first" >&2; exit 1; }; }
sha256() { { command -v sha256sum >/dev/null && sha256sum "$1" || shasum -a 256 "$1"; } | cut -d' ' -f1; }

if has code; then
    if [ ! -d "$DIR/.git" ]; then
        [ -z "$(ls -A "$DIR")" ] || { echo "$DIR exists and is not a git checkout; refusing to clone into it" >&2; exit 1; }
        git clone -q "$VAKRA_REPO" "$DIR"
    fi
    # Only the files this script manages may differ from the pins; anything else is someone's work.
    other=$(git -C "$DIR" status --porcelain --untracked-files=no | awk '{print $2}' \
        | grep -vE "^(evaluator/|benchmark/mcp_client\.py$|${MAPPING//./\\.}$)" || true)
    [ -z "$other" ] || { echo "refusing: $DIR has local changes this script does not manage: $other" >&2; exit 1; }
    for ref in "$VAKRA_REF" "$VAKRA_EVALUATOR_REF"; do
        git -C "$DIR" cat-file -e "$ref^{commit}" 2>/dev/null || git -C "$DIR" fetch -q origin
    done
    git -C "$DIR" checkout -q -f --detach "$VAKRA_REF"
    git -C "$DIR" checkout -q "$VAKRA_EVALUATOR_REF" -- evaluator
    git -C "$DIR" apply "$PINS"/patches/*.patch
    say "code: IBM/vakra@${VAKRA_REF:0:7} with evaluator/ @${VAKRA_EVALUATOR_REF:0:7} + $(ls "$PINS"/patches | wc -l | tr -d ' ') patches"
fi

if has evaluator; then
    command -v uv >/dev/null || { echo "uv is not on PATH (CCC: export PATH=~/.local/bin:\$PATH)" >&2; exit 1; }
    if [ ! -x "$PY" ] || [ "$("$PY" -c 'import platform; print(platform.python_version())')" != "$EVAL_PYTHON" ]; then
        rm -rf "$DIR/.venv"
        uv venv -q --python "$EVAL_PYTHON" "$DIR/.venv"
    fi
    uv pip install -q --python "$PY" -r "$PINS/evaluator.requirements.txt"
    say "evaluator: $DIR/.venv (Python $EVAL_PYTHON, $(grep -c '==' "$PINS/evaluator.requirements.txt") pinned packages)"
fi

if has data; then
    need_venv
    if [ ! -d "$DIR/data/databases" ]; then
        free_gb=$(df -Pk "$DIR" | awk 'NR==2 {print int($4 / 1048576)}')
        [ "$free_gb" -ge 40 ] || { echo "only ${free_gb} GB free under $DIR; the data needs ~37 GB" >&2; exit 1; }
    fi
    "$PY" -I - "$VAKRA_DATA_REPO" "$VAKRA_DATA_REV" "$DIR/data" <<'PY'
import sys
from huggingface_hub import snapshot_download

repo, rev, out = sys.argv[1:4]
snapshot_download(repo_id=repo, repo_type="dataset", revision=rev, local_dir=out,
                  allow_patterns=["databases/*", "indexed_documents/*", "train/*"])
PY
    # The cap4 subsets name their train data cap4_train/data (the campaign's folder), the same files.
    mkdir -p "$DIR/cap4_train"
    ln -sfn ../data/train/capability_4_multiturn "$DIR/cap4_train/data"
    say "data: $VAKRA_DATA_REPO@${VAKRA_DATA_REV:0:7} -> $DIR/data ($(du -sh "$DIR/data" | cut -f1))"
fi

if has universes; then
    need_venv
    git -C "$DIR" checkout -q "$VAKRA_REF" -- "$MAPPING"
    "$PY" -I - "$DIR" "$MAPPING" <<'PY'
import importlib.util
import sys
import tempfile
from pathlib import Path

import yaml

vakra, mapping = Path(sys.argv[1]), Path(sys.argv[1]) / sys.argv[2]
script = vakra / "environment/configs/generate_task_1_tool_universe_mapping.py"
with tempfile.TemporaryDirectory() as tmp:
    # The generator writes next to itself (its repo root): run a copy whose data/ holds only train/.
    root = Path(tmp)
    (root / "environment/configs").mkdir(parents=True)
    (root / "environment/configs" / script.name).write_bytes(script.read_bytes())
    (root / "data").mkdir()
    (root / "data/train").symlink_to(vakra / "data/train")
    spec = importlib.util.spec_from_file_location("generate_mapping", root / "environment/configs" / script.name)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    gen.OUTPUT_DIRS_GLOB = "data/train/capability_1_bi_apis/output"
    gen.generate_mapping()
    train = yaml.safe_load((root / gen.MAPPING_FILE).read_text())
upstream = yaml.safe_load(mapping.read_text())
with open(mapping, "w") as f:
    yaml.dump({**train, **upstream}, f, default_flow_style=False, allow_unicode=True)
print(f"universes: {len(upstream)} upstream (test) + {len(train)} train entries")
PY
    got=$(sha256 "$DIR/$MAPPING")
    [ "$got" = "$MAPPING_SHA256" ] && say "universes: mapping identical to the runs' (sha256 ${got:0:12})" \
        || say "WARNING: mapping sha256 ${got:0:12} differs from the runs' ${MAPPING_SHA256:0:12} (other pins?)"
fi

if has image; then
    read -r -a RT <<<"${CONTAINER_CMD:-$(command -v docker || command -v podman)}"
    # Upstream's Dockerfile with the base image and every package version pinned; the apt line lets rootless
    # podman without subuid ranges build it (apt cannot switch to its _apt user there).
    cp "$PINS/benchmark_environ.constraints.txt" "$DIR/docker/pinned-constraints.txt"
    awk -v base="$VAKRA_BASE_IMAGE" '!done && /^FROM / {
            print "FROM " base
            print "COPY docker/pinned-constraints.txt /tmp/pinned-constraints.txt"
            print "ENV PIP_CONSTRAINT=/tmp/pinned-constraints.txt"
            print "RUN echo \"APT::Sandbox::User \\\"root\\\";\" > /etc/apt/apt.conf.d/00-no-sandbox-user"
            done = 1; next }
        { print }' "$DIR/docker/Dockerfile.unified" > "$DIR/docker/Dockerfile.pinned"
    "${RT[@]}" build ${VAKRA_IMAGE_PLATFORM:+--platform "$VAKRA_IMAGE_PLATFORM"} -f "$DIR/docker/Dockerfile.pinned" \
        -t "$VAKRA_IMAGE:latest" -t "$VAKRA_IMAGE:vakra-${VAKRA_REF:0:7}" "$DIR"
    "${RT[@]}" run --rm --entrypoint sh "$VAKRA_IMAGE:latest" -c \
        'pip freeze; echo "embedding=$(cat /root/.cache/huggingface/hub/models--ibm-granite--granite-embedding-english-r2/refs/main)"' \
        > "$DIR/docker/pinned-image.freeze.txt"
    missing=$(grep -E '==' "$PINS/benchmark_environ.constraints.txt" | grep -vxFf "$DIR/docker/pinned-image.freeze.txt" || true)
    [ -z "$missing" ] && say "image: all $(grep -c '==' "$PINS/benchmark_environ.constraints.txt") package versions match" \
        || say "WARNING: image packages differ from the runs' image: $(echo "$missing" | tr '\n' ' ')"
    grep -qx "embedding=$EMBEDDING_REV" "$DIR/docker/pinned-image.freeze.txt" \
        && say "image: embedding model ${EMBEDDING_REV:0:7} as in the runs' image" \
        || say "WARNING: embedding model revision differs from ${EMBEDDING_REV:0:7}"
    if [ -n "${VAKRA_IMAGE_TAR:-}" ]; then
        "${RT[@]}" save "$VAKRA_IMAGE:latest" | gzip > "$VAKRA_IMAGE_TAR"
        say "image: saved to $VAKRA_IMAGE_TAR ($(du -sh "$VAKRA_IMAGE_TAR" | cut -f1))"
    fi
fi

if has link; then
    LINK="$ROOT/vendor/vakra"
    if [ -e "$LINK" ] && [ "$(readlink "$LINK" 2>/dev/null)" != "$DIR" ] && [ "$FORCE_LINK" != "1" ]; then
        echo "vendor/vakra already points at $(readlink "$LINK" 2>/dev/null || echo 'a directory'); keeping it (--force-link moves it)" >&2
    else
        mkdir -p "$ROOT/vendor"; ln -sfn "$DIR" "$LINK"; say "link: vendor/vakra -> $DIR"
    fi
fi

python3 - "$DIR/PINS.json" <<PY
import json, sys, datetime
json.dump({"vakra_repo": "$VAKRA_REPO", "vakra_ref": "$VAKRA_REF", "vakra_evaluator_ref": "$VAKRA_EVALUATOR_REF",
           "patches": sorted("$(ls "$PINS/patches" | tr '\n' ' ')".split()),
           "data_repo": "$VAKRA_DATA_REPO", "data_rev": "$VAKRA_DATA_REV", "base_image": "$VAKRA_BASE_IMAGE",
           "mapping_sha256_expected": "$MAPPING_SHA256", "embedding_rev_expected": "$EMBEDDING_REV",
           "evaluator_python": "$EVAL_PYTHON", "steps_last_run": "$STEPS",
           "written": datetime.datetime.now().isoformat(timespec="seconds")}, open(sys.argv[1], "w"), indent=1)
PY
say "done ($STEPS); provenance in $DIR/PINS.json. Use it with: export VAKRA_MAIN=$DIR"
