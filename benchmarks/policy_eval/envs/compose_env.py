#!/usr/bin/env python3
"""Compose the CUGA env file of one benchmark run from layers (replaces the per-benchmark cuga*.env copies).

Layers, last wins (all in this folder):
  base.env                      settings shared by every run (the function-calling agent)
  model.<model>.env             MODEL_NAME and AGENT_SETTING_CONFIG        (gptoss, dsv4, gemini38)
  bench.<bench>.env             benchmark mode                              (automationbench, itsm, handbook)
  pair.<model>.<bench>.env      optional: a setting only that pair needs   (pair.gemini38.handbook.env)
  extra                         dict argument: KEY -> value; None removes the key

  from compose_env import compose
  env_file = compose("gptoss", "automationbench", {"DYNACONF_ADVANCED_FEATURES__CUGA_LITE_FC_DYNAMIC_TOOLS": "apps"})
  # the runner then sets ENV_FILE=<env_file> for the child process (cuga loads it with override=True)

The file is written to $TMPDIR/cuga_eval_envs/cuga.<model>.<bench>.<hash>.env. The name holds a hash of the content, so
equal settings give the same path and a running child never sees its file change.

Secrets are not allowed here: a key name with KEY, TOKEN, SECRET or PASSWORD in it is refused. API keys come from
cuga-eval/.env through the runner.

  python3 compose_env.py <model> <bench> [K=V ...]  print the path of the composed file
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|BEARER", re.I)
SECRET_VALUE = re.compile(
    r"sk-[A-Za-z0-9]{10,}|hf_[A-Za-z0-9]{10,}|AKIA[A-Z0-9]{8,}|eyJ[A-Za-z0-9_-]{10,}|Bearer\s|[A-Fa-f0-9]{32,}"
)
KEY_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
PART_NAME = re.compile(r"[a-z0-9]+")


# ── parsing ──────────────────────────────────────────────────────────────────


def parse_runner(text: str, source: str = "?") -> dict[str, str]:
    """Key/value pairs of an env file: a line counts when it has "=" and its first non-blank character is not "#"; the key
    and the value are stripped.
    A trailing "# ..." is part of the value. Two lines with the same key are an error here (the runner keeps the first,
    python-dotenv the last)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key in out:
                raise ValueError(f"{source}: key {key} appears twice")
            out[key] = value
    return out


def _check_pair(key: str, value: str, source: str) -> None:
    if not KEY_NAME.fullmatch(key):
        raise ValueError(f"{source}: bad key name {key!r}")
    if SECRET_NAME.search(key):
        raise ValueError(f"{source}: key {key} looks like a secret; secrets do not belong in these files")
    if "\n" in value or "\r" in value:
        raise ValueError(f"{source}: value of {key} has a line break")
    # The runner keeps " # ..." and a leading quote; python-dotenv drops/handles them. Refuse what the two read differently.
    if " #" in value or (value and value[0] in "\"'"):
        raise ValueError(
            f"{source}: value of {key} has a comment or leading quote; the runner and python-dotenv would read it differently"
        )
    if SECRET_VALUE.search(value):
        raise ValueError(f"{source}: value of {key} looks like a secret (value not shown)")


# ── compose ──────────────────────────────────────────────────────────────────

_P = "DYNACONF_ADVANCED_FEATURES__"
FC_DYNAMIC = {
    _P + "CUGA_LITE_FC_DYNAMIC_TOOLS": "apps"
}  # find_tools + every tool of each searched app (full toolset)
NO_FC = {
    _P + "CUGA_LITE_EXECUTION_MODE": None,
    _P + "CUGA_LITE_FC_PROMPT_FRAGMENTS": None,
}  # CodeAct, not function calling
TEXT_AGENT = {  # the oldest agent: verify gate on, no decomposition setting, no tool-call caps, no claim retry
    _P + "PRE_EXECUTE_VERIFY_ENABLED": "true",
    _P + "DECOMPOSITION_STRATEGY": None,
    _P + "MAX_TOOL_CALLS_PER_BLOCK": None,
    _P + "MAX_TOOL_CALLS_PER_RUN": None,
    _P + "MAX_TOOL_CALLS_PER_THREAD": None,
    _P + "CUGA_LITE_UNEXECUTED_CLAIM_RETRY": None,
    **NO_FC,
}

