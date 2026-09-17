"""Incremental, crash-safe per-task result persistence (Slice A).

This module is deliberately pure-stdlib and has **no ``cuga`` dependency**, so it
imports instantly and is fully unit-testable in isolation. The only place that
reaches into the heavier evaluation stack is :func:`finalize_merged_results`,
which imports ``save_evaluation_results`` lazily so the rest of the module stays
light.

Design (see ISSUE-11 plan):

* Each task's result is written to its own file under
  ``<bundle_dir>/results/partial/<sanitized_task_id>.json`` (or
  ``<sanitized_task_id>__<domain>.json`` for m3 config-mode per-domain results).
  One file per task means concurrent writers from an ``asyncio.gather`` batch
  never touch the same file, so no locking is required.
* Writes are atomic (temp file in the same directory + ``os.replace``), so a
  crash mid-write can never leave a corrupt final-named file.
* Failed tasks are still written (so the merged report reflects the latest
  known state) but are **excluded** from the "completed" skip-set, so
  ``--resume`` re-attempts anything that did not succeed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

PARTIAL_SUBDIR = "partial"

# Separates a task id from a domain in per-domain partial filenames. Chosen to
# be unlikely to appear inside a sanitized task id.
DOMAIN_SEP = "__"


def _sanitize(name: str) -> str:
    """Sanitize a task id for use as a filename component.

    Mirrors the exact pattern already used in
    ``bundle.py::_download_langfuse_traces`` so partial-result filenames and
    Langfuse trace filenames agree on how a task id maps to a safe name.
    """
    return str(name).replace("/", "_").replace("\\", "_")


def partial_dir(bundle_dir: Path) -> Path:
    """Return ``<bundle_dir>/results/partial`` (not created)."""
    return Path(bundle_dir) / "results" / PARTIAL_SUBDIR


def atomic_write_json(path: Path, data: Any) -> Path:
    """Write ``data`` as JSON to ``path`` atomically.

    The data is first written to a temporary file in the *same* directory
    (so ``os.replace`` stays on one filesystem and is therefore atomic) and
    then renamed over the target. On any failure the temp file is removed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return path


def _partial_filename(task_id: str, domain: Optional[str]) -> str:
    safe = _sanitize(task_id)
    if domain is not None and domain != "":
        safe = f"{safe}{DOMAIN_SEP}{_sanitize(domain)}"
    return f"{safe}.json"


def write_task_result(
    bundle_dir: Path,
    task_id: str,
    result: Dict[str, Any],
    *,
    domain: Optional[str] = None,
) -> Path:
    """Persist a single task's ``result`` dict under ``results/partial/``.

    ``domain`` is only used by m3 config-mode, where one benchmark "task" spans
    several domains; the composite ``<task_id>__<domain>.json`` filename keeps
    those from colliding. The identity fields (``task_name``/``domain``) are
    injected into a shallow copy when missing so the read paths can recover the
    completion key from file *content* rather than by reverse-mapping a
    sanitized filename.
    """
    dest = partial_dir(bundle_dir) / _partial_filename(task_id, domain)
    payload = result
    needs_task = result.get("task_name") in (None, "") and result.get("task_id") in (None, "")
    needs_domain = domain is not None and domain != "" and not result.get("domain")
    if needs_task or needs_domain:
        payload = dict(result)
        if needs_task:
            # Direct assignment, not setdefault: needs_task is True when the key
            # is present-but-empty too, and setdefault only fills absent keys.
            payload["task_name"] = task_id
        if needs_domain:
            payload["domain"] = domain
    return atomic_write_json(dest, payload)


async def write_task_result_async(
    bundle_dir: Path,
    task_id: str,
    result: Dict[str, Any],
    *,
    domain: Optional[str] = None,
) -> Path:
    """``asyncio.to_thread`` wrapper around :func:`write_task_result`.

    Used at the eval-loop call sites so persistence never blocks the event loop.
    """
    return await asyncio.to_thread(write_task_result, bundle_dir, task_id, result, domain=domain)


def _quarantine_corrupt_partial(path: Path) -> None:
    """Move an unreadable partial file out of ``*.json`` glob range.

    Left in place, a corrupt file would never count toward
    ``load_completed_task_ids`` and would re-trigger its task on every
    ``--resume`` indefinitely, with no signal to the operator. Renaming it
    (rather than deleting) keeps the evidence around for debugging while
    letting the next resume start clean.
    """
    dest = path.with_name(f"{path.name}.corrupt.{int(time.time())}")
    try:
        os.replace(path, dest)
    except OSError as e:
        logger.warning("Failed to quarantine corrupt partial %s: %s", path, e)


