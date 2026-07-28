"""Per-task ToolGuide policy scoping (cuga-agent#564 workaround).

The bug this works around: ``PolicyAgent.check_tool_guide_policies()`` reads
*every* enabled ToolGuide policy out of a process-shared ``PolicyStorage``
collection and match-scores each one::

    guide_policies = await self.storage.list_policies(
        policy_type=PolicyType.TOOL_GUIDE, enabled_only=True, limit=100
    )

Nothing there knows which task a policy belongs to. eval_m3 manages policies
per task (``clear_all_policies()`` then ``_load_m3_policies()``), so under
``--batch-size > 1`` several domain wrappers mutate that one collection
concurrently and each task gets matched against its siblings' guides.

Measured on a 300-task cap4 run at ``--batch-size 4``: 102 of 126 tasks (81%)
were handed at least one policy belonging to a different task, foreign
applications outnumbered legitimate ones 351 to 77, and one enactment applied
13 policies at once. A deliberately serial control run leaks nothing, so this
is a race and not a failure of ``clear_all_policies()``.

It is not cosmetic: a matched guide is applied *before* tool discovery
(``prepare_node.py:239``, ``:346``), rewriting ``tools_for_execution``,
``app_to_tools_map`` and the ``find_tools`` description — so a task can be
pointed at another task's tools before it acts.

Why this workaround is ugly, stated plainly: it keys on the M3 harness's own
``cap4_policy_<sample_id>`` naming convention, because that is the only thing
tying a stored policy back to a task. A proper fix scopes the lookup inside
cuga-agent (see #564). The precedent for benchmark-shaped enforcement living
here is ``RetrieverPolicyGuard``, which keyword-matches ``policy_judge.py``'s
exact phrasing.

Design mirrors ``tracker_isolation``: a ContextVar carries a small, freshly-set
key that is only ever read downstream, which is the one thing that survives
LangGraph's ``copy_context()`` on every node dispatch. See cuga-agent
``docs/issues/task-tool-call-history-contextvar-isolation.md`` §5.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import re
from typing import Any, Iterator, List, Optional

logger = logging.getLogger(__name__)

_ENV_FLAG = "M3_POLICY_ISOLATION"

# Policies the M3 harness loads are named `cap4_policy_<sample_id>`; the
# sample id is the only link back to an owning task.
_POLICY_NAME_RE = re.compile(r"^cap4_policy_(?P<sample_id>.+)$")

_current_task: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "m3_policy_task_id", default=None
)

_installed = False
_original_check = None
_dropped = 0
_kept = 0


def is_enabled() -> bool:
    """Default on; set M3_POLICY_ISOLATION=0 to run with the bug present."""
    return os.environ.get(_ENV_FLAG, "1").strip().lower() not in ("0", "off", "false", "no")


def dropped_count() -> int:
    """Foreign ToolGuide policies suppressed so far (0 == the bug never fired)."""
    return _dropped


def kept_count() -> int:
    return _kept


def _owner_of(policy_name: Optional[str]) -> Optional[str]:
    if not policy_name:
        return None
    m = _POLICY_NAME_RE.match(str(policy_name))
    return m.group("sample_id") if m else None


def install() -> bool:
    """Wrap ``PolicyAgent.check_tool_guide_policies`` to drop foreign guides.

    Idempotent. Returns False when disabled, already installed, or when the
    class can't be imported. Filtering the *returned matches* (rather than the
    storage read) keeps the patch to one method and leaves matching semantics,
    confidence scores and logging untouched for a task's own policy.
    """
    global _installed, _original_check
    if not is_enabled():
        return False
    if _installed:
        return True

    try:
        from cuga.backend.cuga_graph.policy.agent import PolicyAgent
    except ImportError as e:  # pragma: no cover - cuga always present in eval runs
        logger.warning("[policy-isolation] cuga PolicyAgent unavailable (%s); not installing", e)
        return False

    original = PolicyAgent.check_tool_guide_policies

    async def _scoped_check(self, context, *args, **kwargs) -> List[Any]:
        global _dropped, _kept
        matches = await original(self, context, *args, **kwargs)
        current = _current_task.get()
        if current is None or not matches:
            # Unbound (non-M3 caller, or outside a task) — preserve upstream
            # behaviour rather than guessing.
            return matches

        kept = []
        for m in matches:
            owner = _owner_of(getattr(getattr(m, "policy", None), "name", None))
            # Policies that don't follow the harness naming convention are not
            # ours to judge — keep them.
            if owner is None or owner == current:
                kept.append(m)
                _kept += 1
            else:
                _dropped += 1
                logger.info(
                    "[policy-isolation] dropped ToolGuide 'cap4_policy_%s' leaking into task %s",
                    owner,
                    current,
                )
        return kept

    PolicyAgent.check_tool_guide_policies = _scoped_check
    _original_check = original
    _installed = True
    logger.info(
        "[policy-isolation] Installed per-task ToolGuide scoping (cuga-agent#564). "
        "Concurrent tasks no longer see each other's policies."
    )
    return True


@contextlib.contextmanager
def isolated_policies(sample_id: str) -> Iterator[str]:
    """Bind ``sample_id`` as the policy owner for everything inside the block."""
    if not install():
        yield ""
        return
    token = _current_task.set(sample_id)
    try:
        yield sample_id
    finally:
        _current_task.reset(token)


def _uninstall_for_tests() -> None:
    global _installed, _original_check, _dropped, _kept
    if _installed and _original_check is not None:
        from cuga.backend.cuga_graph.policy.agent import PolicyAgent

        PolicyAgent.check_tool_guide_policies = _original_check
    _installed = False
    _original_check = None
    _dropped = 0
    _kept = 0
