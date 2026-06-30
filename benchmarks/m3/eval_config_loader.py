"""Load named sample-id sets from ``benchmarks/m3/eval_config.toml`` for ``--eval-key``.

``eval_config.toml`` maps split names (e.g. ``train`` / ``test``) to lists of
M3 sample UUIDs, plus an optional default ``eval_key``. ``eval_m3.py`` and
``eval_m3_react.py`` use this to restrict an ``--m3-data`` corpus to a named
split before any ``--task`` / ``--domain`` / ``--capability`` filters apply.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_CONFIG_PATH = Path(__file__).resolve().parent / "eval_config.toml"


def load_eval_key_ids(eval_key: Optional[str], config_path: Path = _CONFIG_PATH) -> Optional[List[str]]:
    """Resolve ``eval_key`` to a list of sample ids from ``eval_config.toml``.

    - If ``eval_key`` is ``None`` and the config sets a default ``eval_key``,
      that default is used.
    - If ``eval_key`` is ``None`` and there is no default, returns ``None``
      (no restriction — preserves the historical "run everything" behavior).
    - Raises ``FileNotFoundError`` if ``eval_key`` was explicitly requested
      but the config file doesn't exist.
    - Raises ``KeyError`` if the resolved key isn't a list in the config.
    """
    if not config_path.exists():
        if eval_key:
            raise FileNotFoundError(f"--eval-key {eval_key!r} requires {config_path}, which does not exist")
        return None

    with config_path.open("rb") as f:
        config: Dict[str, Any] = tomllib.load(f)

    key = eval_key or config.get("eval_key")
    if not key:
        return None

    ids = config.get(key)
    if not isinstance(ids, list):
        available = sorted(k for k, v in config.items() if isinstance(v, list))
        raise KeyError(f"eval_key {key!r} not found in {config_path}. Available: {available}")

    return [str(i) for i in ids]


def filter_samples_by_eval_key(
    samples: List[Dict[str, Any]], eval_key_ids: Optional[Set[str]]
) -> List[Dict[str, Any]]:
    """Keep only samples whose ``sample_id``/``uuid`` is in ``eval_key_ids``.

    Matching is case-insensitive on both sides: ``eval_key_ids`` is lower-cased
    here defensively so callers need not pre-normalize (the symmetric contract
    avoids silent zero-matches when a caller forgets to lower-case). ``None``
    means "no restriction" and returns ``samples`` unchanged; an empty set keeps
    nothing (an explicit empty split).
    """
    if eval_key_ids is None:
        return samples
    wanted = {str(i).lower() for i in eval_key_ids}
    return [s for s in samples if str(s.get("sample_id", s.get("uuid", ""))).lower() in wanted]
