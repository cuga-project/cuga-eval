"""Per-task isolation for cuga-agent's process-wide ``ActivityTracker`` singleton.

Why this exists
---------------
``ActivityTracker`` (cuga-agent, ``src/cuga/backend/activity_tracker/tracker.py``)
is a true singleton: ``__new__`` always returns the same instance, and its
per-task fields (``steps``, ``task_id``, ``token_usage``, ...) are plain shared
instance attributes with no task or thread identifier anywhere on them — the
``Step`` model has no such field either, so post-hoc filtering is impossible.

That is only safe if the process runs one task to completion before starting the
next. ``eval_m3.py``'s ``evaluate_tasks_in_batches()`` does not: it runs
``--batch-size`` tasks concurrently via ``asyncio.gather()``, in one process and
one event loop. Each task calls ``tracker.reset(...)`` at its own start, wiping
a concurrently-running sibling's in-progress state, and every reader of
``tracker.steps`` sees the interleaved union of whatever is currently in flight.

Observed consequences at ``--batch-size 4``: a hockey task whose extracted
``tool_calls`` contained ``food_inspection`` calls, ``Steps`` counts in
``report.md`` that are the sum across concurrent siblings rather than the task's
own, and trajectory JSONs containing other tasks' code blocks.

Filed upstream as cuga-agent#552.

What this does
--------------
Replaces the singleton's per-task fields with class-level ``property``
descriptors that route reads and writes to a bucket keyed by the currently-bound
task. The bucket key rides a ``ContextVar``; the buckets themselves live in an
ordinary module-level dict.

That split is deliberate, and matches the design cuga-agent itself landed on for
the same class of problem (see cuga-agent
``docs/issues/task-tool-call-history-contextvar-isolation.md`` §5(b′), and
``RetrieverPolicyGuard``): a ContextVar cannot carry *accumulating* state across
LangGraph's node dispatches, because Pregel's ``AsyncBackgroundExecutor.submit()``
calls ``copy_context()`` on every dispatch and mutations made inside one dispatch
are invisible to the next. It *can* reliably carry a small immutable key that is
only ever read downstream, because ``copy_context()`` copies the bindings that
already exist — and we set the key once, in the harness's own asyncio task,
before the agent is ever invoked.

Because the interception is at the attribute level, no reader needs to change:
``_extract_tool_calls_from_tracker()``, ``finish_task()``'s trajectory dump and
``len(tracker.steps)`` step counting all become per-task correct for free.

Ambivalence to the upstream fix
-------------------------------
This wraps the *access path*, not the tracker's internals, so it does not depend
on cuga-agent#552 being fixed. If a future cuga-agent adds its own isolation by
turning these fields into descriptors, ``install()`` detects that and declines to
patch, leaving the native implementation in charge.

Set ``M3_TRACKER_ISOLATION=0`` to disable entirely and fall back to the raw
shared-singleton behaviour.
"""

from __future__ import annotations

import contextlib
import contextvars
import copy
import inspect
import os
import threading
import uuid
from typing import Any, Dict, Iterator, Optional

from loguru import logger

# The fields ``ActivityTracker.reset()`` clears, plus ``score`` (set by
# ``collect_score``). These are exactly the per-task ones. Everything else on the
# tracker -- ``tools``, ``apps``, ``tasks``, ``experiment_folder``,
# ``tasks_metadata``, ``dataset_name``, ``session_id``, ``_base_dir`` -- is
# run-scoped by design and is deliberately left shared.
ISOLATED_FIELDS = (
    "steps",
    "prompts",
    "images",
    "task_id",
    "intent",
    "final_answer",
    "token_usage",
    "actions_count",
    "run_id",
    "start_time",
    "current_date",
    "pi",
    "user_id",
    "score",
)

_ENV_FLAG = "M3_TRACKER_ISOLATION"

# Carries only the bucket key -- never accumulating state. Read downstream across
# arbitrarily many ``copy_context()`` boundaries; written only by ``isolated_task``.
_current_key: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "m3_tracker_task_key", default=None
)

# Per-task state. Ordinary dict, so it survives every context copy.
_buckets: Dict[str, Dict[str, Any]] = {}

# Values used when no task is bound (non-M3 callers, and the run-level setup and
# teardown that happen outside any task). Preserves pre-patch behaviour.
_unbound: Dict[str, Any] = {}

# Class defaults captured before patching, used to seed fresh buckets.
_defaults: Dict[str, Any] = {}

_lock = threading.Lock()
_installed = False
_declined_reason: Optional[str] = None

# Counts writes that happened with no task bound while isolation was active.
# A non-zero count on an M3 run means some ``collect_step`` escaped the
# ContextVar -- e.g. via a ``loop.run_in_executor`` thread, which does not
# propagate context -- and that step was attributed to nobody.
_unbound_writes = 0