def _iter_partial_files(bundle_dir: Path):
    pdir = partial_dir(bundle_dir)
    if not pdir.is_dir():
        return
    for path in sorted(pdir.glob("*.json")):
        try:
            yield path, json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            # A corrupt/half-written file (shouldn't happen given atomic writes,
            # but be defensive): warn so operators can spot it, then quarantine
            # it so it stops silently re-triggering its task on every resume.
            logger.warning("Skipping corrupt partial result %s: %s", path, e)
            _quarantine_corrupt_partial(path)
            continue


def _result_task_key(data: Dict[str, Any]) -> Optional[str]:
    key = data.get("task_name")
    if key in (None, ""):
        key = data.get("task_id")
    return key if key not in (None, "") else None


def _looks_completed(data: Dict[str, Any]) -> bool:
    """Return True when a partial result represents a genuine completion.

    ``error is None`` is necessary but not sufficient: a bug in a middleware
    guard (or a broad ``except:`` swallowing a ``KeyboardInterrupt``) could
    return early with ``{"error": None, "success": False, "response": None}``
    — a task that never actually ran the agent. Treating that as "completed"
    would silently skip it on every future ``--resume``. Require, in addition
    to ``error is None``, that the result carries some sign of real work:
    ``success is True``, a non-``None`` ``response``, or a non-empty
    ``tool_calls`` list.
    """
    if data.get("error") is not None:
        return False
    if data.get("success") is True:
        return True
    if data.get("response") is not None:
        return True
    tool_calls = data.get("tool_calls")
    if tool_calls not in (None, []):
        return True
    return False


def load_completed_task_ids(bundle_dir: Path) -> Set[str]:
    """Return task ids that completed **successfully** (``error is None``).

    Errored tasks are deliberately excluded so ``--resume`` re-attempts them.
    Suitable for the simple evaluators and m3's sequential mode, whose skip
    identity is a bare task id.
    """
    completed: Set[str] = set()
    for _path, data in _iter_partial_files(bundle_dir):
        if not _looks_completed(data):
            continue
        key = _result_task_key(data)
        if key is not None:
            completed.add(key)
    return completed


def load_completed_domain_keys(bundle_dir: Path) -> Set[Tuple[str, str]]:
    """Return ``(task_id, domain)`` pairs that completed successfully.

    Used by m3 config-mode, where resume granularity is per-domain rather than
    per-task. Files that lack a ``domain`` field are skipped here (they belong
    to non-config runs).
    """
    completed: Set[Tuple[str, str]] = set()
    for _path, data in _iter_partial_files(bundle_dir):
        if not _looks_completed(data):
            continue
        key = _result_task_key(data)
        domain = data.get("domain")
        if key is not None and domain not in (None, ""):
            completed.add((key, domain))
    return completed


def load_all_partial_results(bundle_dir: Path) -> List[Dict[str, Any]]:
    """Load every partial result, regardless of success/failure.

    Used for pre-seeding ``self.results`` and for final merge/reporting so the
    merged output reflects the last known state of every task (including one
    that has failed on every attempt so far).
    """
    return [data for _path, data in _iter_partial_files(bundle_dir)]


def finalize_merged_results(
    bundle_dir: Path,
    prefix: str,
    run_timestamp: Optional[str] = None,
) -> Path:
    """Merge all on-disk partials into the canonical results file.

    Loads every partial and hands them to the existing
    ``save_evaluation_results`` so the output has the same
    ``{"metrics": ..., "results": [...]}`` shape that ``compare_report.py`` and
    ``bundle.py`` already depend on. Both the normal end-of-run save and the
    crash (``finally:``/``KeyboardInterrupt``) paths call this, so the crash
    guarantee becomes strictly stronger — it merges from disk rather than a
    possibly-incomplete in-memory list.

    The merged file is written under ``<bundle_dir>/results/``.
    """
    # Lazy import keeps this module free of the heavy cuga import chain except
    # when a caller actually needs to produce the merged file.
    from benchmarks.helpers.sdk_eval_helpers import save_evaluation_results

    results = load_all_partial_results(bundle_dir)
    output_dir = Path(bundle_dir) / "results"
    return save_evaluation_results(results, output_dir, prefix=prefix, run_timestamp=run_timestamp)