# The τ² agent as the τ² runner has always set it (launchers/archive/run_arm_a.py and tau2-bench's config): these base
# settings stay at the agent's defaults there. The bench.tau2 layer holds the settings it does set.
TAU2_AGENT = {
    "DYNACONF_FEATURES__LOCAL_SANBDOX": None,
    "DYNACONF_CONTEXT_SUMMARIZATION__ENABLED": None,
    _P + "MAX_TOOL_CALLS_PER_BLOCK": None,
    _P + "MAX_TOOL_CALLS_PER_RUN": None,
    _P + "MAX_TOOL_CALLS_PER_THREAD": None,
}


def _available(prefix: str, envs_dir: Path) -> list[str]:
    return sorted(
        p.name[len(prefix) : -len(".env")] for p in envs_dir.glob(f"{prefix}*.env") if p.name.count(".") == 2
    )


def _read_layer(path: Path) -> dict[str, str]:
    pairs = parse_runner(path.read_text(), path.name)
    for key, value in pairs.items():
        _check_pair(key, value, path.name)
    return pairs


def merge(
    model: str, bench: str, extra: dict | None = None, envs_dir: Path | None = None
) -> tuple[dict[str, str], list[str]]:
    """The composed key/value pairs and the names of the layer files used."""
    envs_dir = Path(envs_dir) if envs_dir else HERE
    for what, name in (("model", model), ("bench", bench)):
        if not PART_NAME.fullmatch(name or ""):
            raise ValueError(f"bad {what} name {name!r}")
    layers = [
        ("base.env", True),
        (f"model.{model}.env", True),
        (f"bench.{bench}.env", True),
        (f"pair.{model}.{bench}.env", False),
    ]
    merged: dict[str, str] = {}
    used: list[str] = []
    for name, required in layers:
        path = envs_dir / name
        if not path.exists():
            if required:
                kind = (
                    "model" if name.startswith("model.") else "bench" if name.startswith("bench.") else "base"
                )
                known = _available(kind + ".", envs_dir) if kind != "base" else []
                raise FileNotFoundError(
                    f"no {name} in {envs_dir}" + (f"; known {kind}s: {', '.join(known)}" if known else "")
                )
            continue
        merged.update(_read_layer(path))
        used.append(name)
    for key, value in (extra or {}).items():
        if value is None:
            merged.pop(key, None)
            continue
        value = "true" if value is True else "false" if value is False else str(value)
        _check_pair(key, value, "extra")
        merged[key] = value
    return merged, used


def compose(
    model: str,
    bench: str,
    extra: dict | None = None,
    *,
    envs_dir: Path | None = None,
    out_dir: Path | None = None,
) -> Path:
    """Write the env file for one child process and return its path. `extra` overrides every layer; a None value
    removes the key. `envs_dir` and `out_dir` exist for tests."""
    merged, used = merge(model, bench, extra, envs_dir)
    notes = ", ".join(sorted(k if v is not None else f"-{k}" for k, v in (extra or {}).items()))
    header = f"# composed by compose_env.py: {' + '.join(used)}" + (f" + extra [{notes}]" if notes else "")
    text = header + "\n" + "".join(f"{k}={v}\n" for k, v in merged.items())
    digest = hashlib.sha256(text.encode()).hexdigest()[:10]
    out_dir = Path(out_dir) if out_dir else Path(tempfile.gettempdir()) / "cuga_eval_envs"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"cuga.{model}.{bench}.{digest}.env"
    if not path.exists() or path.read_text() != text:
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(text)
        os.replace(tmp, path)
    return path


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and not argv[0].startswith("-"):
        extra = {}
        for item in argv[2:]:
            key, sep, value = item.partition("=")
            if not sep:
                raise SystemExit(f"extra must be KEY=VALUE, got {item!r}")
            extra[key] = value
        print(compose(argv[0], argv[1], extra))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