def is_enabled() -> bool:
    """Whether isolation is switched on via the environment (default: on)."""
    return os.environ.get(_ENV_FLAG, "1").strip().lower() not in ("0", "false", "no", "off")


def unbound_write_count() -> int:
    """Number of per-task field writes seen while no task was bound."""
    return _unbound_writes


def _bucket() -> Optional[Dict[str, Any]]:
    key = _current_key.get()
    if key is None:
        return None
    return _buckets.get(key)


def _make_property(name: str) -> property:
    def _get(_self):  # noqa: ANN001 - descriptor protocol
        bucket = _bucket()
        if bucket is None:
            return _unbound.get(name, _defaults[name])
        return bucket[name]

    def _set(_self, value):  # noqa: ANN001 - descriptor protocol
        global _unbound_writes
        bucket = _bucket()
        if bucket is None:
            _unbound_writes += 1
            _unbound[name] = value
        else:
            bucket[name] = value

    _get.__name__ = f"get_{name}"
    _set.__name__ = f"set_{name}"
    return property(_get, _set, doc=f"Task-isolated ActivityTracker.{name} (see tracker_isolation).")


def _fresh_bucket() -> Dict[str, Any]:
    # deepcopy so the list-valued defaults (``steps``, ``prompts``, ``images``)
    # never alias the class attribute or each other.
    return {name: copy.deepcopy(_defaults[name]) for name in ISOLATED_FIELDS}


def install() -> bool:
    """Patch ``ActivityTracker``'s per-task fields. Idempotent; safe to call often.

    Returns True if isolation is active after the call (including when it was
    already installed), False if it was declined or disabled.
    """
    global _installed, _declined_reason

    if _installed:
        return True
    if not is_enabled():
        _declined_reason = f"{_ENV_FLAG} is set to off"
        return False

    with _lock:
        if _installed:
            return True

        from cuga.backend.activity_tracker.tracker import ActivityTracker

        # If upstream ever gives these fields real isolation, they will stop
        # being plain class attributes. Defer to the native implementation
        # rather than layering a second mechanism on top of it.
        already_managed = [
            name
            for name in ISOLATED_FIELDS
            if inspect.getattr_static(ActivityTracker, name, None) is not None
            and hasattr(inspect.getattr_static(ActivityTracker, name, None), "__get__")
        ]
        if already_managed:
            _declined_reason = (
                f"ActivityTracker already manages {already_managed} via descriptors "
                "(upstream isolation present) - leaving it alone"
            )
            logger.info(f"[tracker-isolation] Not installing: {_declined_reason}")
            return False

        for name in ISOLATED_FIELDS:
            _defaults[name] = copy.deepcopy(getattr(ActivityTracker, name))

        # The live singleton may already carry instance-dict entries from an
        # earlier ``reset()``. ``property`` is a data descriptor so it would win
        # anyway, but leaving stale shadows around is a debugging trap.
        instance = ActivityTracker()
        for name in ISOLATED_FIELDS:
            instance.__dict__.pop(name, None)

        for name in ISOLATED_FIELDS:
            setattr(ActivityTracker, name, _make_property(name))

        _installed = True

    logger.info(
        f"[tracker-isolation] Installed per-task isolation for ActivityTracker "
        f"({len(ISOLATED_FIELDS)} fields). Concurrent tasks no longer share steps/task_id. "
        f"Disable with {_ENV_FLAG}=0."
    )
    return True


@contextlib.contextmanager
def isolated_task(label: str = "task") -> Iterator[str]:
    """Bind a fresh per-task tracker bucket for the duration of the block.

    Must wrap everything from the task's ``tracker.reset()`` through the last
    read of tracker state for that task (the tool-call extraction and
    ``finish_task``). Nested LangGraph dispatches inherit the binding, since they
    only ever read the key.

    Yields the bucket key, which is unique per call.
    """
    if not install():
        # Isolation unavailable (disabled, or upstream owns it). Behave exactly
        # as before: no binding, shared singleton.
        yield ""
        return

    key = f"{label}#{uuid.uuid4().hex[:12]}"
    with _lock:
        _buckets[key] = _fresh_bucket()
    token = _current_key.set(key)
    try:
        yield key
    finally:
        _current_key.reset(token)
        with _lock:
            _buckets.pop(key, None)


def _uninstall_for_tests() -> None:
    """Restore the unpatched class. Test-support only."""
    global _installed, _declined_reason, _unbound_writes

    with _lock:
        if _installed:
            from cuga.backend.activity_tracker.tracker import ActivityTracker

            for name in ISOLATED_FIELDS:
                setattr(ActivityTracker, name, copy.deepcopy(_defaults[name]))
        _installed = False
        _declined_reason = None
        _unbound_writes = 0
        _buckets.clear()
        _unbound.clear()
        _defaults.clear()
