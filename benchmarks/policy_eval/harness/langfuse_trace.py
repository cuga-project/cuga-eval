"""Langfuse trace of one harness task (``run.py --langfuse``).

The parent passes the keys of the local Langfuse (``LANGFUSE_ENV_FILE``, default ``~/dev/langfuse-latest/cuga.env``) to
each child; without ``--langfuse`` the child gets no ``LANGFUSE_`` variable and nothing is traced. The child opens one
root observation per task, named ``<benchmark>/<task>``, with the run, profile, trial, model and policy version as
metadata and tags. The CUGA SDK nests its own run (LLM calls, tool calls, hook decisions) under it, and the grade is
added as the trace scores ``strict`` and ``partial`` so failing traces can be filtered.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

DEFAULT_ENV_FILE = Path.home() / "dev/langfuse-latest/cuga.env"


def env_for_child() -> Dict[str, str]:
    """The Langfuse variables for a traced child (keys, host, and the CUGA switch)."""
    from dotenv import dotenv_values

    path = Path(os.environ.get("LANGFUSE_ENV_FILE") or DEFAULT_ENV_FILE)
    if not path.is_file():
        raise SystemExit(f"--langfuse: no Langfuse env file at {path} (set LANGFUSE_ENV_FILE)")
    values = {k: v for k, v in dotenv_values(path).items() if v}
    values.setdefault("DYNACONF_ADVANCED_FEATURES__LANGFUSE_TRACING", "true")
    return values


class TaskTrace:
    def __init__(self, span: Any = None):
        self.span = span

    def finish(self, result: Any) -> None:
        if self.span is None:
            return
        try:
            score = result.score
            as_dict = score.to_dict() if hasattr(score, "to_dict") else score
            self.span.update(
                output={"error": result.error, "score": as_dict},
                level="ERROR" if result.error else None,
                status_message=result.error,
            )
            if score is not None:
                primary = getattr(score, "passed", None)
                partial = getattr(score, "partial", None)
                if primary is not None:
                    self.span.score_trace(name="strict", value=1.0 if primary else 0.0)
                if partial is not None:
                    self.span.score_trace(name="partial", value=float(partial))
        except Exception as exc:  # noqa: BLE001 - tracing never changes a result
            print(f"langfuse: task result not recorded: {exc}", flush=True)


@contextmanager
def task_trace(benchmark: str, task: str, meta: Dict[str, Optional[str]]) -> Iterator[TaskTrace]:
    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        yield TaskTrace()
        return
    try:
        from langfuse import get_client, propagate_attributes

        client = get_client()
        attrs = propagate_attributes(
            session_id=meta.get("run"),
            tags=[t for t in (benchmark, meta.get("run"), meta.get("profile")) if t],
            metadata={k: str(v)[:200] for k, v in meta.items() if v is not None},
            trace_name=f"{benchmark}/{task}",
        )
        span_cm = client.start_as_current_observation(name=f"{benchmark}/{task}", as_type="span", input={"task": task})
    except Exception as exc:  # noqa: BLE001
        print(f"langfuse: task trace not started: {exc}", flush=True)
        yield TaskTrace()
        return
    with attrs, span_cm as span:
        try:
            yield TaskTrace(span)
        finally:
            try:
                client.flush()
            except Exception:  # noqa: BLE001
                pass
