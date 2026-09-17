# Run Receipt Token Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For m3 and the appworld SDK evaluator, read per-run token/timing metrics from `CugaAgent.invoke()`'s `InvokeResult.receipt` (cuga-agent's `RunReceipt`, PR cuga-agent#467) instead of fetching them from Langfuse, and surface every receipt field (input/output/cache-read/reasoning tokens, LLM calls, tool timings) in both `report.md` generators and the results JSON.

**Architecture:** cuga-agent already builds a `RunReceipt` inside `agent.invoke()` whenever `advanced_features.run_receipt` is on (default off) — no cuga-agent changes needed. Add one small pure helper in cuga-eval that flattens `invoke_result.receipt` into the existing per-task result dict, call it right after every `agent.invoke()` in the two evaluators in scope, and skip the Langfuse HTTP fetch whenever it returns data. The new fields ride through unchanged on the existing generic (no-whitelist) JSON serialization; only `compare_report.py`'s two report generators need new sections.

**Tech Stack:** Python 3, pytest (`pytest.mark.unit` / `pytest.mark.regression`), pydantic (`RunReceipt`/`ToolTiming` from cuga-agent, duck-typed via `getattr`), bash (eval.sh flag wiring).

**Spec:** This plan's header and the "Design Decisions" section below are the spec — there is no separate spec doc. The originating context is cuga-eval issue #95 ("Consistent LLM token tracking via callbacks (cache-aware) with tests") and cuga-agent PR #467 (`src/cuga/backend/cuga_graph/utils/run_receipt.py`).

## Design Decisions (read before touching code)

1. **The "flag" is cuga-agent's own `advanced_features.run_receipt` setting** (Dynaconf, env var `DYNACONF_ADVANCED_FEATURES__RUN_RECEIPT`), not a new cuga-eval-side flag. `invoke_result.receipt` is `None` unless that setting is on, so gating on `getattr(invoke_result, "receipt", None)` truthiness *is* gating on the flag — no separate setting to invent or thread through.
2. **Scope is `eval_m3.py` (via `sdk_eval_helpers.evaluate_task_with_langfuse` / `evaluate_multiturn_task_with_langfuse`) and `benchmarks/appworld/eval_appworld_sdk.py` only.** The default `benchmarks/appworld/appworld_eval.py` (graph/`ActivityTracker` path, what `eval.sh` runs without `--sdk`) never calls `agent.invoke()` and cannot produce a receipt; it is explicitly out of scope (confirmed with the user — this was a deliberate call, not an oversight). `bpo` and `oak` share the same `sdk_eval_helpers` functions and get the capability for free, but their `eval.sh` scripts are not touched, so their behavior is unchanged (the setting defaults off).
3. **Existing keys are reused, not replaced.** When a receipt is present, `total_tokens` / `total_llm_calls` / `total_cache_input_tokens` are populated *from the receipt* (so every existing aggregation/report path that already reads those three keys keeps working with zero changes). New keys are added alongside for the fields that have no existing equivalent: `input_tokens`, `output_tokens`, `cache_read_tokens`, `reasoning_tokens`, `tool_call_count`, `llm_time_s`, `tool_time_s`, `wall_time_s`, `models`, `slowest_tool`, `tool_timings`, plus a `token_source` marker (`"receipt"` vs. absent-when-Langfuse) so a report can tell which source produced the numbers.
4. **When a receipt is present, the Langfuse HTTP fetch (`fetch_langfuse_metrics_for_trace`) is skipped entirely** — this is the "instead of Langfuse" behavior the user asked for, and it also removes the up-to-8s-per-task retry/backoff latency that fetch carries. Langfuse *tracing* itself (if separately enabled) is untouched — a trace can still be created for debugging; only the metrics-fetch call is bypassed.
5. **`answer` and `tool_calls` are already captured today** (`invoke_result.answer` → `result["response"]`, `invoke_result.tool_calls` → `result["tool_calls"]`) in every path touched by this plan. No new work needed for those two fields — verify, don't re-implement.
6. **JSON storage needs no schema change.** `save_evaluation_results` (`sdk_eval_helpers.py:1905`) and `write_task_result`/`write_task_result_async` (`incremental_results.py`) both serialize `result.items()` generically with no field whitelist — new keys on the per-task result dict land in the results JSON automatically. Verified by reading both functions; no edits needed there.
7. **`metrics.py`'s `EvaluationMetrics._aggregate_langfuse_metrics` is dead code for this path** — `eval_m3.py` and `eval_appworld_sdk.py` never call `EvaluationMetrics.calculate_*` (only `benchmarks/bpo/metrics.py` does, for BPO). The actual report generator for both `eval.sh` (single run) and `compare.sh` (multi-config) is `benchmarks/helpers/compare_report.py`, so all report-generation work targets that file, not `metrics.py`.
8. **Report scope: one new "Run Receipt Breakdown" section per report, not a rewrite of every existing table.** `compare_report.py` is ~1600 lines with many independently-formatted per-group/per-difficulty/per-capability tables (markdown *and* plain-text variants of each). Threading 8 new columns through all of them is not worth the risk/complexity for this feature. Instead: one clearly-labeled section, rendered only when the underlying run actually carries receipt data (so bpo/oak/appworld-default reports — which never will, per point 2 — are byte-for-byte unchanged), showing Total + Avg/Task for every new field. This satisfies "reflect all of these fields (mean values and totals where appropriate)" without an open-ended rewrite.

## Global Constraints

- Python: match existing code style in the touched files (no type-hint modernization, no unrelated refactors).
- Every new function gets a docstring only where the *why* is non-obvious (existing repo convention — see `receipt_fields_from_invoke_result`'s "why prefixed keys are reused" note below).
- Do not touch `benchmarks/appworld/appworld_eval.py`, `benchmarks/bpo/*`, `benchmarks/oak_health_insurance/*`, or `metrics.py`.
- Do not add a new settings key anywhere — reuse `advanced_features.run_receipt`.
- All new dict/list values placed into result dicts must be JSON-serializable (`RunReceipt`/`ToolTiming` are pydantic — convert via `.model_dump()`, never pass the model instance itself).

---

### Task 1: Receipt-flattening helpers in `sdk_eval_helpers.py`

**Files:**
- Modify: `benchmarks/helpers/sdk_eval_helpers.py` (add two new functions near `fetch_langfuse_metrics_for_trace`, i.e. right after line 554 in the current file — after the `fetch_langfuse_metrics_for_trace` function and before `def setup_langfuse():`)
- Create: `benchmarks/helpers/tests/test_receipt_metrics.py`

**Interfaces:**
- Produces: `receipt_fields_from_invoke_result(invoke_result: Any) -> Optional[Dict[str, Any]]` — returns `None` when `invoke_result` has no receipt (or `receipt` is `None`); otherwise a flat dict with keys: `token_source`, `total_tokens`, `total_llm_calls`, `total_cache_input_tokens`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `reasoning_tokens`, `tool_call_count`, `llm_time_s`, `tool_time_s`, `wall_time_s`, `models` (list[str]), `slowest_tool` (str | None), `tool_timings` (list[dict] with keys `name`/`calls`/`total_ms`).
- Produces: `_accumulate_receipt_metrics(acc: Optional[Dict[str, Any]], invoke_result: Any) -> Optional[Dict[str, Any]]` — folds one turn's receipt into a running multi-turn total; returns `None` if `acc` was already `None` and this turn has no receipt either, or once any turn lacks a receipt (never partially reports). Used by Task 3.
- Consumes: nothing new (pure functions over `invoke_result`, a duck-typed object with an optional `.receipt` attribute shaped like cuga-agent's `RunReceipt`).

- [ ] **Step 1: Write the failing tests**

Create `benchmarks/helpers/tests/test_receipt_metrics.py`:

```python
"""Unit tests for the RunReceipt -> eval-result flattening helpers.

Covers cuga-eval issue #95: consistent, cache-aware token tracking sourced
from CugaAgent.invoke()'s receipt instead of Langfuse. invoke_result.receipt
is duck-typed (a plain object with the RunReceipt attributes) so these tests
don't need cuga-agent installed with a particular shape beyond attribute names.
"""

from types import SimpleNamespace

import pytest

from benchmarks.helpers.sdk_eval_helpers import (
    _accumulate_receipt_metrics,
    receipt_fields_from_invoke_result,
)

pytestmark = pytest.mark.unit


def _tool_timing(name, calls, total_ms):
    return SimpleNamespace(name=name, calls=calls, total_ms=total_ms, model_dump=lambda: {
        "name": name,
        "calls": calls,
        "total_ms": total_ms,
    })


def _receipt(**overrides):
    defaults = dict(
        models=["gpt-oss-120b"],
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        cache_read_tokens=20,
        reasoning_tokens=5,
        llm_calls=3,
        tool_call_count=2,
        llm_time_s=1.5,
        tool_time_s=0.5,
        wall_time_s=2.5,
        slowest_tool="search",
        tool_timings=[_tool_timing("search", 2, 500.0)],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_returns_none_when_invoke_result_has_no_receipt():
    invoke_result = SimpleNamespace(answer="ok")  # no .receipt attribute at all
    assert receipt_fields_from_invoke_result(invoke_result) is None


def test_returns_none_when_receipt_is_none():
    invoke_result = SimpleNamespace(answer="ok", receipt=None)
    assert receipt_fields_from_invoke_result(invoke_result) is None


def test_flattens_all_receipt_fields():
    invoke_result = SimpleNamespace(answer="ok", receipt=_receipt())
    fields = receipt_fields_from_invoke_result(invoke_result)

    assert fields["token_source"] == "receipt"
    # Existing/reused keys
    assert fields["total_tokens"] == 150
    assert fields["total_llm_calls"] == 3
    assert fields["total_cache_input_tokens"] == 20
    # New keys
    assert fields["input_tokens"] == 100
    assert fields["output_tokens"] == 50
    assert fields["cache_read_tokens"] == 20
    assert fields["reasoning_tokens"] == 5
    assert fields["tool_call_count"] == 2
    assert fields["llm_time_s"] == 1.5
    assert fields["tool_time_s"] == 0.5
    assert fields["wall_time_s"] == 2.5
    assert fields["models"] == ["gpt-oss-120b"]
    assert fields["slowest_tool"] == "search"
    assert fields["tool_timings"] == [{"name": "search", "calls": 2, "total_ms": 500.0}]


def test_accumulate_sums_across_turns():
    r1 = SimpleNamespace(answer="a", receipt=_receipt(total_tokens=100, input_tokens=70, output_tokens=30))
    r2 = SimpleNamespace(answer="b", receipt=_receipt(total_tokens=50, input_tokens=30, output_tokens=20))

    acc = _accumulate_receipt_metrics(None, r1)
    acc = _accumulate_receipt_metrics(acc, r2)

    assert acc["total_tokens"] == 150
    assert acc["input_tokens"] == 100
    assert acc["output_tokens"] == 50
    assert acc["total_llm_calls"] == 6  # 3 + 3
    assert acc["models"] == ["gpt-oss-120b"]  # deduped, not doubled
    assert len(acc["tool_timings"]) == 2  # one per turn, concatenated


def test_accumulate_returns_none_once_any_turn_lacks_a_receipt():
    r1 = SimpleNamespace(answer="a", receipt=_receipt())
    r2 = SimpleNamespace(answer="b", receipt=None)

    acc = _accumulate_receipt_metrics(None, r1)
    acc = _accumulate_receipt_metrics(acc, r2)

    assert acc is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/helpers/tests/test_receipt_metrics.py -v`
Expected: FAIL / ERROR — `ImportError: cannot import name 'receipt_fields_from_invoke_result'`.

- [ ] **Step 3: Implement the helpers**

In `benchmarks/helpers/sdk_eval_helpers.py`, insert immediately after the `fetch_langfuse_metrics_for_trace` function (i.e., right after its closing `return metrics` at line 554, before `def setup_langfuse():`):

```python
def receipt_fields_from_invoke_result(invoke_result: Any) -> Optional[Dict[str, Any]]:
    """Flatten ``InvokeResult.receipt`` (cuga-agent's RunReceipt) into result fields.

    Returns None when the caller's cuga-agent build didn't attach a receipt —
    ``advanced_features.run_receipt`` is off (the default), or the installed
    cuga-agent predates it (cuga-agent#467). Callers use that None-ness as the
    signal to fall back to the existing Langfuse-fetch path.

    Reuses total_tokens / total_llm_calls / total_cache_input_tokens so every
    existing aggregator (compare_report.py) needs no branching on where the
    numbers came from; the remaining keys have no Langfuse-path equivalent.
    """
    receipt = getattr(invoke_result, "receipt", None)
    if receipt is None:
        return None
    tool_timings = getattr(receipt, "tool_timings", None) or []
    return {
        "token_source": "receipt",
        "total_tokens": getattr(receipt, "total_tokens", 0) or 0,
        "total_llm_calls": getattr(receipt, "llm_calls", 0) or 0,
        "total_cache_input_tokens": getattr(receipt, "cache_read_tokens", 0) or 0,
        "input_tokens": getattr(receipt, "input_tokens", 0) or 0,
        "output_tokens": getattr(receipt, "output_tokens", 0) or 0,
        "cache_read_tokens": getattr(receipt, "cache_read_tokens", 0) or 0,
        "reasoning_tokens": getattr(receipt, "reasoning_tokens", 0) or 0,
        "tool_call_count": getattr(receipt, "tool_call_count", 0) or 0,
        "llm_time_s": getattr(receipt, "llm_time_s", 0.0) or 0.0,
        "tool_time_s": getattr(receipt, "tool_time_s", 0.0) or 0.0,
        "wall_time_s": getattr(receipt, "wall_time_s", 0.0) or 0.0,
        "models": list(getattr(receipt, "models", None) or []),
        "slowest_tool": getattr(receipt, "slowest_tool", None),
        "tool_timings": [
            tt.model_dump() if hasattr(tt, "model_dump") else tt for tt in tool_timings
        ],
    }


_RECEIPT_SUM_KEYS = (
    "total_tokens",
    "total_llm_calls",
    "total_cache_input_tokens",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "reasoning_tokens",
    "tool_call_count",
    "llm_time_s",
    "tool_time_s",
    "wall_time_s",
)


def _accumulate_receipt_metrics(
    acc: Optional[Dict[str, Any]], invoke_result: Any
) -> Optional[Dict[str, Any]]:
    """Fold one multi-turn step's receipt into a running total.

    A fresh RunMetricsCollector is attached per ``agent.invoke()`` call
    (cuga-agent#467), so a multi-turn task needs to sum across turns itself.
    Returns None once any turn lacks a receipt — a multi-turn total must
    never silently under-report from a partial mix of receipt/no-receipt
    turns.
    """
    fields = receipt_fields_from_invoke_result(invoke_result)
    if fields is None:
        return None
    if acc is None:
        acc = {key: (0.0 if key.endswith("_s") else 0) for key in _RECEIPT_SUM_KEYS}
        acc["token_source"] = "receipt"
        acc["models"] = []
        acc["tool_timings"] = []
        acc["slowest_tool"] = None
    for key in _RECEIPT_SUM_KEYS:
        acc[key] += fields[key]
    for model in fields["models"]:
        if model not in acc["models"]:
            acc["models"].append(model)
    acc["tool_timings"].extend(fields["tool_timings"])
    acc["slowest_tool"] = (
        max(acc["tool_timings"], key=lambda t: t.get("total_ms", 0))["name"]
        if acc["tool_timings"]
        else None
    )
    return acc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/helpers/tests/test_receipt_metrics.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add benchmarks/helpers/sdk_eval_helpers.py benchmarks/helpers/tests/test_receipt_metrics.py
git commit -m "feat(eval): add RunReceipt-to-result-fields helpers (cuga-eval#95)"
```

---

### Task 2: Wire receipt into `evaluate_task_with_langfuse` (m3/bpo/oak single-turn path)

**Files:**
- Modify: `benchmarks/helpers/sdk_eval_helpers.py:824-1099` (function `evaluate_task_with_langfuse`)
- Test: `benchmarks/helpers/tests/test_evaluate_task_with_langfuse_receipt.py`

**Interfaces:**
- Consumes: `receipt_fields_from_invoke_result` from Task 1.
- Produces: no new public interface — same `Dict[str, Any]` return shape, with the new keys present when a receipt exists.

- [ ] **Step 1: Write the failing test**

Create `benchmarks/helpers/tests/test_evaluate_task_with_langfuse_receipt.py`:

```python
"""evaluate_task_with_langfuse prefers InvokeResult.receipt over Langfuse
when the agent produced one (cuga-eval#95 / cuga-agent#467)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from benchmarks.helpers import sdk_eval_helpers

pytestmark = pytest.mark.unit


def _agent_returning(receipt):
    agent = AsyncMock()
    agent.invoke = AsyncMock(
        return_value=SimpleNamespace(answer="the answer", tool_calls=[], receipt=receipt)
    )
    return agent


def _receipt():
    return SimpleNamespace(
        models=["gpt-oss-120b"],
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        cache_read_tokens=2,
        reasoning_tokens=0,
        llm_calls=1,
        tool_call_count=0,
        llm_time_s=0.1,
        tool_time_s=0.0,
        wall_time_s=0.1,
        slowest_tool=None,
        tool_timings=[],
    )


@pytest.mark.asyncio
async def test_receipt_fields_land_in_result_when_langfuse_disabled():
    agent = _agent_returning(_receipt())
    task = {"name": "t1", "intent": "do the thing", "expected_output": {"keywords": []}}

    with patch.object(sdk_eval_helpers, "should_trace_langfuse_task", return_value=False):
        result = await sdk_eval_helpers.evaluate_task_with_langfuse(agent, task, 0)

    assert result["total_tokens"] == 15
    assert result["input_tokens"] == 10
    assert result["output_tokens"] == 5
    assert result["cache_read_tokens"] == 2
    assert result["token_source"] == "receipt"


@pytest.mark.asyncio
async def test_langfuse_fetch_skipped_when_receipt_present():
    agent = _agent_returning(_receipt())
    task = {"name": "t1", "intent": "do the thing", "expected_output": {"keywords": []}}

    fake_langfuse_module = SimpleNamespace(
        get_client=lambda: SimpleNamespace(
            create_trace_id=lambda seed: "trace-1",
            create_score=lambda **kw: None,
        )
    )

    with (
        patch.object(sdk_eval_helpers, "should_trace_langfuse_task", return_value=True),
        patch.object(sdk_eval_helpers, "build_langfuse_invoke_config", return_value={}),
        patch.object(
            sdk_eval_helpers, "fetch_langfuse_metrics_for_trace", new_callable=AsyncMock
        ) as mock_fetch,
        patch.dict("sys.modules", {"langfuse": fake_langfuse_module}),
    ):
        result = await sdk_eval_helpers.evaluate_task_with_langfuse(agent, task, 0)

    mock_fetch.assert_not_awaited()
    assert result["total_tokens"] == 15
    assert result["input_tokens"] == 10


@pytest.mark.asyncio
async def test_langfuse_fetch_still_used_when_no_receipt():
    agent = _agent_returning(None)  # no receipt: run_receipt off / old cuga-agent

    task = {"name": "t1", "intent": "do the thing", "expected_output": {"keywords": []}}

    fake_metrics = SimpleNamespace(
        total_tokens=99,
        total_llm_calls=4,
        total_cost=0.01,
        full_execution_time=1.0,
        total_cache_input_tokens=0,
        generation_timings=[],
        llm_call_details=[],
        node_timings={},
    )
    fake_langfuse_module = SimpleNamespace(
        get_client=lambda: SimpleNamespace(
            create_trace_id=lambda seed: "trace-1",
            create_score=lambda **kw: None,
        )
    )

    with (
        patch.object(sdk_eval_helpers, "should_trace_langfuse_task", return_value=True),
        patch.object(sdk_eval_helpers, "build_langfuse_invoke_config", return_value={}),
        patch.object(
            sdk_eval_helpers,
            "fetch_langfuse_metrics_for_trace",
            new_callable=AsyncMock,
            return_value=fake_metrics,
        ) as mock_fetch,
        patch.dict("sys.modules", {"langfuse": fake_langfuse_module}),
    ):
        result = await sdk_eval_helpers.evaluate_task_with_langfuse(agent, task, 0)

    mock_fetch.assert_awaited_once()
    assert result["total_tokens"] == 99
    assert "input_tokens" not in result  # Langfuse path never had this field
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/helpers/tests/test_evaluate_task_with_langfuse_receipt.py -v`
Expected: FAIL on `test_receipt_fields_land_in_result_when_langfuse_disabled` and `test_langfuse_fetch_skipped_when_receipt_present` (result has no `input_tokens`/`token_source` key yet; `mock_fetch` gets awaited even with a receipt present). `test_langfuse_fetch_still_used_when_no_receipt` should already pass (no behavior change needed for that path) — confirming it's a true regression guard, not a new requirement.

- [ ] **Step 3: Wire the helper into `evaluate_task_with_langfuse`**

In `benchmarks/helpers/sdk_eval_helpers.py`, inside `evaluate_task_with_langfuse` (starts at what is currently line 824):

Change the initializer block (currently):
```python
        keyword_check_result = None
        tool_calls = []
        _langfuse_metrics = None
        predefined_trace_id = None
```
to:
```python
        keyword_check_result = None
        tool_calls = []
        _langfuse_metrics = None
        _receipt_metrics = None
        predefined_trace_id = None
```

In the traced-success branch, change:
```python
                lf_config = build_langfuse_invoke_config(predefined_trace_id, thread_id)
                invoke_result = await _invoke_agent_for_eval(
                    agent,
                    [HumanMessage(content=intent)],
                    thread_id=thread_id,
                    user_context=user_context or "",
                    track_tool_calls=track_tool_calls,
                    lf_config=lf_config,
                )
                if isinstance(agent, GenericReactAgent) and predefined_trace_id:
```
to:
```python
                lf_config = build_langfuse_invoke_config(predefined_trace_id, thread_id)
                invoke_result = await _invoke_agent_for_eval(
                    agent,
                    [HumanMessage(content=intent)],
                    thread_id=thread_id,
                    user_context=user_context or "",
                    track_tool_calls=track_tool_calls,
                    lf_config=lf_config,
                )
                _receipt_metrics = receipt_fields_from_invoke_result(invoke_result)
                if isinstance(agent, GenericReactAgent) and predefined_trace_id:
```

Then change the fetch guard, currently:
```python
                try:
                    _langfuse_metrics = await fetch_langfuse_metrics_for_trace(predefined_trace_id)
                except Exception as langfuse_err:
                    logger.warning(f"Failed to fetch Langfuse metrics: {langfuse_err}")
                    _langfuse_metrics = None
```
to:
```python
                if _receipt_metrics is None:
                    try:
                        _langfuse_metrics = await fetch_langfuse_metrics_for_trace(predefined_trace_id)
                    except Exception as langfuse_err:
                        logger.warning(f"Failed to fetch Langfuse metrics: {langfuse_err}")
                        _langfuse_metrics = None
```

In the traced-but-exception fallback branch, change:
```python
                invoke_result = await _invoke_agent_for_eval(
                    agent,
                    [HumanMessage(content=intent)],
                    thread_id=thread_id,
                    user_context=user_context or "",
                    track_tool_calls=track_tool_calls,
                )
                # Handle both string and object return types
                response = invoke_result.answer if hasattr(invoke_result, 'answer') else invoke_result
                keyword_check_result = check_keywords(response, expected_keywords)
        else:
            invoke_result = await agent.invoke(
                [HumanMessage(content=intent)],
                thread_id=thread_id,
                user_context=user_context or "",
                track_tool_calls=track_tool_calls,
            )
            # Handle both string and object return types
            response = invoke_result.answer if hasattr(invoke_result, 'answer') else invoke_result
            keyword_check_result = check_keywords(response, expected_keywords)
```
to:
```python
                invoke_result = await _invoke_agent_for_eval(
                    agent,
                    [HumanMessage(content=intent)],
                    thread_id=thread_id,
                    user_context=user_context or "",
                    track_tool_calls=track_tool_calls,
                )
                _receipt_metrics = receipt_fields_from_invoke_result(invoke_result)
                # Handle both string and object return types
                response = invoke_result.answer if hasattr(invoke_result, 'answer') else invoke_result
                keyword_check_result = check_keywords(response, expected_keywords)
        else:
            invoke_result = await agent.invoke(
                [HumanMessage(content=intent)],
                thread_id=thread_id,
                user_context=user_context or "",
                track_tool_calls=track_tool_calls,
            )
            _receipt_metrics = receipt_fields_from_invoke_result(invoke_result)
            # Handle both string and object return types
            response = invoke_result.answer if hasattr(invoke_result, 'answer') else invoke_result
            keyword_check_result = check_keywords(response, expected_keywords)
```

Finally, change the merge block, currently:
```python
        if predefined_trace_id:
            result["trace_id"] = predefined_trace_id
        if _langfuse_metrics:
            result["total_tokens"] = _langfuse_metrics.total_tokens
            result["total_llm_calls"] = _langfuse_metrics.total_llm_calls
            result["total_cost"] = _langfuse_metrics.total_cost
            result["full_execution_time"] = _langfuse_metrics.full_execution_time
            result["total_cache_input_tokens"] = _langfuse_metrics.total_cache_input_tokens
            result["generation_timings"] = _langfuse_metrics.generation_timings
            result["llm_call_details"] = _langfuse_metrics.llm_call_details
            result["node_timings"] = _langfuse_metrics.node_timings
```
to:
```python
        if predefined_trace_id:
            result["trace_id"] = predefined_trace_id
        if _receipt_metrics:
            result.update(_receipt_metrics)
        elif _langfuse_metrics:
            result["total_tokens"] = _langfuse_metrics.total_tokens
            result["total_llm_calls"] = _langfuse_metrics.total_llm_calls
            result["total_cost"] = _langfuse_metrics.total_cost
            result["full_execution_time"] = _langfuse_metrics.full_execution_time
            result["total_cache_input_tokens"] = _langfuse_metrics.total_cache_input_tokens
            result["generation_timings"] = _langfuse_metrics.generation_timings
            result["llm_call_details"] = _langfuse_metrics.llm_call_details
            result["node_timings"] = _langfuse_metrics.node_timings
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/helpers/tests/test_evaluate_task_with_langfuse_receipt.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the existing sdk_eval_helpers regression suite**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/helpers/tests/test_invoke_agent_for_eval.py benchmarks/helpers/tests/test_langfuse_cache_tokens.py -v`
Expected: PASS, unchanged (this task must not touch the non-receipt code paths' behavior).

- [ ] **Step 6: Commit**

```bash
git add benchmarks/helpers/sdk_eval_helpers.py benchmarks/helpers/tests/test_evaluate_task_with_langfuse_receipt.py
git commit -m "feat(eval): prefer RunReceipt over Langfuse fetch in evaluate_task_with_langfuse"
```

---

### Task 3: Wire receipt into `evaluate_multiturn_task_with_langfuse` (m3 multi-turn path)

**Files:**
- Modify: `benchmarks/helpers/sdk_eval_helpers.py:1343-1673` (function `evaluate_multiturn_task_with_langfuse`)
- Test: `benchmarks/helpers/tests/test_evaluate_multiturn_task_with_langfuse_receipt.py`

**Interfaces:**
- Consumes: `_accumulate_receipt_metrics` from Task 1.
- Produces: same shape as Task 2, accumulated across all turns.

- [ ] **Step 1: Write the failing test**

Create `benchmarks/helpers/tests/test_evaluate_multiturn_task_with_langfuse_receipt.py`:

```python
"""evaluate_multiturn_task_with_langfuse sums InvokeResult.receipt across
turns instead of fetching Langfuse metrics, when receipts are available."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from benchmarks.helpers import sdk_eval_helpers

pytestmark = pytest.mark.unit


def _receipt(total_tokens, input_tokens, output_tokens):
    return SimpleNamespace(
        models=["gpt-oss-120b"],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cache_read_tokens=0,
        reasoning_tokens=0,
        llm_calls=1,
        tool_call_count=0,
        llm_time_s=0.1,
        tool_time_s=0.0,
        wall_time_s=0.1,
        slowest_tool=None,
        tool_timings=[],
    )


@pytest.mark.asyncio
async def test_receipt_accumulates_across_turns_without_langfuse():
    agent = AsyncMock()
    agent.invoke = AsyncMock(
        side_effect=[
            SimpleNamespace(answer="turn 1 answer", tool_calls=[], receipt=_receipt(10, 7, 3)),
            SimpleNamespace(answer="turn 2 answer", tool_calls=[], receipt=_receipt(20, 14, 6)),
        ]
    )
    turns = [{"query": "first"}, {"query": "second"}]

    with patch.object(sdk_eval_helpers, "should_trace_langfuse_task", return_value=False):
        result = await sdk_eval_helpers.evaluate_multiturn_task_with_langfuse(
            agent, turns, "task-1", 0, turn_delay=0.0
        )

    assert result["total_tokens"] == 30
    assert result["input_tokens"] == 21
    assert result["output_tokens"] == 9
    assert result["token_source"] == "receipt"


@pytest.mark.asyncio
async def test_langfuse_fetch_skipped_when_all_turns_have_receipts():
    agent = AsyncMock()
    fake_langfuse_module = SimpleNamespace(
        get_client=lambda: SimpleNamespace(
            create_trace_id=lambda seed: "trace-1",
            create_score=lambda **kw: None,
        )
    )

    with (
        patch.object(sdk_eval_helpers, "should_trace_langfuse_task", return_value=True),
        patch.object(sdk_eval_helpers, "build_langfuse_invoke_config", return_value={}),
        patch.object(
            sdk_eval_helpers, "_invoke_agent_for_eval", new_callable=AsyncMock
        ) as mock_invoke,
        patch.object(
            sdk_eval_helpers, "fetch_langfuse_metrics_for_trace", new_callable=AsyncMock
        ) as mock_fetch,
        patch.object(sdk_eval_helpers, "record_harness_trace_output"),
        patch.dict("sys.modules", {"langfuse": fake_langfuse_module}),
    ):
        mock_invoke.return_value = SimpleNamespace(
            answer="turn answer", tool_calls=[], receipt=_receipt(10, 7, 3)
        )
        turns = [{"query": "only turn"}]
        result = await sdk_eval_helpers.evaluate_multiturn_task_with_langfuse(
            agent, turns, "task-1", 0, turn_delay=0.0
        )

    mock_fetch.assert_not_awaited()
    assert result["total_tokens"] == 10
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/helpers/tests/test_evaluate_multiturn_task_with_langfuse_receipt.py -v`
Expected: FAIL (result has no `input_tokens`/`token_source`; `mock_fetch` gets awaited despite receipts being present).

- [ ] **Step 3: Wire the accumulator into `evaluate_multiturn_task_with_langfuse`**

In `benchmarks/helpers/sdk_eval_helpers.py`, inside `evaluate_multiturn_task_with_langfuse`:

Change the initializer (currently):
```python
        keyword_check_result = None
        all_responses = []
        all_tool_calls = []
        final_response = None
        _langfuse_metrics = None
        predefined_trace_id = None
        total_react_steps = 0
```
to:
```python
        keyword_check_result = None
        all_responses = []
        all_tool_calls = []
        final_response = None
        _langfuse_metrics = None
        _receipt_metrics = None
        predefined_trace_id = None
        total_react_steps = 0
```

In the traced-success turn loop, change:
```python
                    invoke_result = await _invoke_agent_for_eval(
                        agent,
                        [HumanMessage(content=query)],
                        thread_id=thread_id,
                        user_context=user_context or "",
                        track_tool_calls=track_tool_calls,
                        lf_config=lf_config,
                    )
                    total_react_steps = _accumulate_react_steps(total_react_steps, invoke_result)
                    result_state = invoke_result.answer
                    turn_tool_calls = invoke_result.tool_calls or []
                    all_tool_calls.extend([(turn_idx, tc) for tc in turn_tool_calls])

                    all_responses.append(
                        {
                            "turn": turn_idx,
                            "query": query,
                            "response": result_state,
                            "tool_calls": [tc for tc in turn_tool_calls],
                        }
                    )

                    answer_preview = result_state[:100] if result_state else "(empty)"
                    logger.info(
                        f"[Turn {turn_idx}] Response received: {answer_preview}{'...' if len(result_state) > 100 else ''}"
                    )
                    logger.info(f"[Turn {turn_idx}] Tool calls captured: {len(turn_tool_calls)}")

                    if not turn_tool_calls and result_state:
                        logger.warning(f"[Turn {turn_idx}] ⚠️  Answer provided but NO tool calls recorded!")
                    elif turn_tool_calls:
                        tool_names = [
                            tc.get('name', 'unknown')
                            if isinstance(tc, dict)
                            else getattr(tc, 'name', 'unknown')
                            for tc in turn_tool_calls
                        ]
                        logger.info(f"[Turn {turn_idx}] Tools used: {tool_names}")

                    if turn_idx < num_turns:
                        await asyncio.sleep(turn_delay)

                final_response = all_responses[-1]["response"] if all_responses else None

                if expected_keywords and final_response:
```
to (only the two added lines after `total_react_steps = ...` differ from the current file):
```python
                    invoke_result = await _invoke_agent_for_eval(
                        agent,
                        [HumanMessage(content=query)],
                        thread_id=thread_id,
                        user_context=user_context or "",
                        track_tool_calls=track_tool_calls,
                        lf_config=lf_config,
                    )
                    total_react_steps = _accumulate_react_steps(total_react_steps, invoke_result)
                    _receipt_metrics = _accumulate_receipt_metrics(_receipt_metrics, invoke_result)
                    result_state = invoke_result.answer
                    turn_tool_calls = invoke_result.tool_calls or []
                    all_tool_calls.extend([(turn_idx, tc) for tc in turn_tool_calls])

                    all_responses.append(
                        {
                            "turn": turn_idx,
                            "query": query,
                            "response": result_state,
                            "tool_calls": [tc for tc in turn_tool_calls],
                        }
                    )

                    answer_preview = result_state[:100] if result_state else "(empty)"
                    logger.info(
                        f"[Turn {turn_idx}] Response received: {answer_preview}{'...' if len(result_state) > 100 else ''}"
                    )
                    logger.info(f"[Turn {turn_idx}] Tool calls captured: {len(turn_tool_calls)}")

                    if not turn_tool_calls and result_state:
                        logger.warning(f"[Turn {turn_idx}] ⚠️  Answer provided but NO tool calls recorded!")
                    elif turn_tool_calls:
                        tool_names = [
                            tc.get('name', 'unknown')
                            if isinstance(tc, dict)
                            else getattr(tc, 'name', 'unknown')
                            for tc in turn_tool_calls
                        ]
                        logger.info(f"[Turn {turn_idx}] Tools used: {tool_names}")

                    if turn_idx < num_turns:
                        await asyncio.sleep(turn_delay)

                final_response = all_responses[-1]["response"] if all_responses else None

                if expected_keywords and final_response:
```

Then guard the Langfuse fetch, currently:
```python
                try:
                    _langfuse_metrics = await fetch_langfuse_metrics_for_trace(predefined_trace_id)
                except Exception as langfuse_err:
                    logger.warning(f"Failed to fetch Langfuse metrics: {langfuse_err}")
                    _langfuse_metrics = None
```
to:
```python
                if _receipt_metrics is None:
                    try:
                        _langfuse_metrics = await fetch_langfuse_metrics_for_trace(predefined_trace_id)
                    except Exception as langfuse_err:
                        logger.warning(f"Failed to fetch Langfuse metrics: {langfuse_err}")
                        _langfuse_metrics = None
```

In the traced-but-exception fallback loop, change:
```python
                    invoke_result = await _invoke_agent_for_eval(
                        agent,
                        [HumanMessage(content=query)],
                        thread_id=thread_id,
                        user_context=user_context or "",
                        track_tool_calls=track_tool_calls,
                    )
                    total_react_steps = _accumulate_react_steps(total_react_steps, invoke_result)
                    result_state = invoke_result.answer
```
to:
```python
                    invoke_result = await _invoke_agent_for_eval(
                        agent,
                        [HumanMessage(content=query)],
                        thread_id=thread_id,
                        user_context=user_context or "",
                        track_tool_calls=track_tool_calls,
                    )
                    total_react_steps = _accumulate_react_steps(total_react_steps, invoke_result)
                    _receipt_metrics = _accumulate_receipt_metrics(_receipt_metrics, invoke_result)
                    result_state = invoke_result.answer
```

In the untraced (`else`) loop, change:
```python
                invoke_result = await agent.invoke(
                    [HumanMessage(content=query)],
                    thread_id=thread_id,
                    user_context=user_context,
                    track_tool_calls=track_tool_calls,
                )
                total_react_steps = _accumulate_react_steps(total_react_steps, invoke_result)
                result_state = invoke_result.answer
```
to:
```python
                invoke_result = await agent.invoke(
                    [HumanMessage(content=query)],
                    thread_id=thread_id,
                    user_context=user_context,
                    track_tool_calls=track_tool_calls,
                )
                total_react_steps = _accumulate_react_steps(total_react_steps, invoke_result)
                _receipt_metrics = _accumulate_receipt_metrics(_receipt_metrics, invoke_result)
                result_state = invoke_result.answer
```

Finally, change the merge block, currently:
```python
        if predefined_trace_id:
            result["trace_id"] = predefined_trace_id
        if _langfuse_metrics:
            result["total_tokens"] = _langfuse_metrics.total_tokens
            result["total_llm_calls"] = _langfuse_metrics.total_llm_calls
            result["total_cost"] = _langfuse_metrics.total_cost
            result["full_execution_time"] = _langfuse_metrics.full_execution_time
            result["total_cache_input_tokens"] = _langfuse_metrics.total_cache_input_tokens
            result["generation_timings"] = _langfuse_metrics.generation_timings
            result["llm_call_details"] = _langfuse_metrics.llm_call_details
            result["node_timings"] = _langfuse_metrics.node_timings
```
to:
```python
        if predefined_trace_id:
            result["trace_id"] = predefined_trace_id
        if _receipt_metrics:
            result.update(_receipt_metrics)
        elif _langfuse_metrics:
            result["total_tokens"] = _langfuse_metrics.total_tokens
            result["total_llm_calls"] = _langfuse_metrics.total_llm_calls
            result["total_cost"] = _langfuse_metrics.total_cost
            result["full_execution_time"] = _langfuse_metrics.full_execution_time
            result["total_cache_input_tokens"] = _langfuse_metrics.total_cache_input_tokens
            result["generation_timings"] = _langfuse_metrics.generation_timings
            result["llm_call_details"] = _langfuse_metrics.llm_call_details
            result["node_timings"] = _langfuse_metrics.node_timings
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/helpers/tests/test_evaluate_multiturn_task_with_langfuse_receipt.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full sdk_eval_helpers test directory**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/helpers/tests/ -v -k "not bundle and not resume_integration"`
Expected: PASS (existing tests unaffected; skip the slower bundle/resume integration tests here for speed, they aren't touched by this task).

- [ ] **Step 6: Commit**

```bash
git add benchmarks/helpers/sdk_eval_helpers.py benchmarks/helpers/tests/test_evaluate_multiturn_task_with_langfuse_receipt.py
git commit -m "feat(eval): prefer RunReceipt over Langfuse fetch in evaluate_multiturn_task_with_langfuse"
```

---

### Task 4: Wire receipt into `eval_appworld_sdk.py`

**Files:**
- Modify: `benchmarks/appworld/eval_appworld_sdk.py:118-336` (function `invoke_and_score_appworld`)
- Test: `benchmarks/appworld/tests/test_invoke_and_score_appworld_receipt.py` (create the `tests/` dir if it does not already exist — check first with `ls benchmarks/appworld/tests/` before creating; if it exists, add the file there and mirror the existing `__init__.py` pattern)

**Interfaces:**
- Consumes: `receipt_fields_from_invoke_result` from `benchmarks.helpers.sdk_eval_helpers` (Task 1).
- Produces: same result-dict shape as Task 2, for the appworld-sdk per-task result.

- [ ] **Step 1: Check for an existing appworld tests directory**

Run: `ls benchmarks/appworld/tests/ 2>&1 || echo "does not exist"`

If it does not exist, create it:
```bash
mkdir -p benchmarks/appworld/tests
touch benchmarks/appworld/tests/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `benchmarks/appworld/tests/test_invoke_and_score_appworld_receipt.py`:

```python
"""invoke_and_score_appworld prefers InvokeResult.receipt over a Langfuse
fetch when the agent produced one (cuga-eval#95 / cuga-agent#467)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from benchmarks.appworld import eval_appworld_sdk

pytestmark = pytest.mark.unit


def _receipt():
    return SimpleNamespace(
        models=["gpt-oss-120b"],
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        cache_read_tokens=2,
        reasoning_tokens=0,
        llm_calls=1,
        tool_call_count=0,
        llm_time_s=0.1,
        tool_time_s=0.0,
        wall_time_s=0.1,
        slowest_tool=None,
        tool_timings=[],
    )


def _world():
    world = MagicMock()
    world.task.instruction = "do the appworld thing"
    world.evaluate.return_value = MagicMock()
    return world


@pytest.mark.asyncio
async def test_receipt_fields_populate_result_without_langfuse_handler():
    agent = AsyncMock()
    agent.invoke = AsyncMock(
        return_value=SimpleNamespace(answer="done", tool_calls=[], receipt=_receipt())
    )
    world = _world()

    with patch.object(
        eval_appworld_sdk, "evaluation_task_info", return_value={"success": True, "pass_percentage": 100}
    ):
        result = await eval_appworld_sdk.invoke_and_score_appworld(
            agent, None, world, "task-1", 0, "easy", None
        )

    assert result["total_tokens"] == 15
    assert result["input_tokens"] == 10
    assert result["token_source"] == "receipt"


@pytest.mark.asyncio
async def test_langfuse_fetch_skipped_when_receipt_present_even_with_handler():
    agent = AsyncMock()
    agent.invoke = AsyncMock(
        return_value=SimpleNamespace(answer="done", tool_calls=[], receipt=_receipt())
    )
    world = _world()
    fake_langfuse_module = SimpleNamespace(
        get_client=lambda: SimpleNamespace(
            create_trace_id=lambda seed: "trace-1",
            create_score=lambda **kw: None,
        )
    )

    with (
        patch.object(
            eval_appworld_sdk, "evaluation_task_info", return_value={"success": True, "pass_percentage": 100}
        ),
        patch(
            "benchmarks.helpers.sdk_eval_helpers.fetch_langfuse_metrics_for_trace",
            new_callable=AsyncMock,
        ) as mock_fetch,
        patch.dict("sys.modules", {"langfuse": fake_langfuse_module}),
    ):
        result = await eval_appworld_sdk.invoke_and_score_appworld(
            agent, "handler", world, "task-1", 0, "easy", None
        )

    mock_fetch.assert_not_awaited()
    assert result["total_tokens"] == 15
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/appworld/tests/test_invoke_and_score_appworld_receipt.py -v`
Expected: FAIL (no `input_tokens`/`token_source` key on the result yet; with a `langfuse_handler` set, the fetch currently always runs regardless of receipt presence).

- [ ] **Step 4: Wire the helper into `invoke_and_score_appworld`**

In `benchmarks/appworld/eval_appworld_sdk.py`, add the import near the existing one:

Change:
```python
from benchmarks.helpers.sdk_eval_helpers import _react_steps_from_invoke_result
```
to:
```python
from benchmarks.helpers.sdk_eval_helpers import (
    _react_steps_from_invoke_result,
    receipt_fields_from_invoke_result,
)
```

In `run_invoke`, change:
```python
    async def run_invoke(invoke_config: Optional[dict] = None) -> None:
        nonlocal response, tool_calls, err, err_exc, is_error, invoked
        try:
            invoke_result = await agent.invoke(
                [HumanMessage(content=intent)],
                thread_id=thread_id,
                user_context=user_context,
                track_tool_calls=track_tool_calls,
                config=invoke_config or {},
            )
            invoke_result_holder.clear()
            invoke_result_holder.append(invoke_result)
            response = invoke_result.answer
            tool_calls = list(invoke_result.tool_calls or []) if track_tool_calls else []
            invoked = True
        except Exception as e:
            err = str(e)
            err_exc = e
            is_error = True
            logger.error(f"Agent invoke failed: {e}")
```
to (adds `_receipt_metrics` capture as a nonlocal, mirroring the existing pattern):
```python
    async def run_invoke(invoke_config: Optional[dict] = None) -> None:
        nonlocal response, tool_calls, err, err_exc, is_error, invoked, _receipt_metrics
        try:
            invoke_result = await agent.invoke(
                [HumanMessage(content=intent)],
                thread_id=thread_id,
                user_context=user_context,
                track_tool_calls=track_tool_calls,
                config=invoke_config or {},
            )
            invoke_result_holder.clear()
            invoke_result_holder.append(invoke_result)
            response = invoke_result.answer
            tool_calls = list(invoke_result.tool_calls or []) if track_tool_calls else []
            _receipt_metrics = receipt_fields_from_invoke_result(invoke_result)
            invoked = True
        except Exception as e:
            err = str(e)
            err_exc = e
            is_error = True
            logger.error(f"Agent invoke failed: {e}")
```

Declare `_receipt_metrics` alongside the other per-task locals. Change:
```python
    eval_dict: Dict[str, Any] = {}
    trace_id: Optional[str] = None
    _langfuse_metrics = None
    invoke_result_holder: List[Any] = []
```
to:
```python
    eval_dict: Dict[str, Any] = {}
    trace_id: Optional[str] = None
    _langfuse_metrics = None
    _receipt_metrics = None
    invoke_result_holder: List[Any] = []
```

Change the Langfuse-fetch guard, currently:
```python
            try:
                _langfuse_metrics = await fetch_langfuse_metrics_for_trace(predefined_trace_id)
            except Exception as langfuse_err:
                logger.warning(f"Failed to fetch Langfuse metrics: {langfuse_err}")
                _langfuse_metrics = None
        except Exception as e:
            logger.warning(f"Langfuse trace failed: {e}")
            _langfuse_metrics = None
```
to:
```python
            if _receipt_metrics is None:
                try:
                    _langfuse_metrics = await fetch_langfuse_metrics_for_trace(predefined_trace_id)
                except Exception as langfuse_err:
                    logger.warning(f"Failed to fetch Langfuse metrics: {langfuse_err}")
                    _langfuse_metrics = None
        except Exception as e:
            logger.warning(f"Langfuse trace failed: {e}")
            _langfuse_metrics = None
```

Finally, change the merge block, currently:
```python
    # Add Langfuse metrics if available
    if langfuse_handler and _langfuse_metrics:
        result["total_tokens"] = _langfuse_metrics.total_tokens
        result["total_llm_calls"] = _langfuse_metrics.total_llm_calls
        result["total_cost"] = _langfuse_metrics.total_cost
        result["full_execution_time"] = _langfuse_metrics.full_execution_time
        result["total_cache_input_tokens"] = _langfuse_metrics.total_cache_input_tokens
        result["generation_timings"] = _langfuse_metrics.generation_timings
        result["llm_call_details"] = _langfuse_metrics.llm_call_details
        result["node_timings"] = _langfuse_metrics.node_timings
```
to (dropping the `langfuse_handler and` guard on the receipt branch — the receipt never depended on Langfuse tracing being on):
```python
    # Prefer the SDK's own RunReceipt (advanced_features.run_receipt) over a
    # Langfuse fetch when both are available (cuga-eval#95 / cuga-agent#467).
    if _receipt_metrics:
        result.update(_receipt_metrics)
    elif langfuse_handler and _langfuse_metrics:
        result["total_tokens"] = _langfuse_metrics.total_tokens
        result["total_llm_calls"] = _langfuse_metrics.total_llm_calls
        result["total_cost"] = _langfuse_metrics.total_cost
        result["full_execution_time"] = _langfuse_metrics.full_execution_time
        result["total_cache_input_tokens"] = _langfuse_metrics.total_cache_input_tokens
        result["generation_timings"] = _langfuse_metrics.generation_timings
        result["llm_call_details"] = _langfuse_metrics.llm_call_details
        result["node_timings"] = _langfuse_metrics.node_timings
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/appworld/tests/test_invoke_and_score_appworld_receipt.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add benchmarks/appworld/eval_appworld_sdk.py benchmarks/appworld/tests/
git commit -m "feat(eval): prefer RunReceipt over Langfuse fetch in eval_appworld_sdk"
```

---

### Task 5: Turn the flag on for m3 and appworld-sdk eval.sh

**Files:**
- Modify: `benchmarks/m3/eval.sh:360` (right after the existing `DYNACONF_SERVER_PORTS__REGISTRY` export)
- Modify: `benchmarks/appworld/eval.sh:130` (right after the existing `DYNACONF_SERVER_PORTS__APIS_URL` export)

**Interfaces:**
- Consumes: nothing (env var only).
- Produces: `DYNACONF_ADVANCED_FEATURES__RUN_RECEIPT=true` in both scripts' environment, inherited by every python subprocess they launch (including when `compare.sh` shells out to `eval.sh` — no separate change needed in `compare.sh`, verified by reading both compare.sh scripts: they only `source load_env.sh` and then invoke `./eval.sh`, which performs this export itself on each invocation).

- [ ] **Step 1: Edit `benchmarks/m3/eval.sh`**

Change:
```bash
REGISTRY_PORT="${REGISTRY_PORT:-${DYNACONF_SERVER_PORTS__REGISTRY:-8001}}"
export REGISTRY_PORT
export DYNACONF_SERVER_PORTS__REGISTRY="$REGISTRY_PORT"

# Capture the cuga-agent checkout's git state now, before the eval run starts
```
to:
```bash
REGISTRY_PORT="${REGISTRY_PORT:-${DYNACONF_SERVER_PORTS__REGISTRY:-8001}}"
export REGISTRY_PORT
export DYNACONF_SERVER_PORTS__REGISTRY="$REGISTRY_PORT"

# Per-run token/timing receipt from CugaAgent.invoke() (cuga-agent#467),
# preferred over the Langfuse HTTP fetch when present (cuga-eval#95).
export DYNACONF_ADVANCED_FEATURES__RUN_RECEIPT=true

# Capture the cuga-agent checkout's git state now, before the eval run starts
```

- [ ] **Step 2: Edit `benchmarks/appworld/eval.sh`**

Change:
```bash
APPWORLD_APIS_PORT="${APPWORLD_APIS_PORT:-${DYNACONF_SERVER_PORTS__APIS_URL:-9111}}"
export APPWORLD_APIS_PORT
export DYNACONF_SERVER_PORTS__APIS_URL="$APPWORLD_APIS_PORT"

# Capture console output to a log file for reproducibility bundles
```
to:
```bash
APPWORLD_APIS_PORT="${APPWORLD_APIS_PORT:-${DYNACONF_SERVER_PORTS__APIS_URL:-9111}}"
export APPWORLD_APIS_PORT
export DYNACONF_SERVER_PORTS__APIS_URL="$APPWORLD_APIS_PORT"

# Per-run token/timing receipt from CugaAgent.invoke() (cuga-agent#467).
# Only the --sdk evaluator (eval_appworld_sdk.py) calls agent.invoke() and can
# use it; the default graph-based appworld_eval.py ignores it harmlessly.
export DYNACONF_ADVANCED_FEATURES__RUN_RECEIPT=true

# Capture console output to a log file for reproducibility bundles
```

- [ ] **Step 3: Verify the exports are present**

Run: `grep -n "DYNACONF_ADVANCED_FEATURES__RUN_RECEIPT" benchmarks/m3/eval.sh benchmarks/appworld/eval.sh`
Expected: one match per file.

- [ ] **Step 4: Shellcheck the two edited scripts (repo convention — verify no new lint issues)**

Run: `shellcheck benchmarks/m3/eval.sh benchmarks/appworld/eval.sh || true`
Expected: no new warnings attributable to the two added lines (a plain `export VAR=value` with a literal value shellchecks clean).

- [ ] **Step 5: Commit**

```bash
git add benchmarks/m3/eval.sh benchmarks/appworld/eval.sh
git commit -m "feat(eval): enable advanced_features.run_receipt for m3 and appworld-sdk eval.sh"
```

---

### Task 6: Extend `compare_report.py` parsing + aggregation with receipt fields

**Files:**
- Modify: `benchmarks/helpers/compare_report.py:254-353` (`_parse_sdk_results`) and add a new function after `_aggregate_costs` (currently ending at line 546)
- Test: extend `benchmarks/helpers/tests/test_compare_report.py`

**Interfaces:**
- Produces: `_parse_sdk_results` return dict gains `input_tokens`, `output_tokens`, `cache_read_tokens`, `reasoning_tokens`, `tool_call_count`, `llm_time_s`, `tool_time_s`, `wall_time_s` at the top level (totals) **and** on each entry of `tasks[name]` (per-task); all default to `0`/`0.0` when absent from the source result (so existing bpo/oak/appworld-default result files, which never carry these keys, produce all-zero totals rather than crashing).
- Produces: `_aggregate_receipt_costs(tasks: dict) -> dict` — same shape as `_aggregate_costs`, for the 8 new fields; returns a dict of `None`s (not zeros) when no task carries `receipt`-sourced data, so callers can render "--" instead of a misleading "0".

- [ ] **Step 1: Write the failing tests**

Append to `benchmarks/helpers/tests/test_compare_report.py` (add these imports to the existing `from benchmarks.helpers.compare_report import (...)` block: `_aggregate_receipt_costs`, and keep `_parse_sdk_results`, `generate_eval_report`, `generate_report` already imported there):

```python
def test_parse_sdk_results_extracts_receipt_fields():
    data = {
        "metrics": {"total_tasks": 1, "passed": 1},
        "results": [
            {
                "task_name": "t1",
                "success": True,
                "total_tokens": 150,
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_tokens": 20,
                "reasoning_tokens": 5,
                "tool_call_count": 2,
                "llm_time_s": 1.5,
                "tool_time_s": 0.5,
                "wall_time_s": 2.5,
            }
        ],
    }
    parsed = _parse_sdk_results(data)

    assert parsed["input_tokens"] == 100
    assert parsed["output_tokens"] == 50
    assert parsed["cache_read_tokens"] == 20
    assert parsed["reasoning_tokens"] == 5
    assert parsed["tool_call_count"] == 2
    assert parsed["llm_time_s"] == 1.5
    assert parsed["tool_time_s"] == 0.5
    assert parsed["wall_time_s"] == 2.5
    assert parsed["tasks"]["t1"]["input_tokens"] == 100


def test_parse_sdk_results_defaults_receipt_fields_to_zero_when_absent():
    data = {
        "metrics": {"total_tasks": 1, "passed": 1},
        "results": [{"task_name": "t1", "success": True, "total_tokens": 50}],
    }
    parsed = _parse_sdk_results(data)

    assert parsed["input_tokens"] == 0
    assert parsed["tasks"]["t1"]["input_tokens"] == 0


def test_aggregate_receipt_costs_totals_and_averages():
    tasks = {
        "t1": {"input_tokens": 100, "output_tokens": 50, "cache_read_tokens": 20,
               "reasoning_tokens": 5, "tool_call_count": 2, "llm_time_s": 1.0,
               "tool_time_s": 0.5, "wall_time_s": 1.5},
        "t2": {"input_tokens": 200, "output_tokens": 100, "cache_read_tokens": 0,
               "reasoning_tokens": 0, "tool_call_count": 4, "llm_time_s": 2.0,
               "tool_time_s": 1.0, "wall_time_s": 3.0},
    }
    agg = _aggregate_receipt_costs(tasks)

    assert agg["total_input_tokens"] == 300
    assert agg["avg_input_tokens"] == 150
    assert agg["total_output_tokens"] == 150
    assert agg["total_tool_call_count"] == 6
    assert agg["avg_wall_time_s"] == 2.25


def test_aggregate_receipt_costs_all_none_when_no_receipt_data():
    tasks = {"t1": {"tokens": 50}}  # legacy shape, no receipt fields at all
    agg = _aggregate_receipt_costs(tasks)

    assert agg["total_input_tokens"] is None
    assert agg["avg_input_tokens"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/helpers/tests/test_compare_report.py -v -k receipt`
Expected: FAIL — `ImportError: cannot import name '_aggregate_receipt_costs'` and `KeyError: 'input_tokens'`.

- [ ] **Step 3: Extend `_parse_sdk_results`**

In `benchmarks/helpers/compare_report.py`, change the totals block at the top of `_parse_sdk_results`:
```python
    total_tokens = sum(r.get("total_tokens", 0) or 0 for r in results)
    total_cost = sum(r.get("total_cost", 0) or 0 for r in results)
    total_llm_calls = sum(r.get("total_llm_calls", 0) or 0 for r in results)
    total_cache_tokens = sum(r.get("total_cache_input_tokens", 0) or 0 for r in results)
```
to:
```python
    total_tokens = sum(r.get("total_tokens", 0) or 0 for r in results)
    total_cost = sum(r.get("total_cost", 0) or 0 for r in results)
    total_llm_calls = sum(r.get("total_llm_calls", 0) or 0 for r in results)
    total_cache_tokens = sum(r.get("total_cache_input_tokens", 0) or 0 for r in results)
    # Run Receipt fields (cuga-eval#95 / cuga-agent#467) — absent (0) for
    # results sourced from Langfuse or from benchmarks not yet opted in.
    total_input_tokens = sum(r.get("input_tokens", 0) or 0 for r in results)
    total_output_tokens = sum(r.get("output_tokens", 0) or 0 for r in results)
    total_receipt_cache_read = sum(r.get("cache_read_tokens", 0) or 0 for r in results)
    total_reasoning_tokens = sum(r.get("reasoning_tokens", 0) or 0 for r in results)
    total_tool_call_count = sum(r.get("tool_call_count", 0) or 0 for r in results)
    total_llm_time_s = sum(r.get("llm_time_s", 0) or 0 for r in results)
    total_tool_time_s = sum(r.get("tool_time_s", 0) or 0 for r in results)
    total_wall_time_s = sum(r.get("wall_time_s", 0) or 0 for r in results)
```

Change the per-task dict literal:
```python
        tasks[name] = {
            "success": r.get("success", False),
            "tokens": r.get("total_tokens", 0) or 0,
            "cost": r.get("total_cost", 0) or 0,
            "llm_calls": r.get("total_llm_calls", 0) or 0,
            "cache_tokens": r.get("total_cache_input_tokens", 0) or 0,
            "duration": dur,
            "steps": r.get("steps"),
```
to:
```python
        tasks[name] = {
            "success": r.get("success", False),
            "tokens": r.get("total_tokens", 0) or 0,
            "cost": r.get("total_cost", 0) or 0,
            "llm_calls": r.get("total_llm_calls", 0) or 0,
            "cache_tokens": r.get("total_cache_input_tokens", 0) or 0,
            "input_tokens": r.get("input_tokens", 0) or 0,
            "output_tokens": r.get("output_tokens", 0) or 0,
            "cache_read_tokens": r.get("cache_read_tokens", 0) or 0,
            "reasoning_tokens": r.get("reasoning_tokens", 0) or 0,
            "tool_call_count": r.get("tool_call_count", 0) or 0,
            "llm_time_s": r.get("llm_time_s", 0) or 0,
            "tool_time_s": r.get("tool_time_s", 0) or 0,
            "wall_time_s": r.get("wall_time_s", 0) or 0,
            "duration": dur,
            "steps": r.get("steps"),
```

Change the return dict:
```python
    return {
        "total": total,
        "passed": passed,
        "rate": passed / total if total else 0,
        "tokens": total_tokens,
        "cost": total_cost,
        "llm_calls": total_llm_calls,
        "cache_tokens": total_cache_tokens,
        "duration": total_duration if has_duration else None,
        "tasks": tasks,
    }
```
to:
```python
    return {
        "total": total,
        "passed": passed,
        "rate": passed / total if total else 0,
        "tokens": total_tokens,
        "cost": total_cost,
        "llm_calls": total_llm_calls,
        "cache_tokens": total_cache_tokens,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cache_read_tokens": total_receipt_cache_read,
        "reasoning_tokens": total_reasoning_tokens,
        "tool_call_count": total_tool_call_count,
        "llm_time_s": total_llm_time_s,
        "tool_time_s": total_tool_time_s,
        "wall_time_s": total_wall_time_s,
        "duration": total_duration if has_duration else None,
        "tasks": tasks,
    }
```

- [ ] **Step 4: Add `_aggregate_receipt_costs`**

In `benchmarks/helpers/compare_report.py`, insert immediately after `_aggregate_costs` (after its closing `}` — currently ending at line 546, right before `def _per_config_cost_stats`):

```python
_RECEIPT_COST_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "reasoning_tokens",
    "tool_call_count",
    "llm_time_s",
    "tool_time_s",
    "wall_time_s",
)


def _aggregate_receipt_costs(tasks: dict) -> dict:
    """Sum and average Run Receipt fields (cuga-eval#95 / cuga-agent#467)
    across a dict of task dicts (as produced by ``_parse_sdk_results``).

    Returns every value as None (not 0) when no task in *tasks* carries any
    receipt data, so callers can render "--" instead of a misleading zero for
    benchmarks/runs that never opted into ``advanced_features.run_receipt``.
    """
    has_any = any(t.get("input_tokens") or t.get("output_tokens") for t in tasks.values())
    if not has_any:
        result: dict = {}
        for field in _RECEIPT_COST_FIELDS:
            result[f"total_{field}"] = None
            result[f"avg_{field}"] = None
        return result

    n = len(tasks)
    result = {}
    for field in _RECEIPT_COST_FIELDS:
        total = sum(t.get(field, 0) or 0 for t in tasks.values())
        result[f"total_{field}"] = total
        result[f"avg_{field}"] = (total / n) if n else None
    return result
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/helpers/tests/test_compare_report.py -v`
Expected: PASS, including all pre-existing tests in the file (this task only adds fields — no existing key was removed or renamed).

- [ ] **Step 6: Commit**

```bash
git add benchmarks/helpers/compare_report.py benchmarks/helpers/tests/test_compare_report.py
git commit -m "feat(eval): parse and aggregate Run Receipt fields in compare_report"
```

---

### Task 7: "Run Receipt Breakdown" section in `generate_eval_report` (eval.sh's report.md)

**Files:**
- Modify: `benchmarks/helpers/compare_report.py:1333-1372` (function `generate_eval_report`, Summary section)
- Test: extend `benchmarks/helpers/tests/test_compare_report.py`

**Interfaces:**
- Consumes: `_aggregate_receipt_costs` from Task 6.
- Produces: no new function — `generate_eval_report`'s returned markdown/plain-text string gains a new section, present only when receipt data exists.

- [ ] **Step 1: Write the failing test**

Append to `benchmarks/helpers/tests/test_compare_report.py`:

```python
def _write_sdk_result_file(tmp_path, results):
    path = tmp_path / "results.json"
    path.write_text(
        json.dumps({"metrics": {"total_tasks": len(results), "passed": len(results)}, "results": results})
    )
    return str(path)


def test_generate_eval_report_includes_receipt_breakdown_when_present(tmp_path):
    results = [
        {
            "task_name": "t1",
            "success": True,
            "total_tokens": 150,
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 20,
            "reasoning_tokens": 5,
            "tool_call_count": 2,
            "llm_time_s": 1.5,
            "tool_time_s": 0.5,
            "wall_time_s": 2.5,
        }
    ]
    report = generate_eval_report(_write_sdk_result_file(tmp_path, results))

    assert "Run Receipt Breakdown" in report
    assert "Input Tokens" in report
    assert "100" in report


def test_generate_eval_report_omits_receipt_breakdown_when_absent(tmp_path):
    results = [{"task_name": "t1", "success": True, "total_tokens": 150}]
    report = generate_eval_report(_write_sdk_result_file(tmp_path, results))

    assert "Run Receipt Breakdown" not in report
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/helpers/tests/test_compare_report.py -v -k receipt_breakdown`
Expected: FAIL — `"Run Receipt Breakdown" in report` is `False` for the first test.

- [ ] **Step 3: Add the section to `generate_eval_report`**

In `benchmarks/helpers/compare_report.py`, change:
```python
    parsed = parse_result_file(result_file)
    rows, grouped = _bucket_m3_tasks(parsed["tasks"])
    cost = _aggregate_costs(parsed["tasks"])
```
to:
```python
    parsed = parse_result_file(result_file)
    rows, grouped = _bucket_m3_tasks(parsed["tasks"])
    cost = _aggregate_costs(parsed["tasks"])
    receipt_cost = _aggregate_receipt_costs(parsed["tasks"])
```

Then, right after the existing Summary block and its `_append_content_filter_summary` call — change:
```python
    _append_content_filter_summary(lines, parsed["tasks"], markdown=markdown)
    lines.append("")

    lines.append(h2("Per-Task Results"))
```
to:
```python
    _append_content_filter_summary(lines, parsed["tasks"], markdown=markdown)
    lines.append("")

    if receipt_cost["total_input_tokens"] is not None:
        lines.append(h2("Run Receipt Breakdown"))
        lines.append("")
        receipt_rows = [
            ("Input Tokens", "total_input_tokens", "avg_input_tokens", ","),
            ("Output Tokens", "total_output_tokens", "avg_output_tokens", ","),
            ("Cache Read Tokens", "total_cache_read_tokens", "avg_cache_read_tokens", ","),
            ("Reasoning Tokens", "total_reasoning_tokens", "avg_reasoning_tokens", ","),
            ("Tool Calls", "total_tool_call_count", "avg_tool_call_count", ","),
            ("LLM Time", "total_llm_time_s", "avg_llm_time_s", "s"),
            ("Tool Time", "total_tool_time_s", "avg_tool_time_s", "s"),
            ("Wall Time", "total_wall_time_s", "avg_wall_time_s", "s"),
        ]
        if markdown:
            for label, total_key, avg_key, fmt in receipt_rows:
                lines.append(
                    f"- **{label}**: {_fmt(receipt_cost[total_key], fmt)} total, "
                    f"{_fmt(receipt_cost[avg_key], fmt)} / task"
                )
        else:
            for label, total_key, avg_key, fmt in receipt_rows:
                lines.append(
                    f"  {label:<18} {_fmt(receipt_cost[total_key], fmt):>10} total   "
                    f"{_fmt(receipt_cost[avg_key], fmt):>10} / task"
                )
        lines.append("")

    lines.append(h2("Per-Task Results"))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/helpers/tests/test_compare_report.py -v`
Expected: PASS, all tests in the file (old and new).

- [ ] **Step 5: Commit**

```bash
git add benchmarks/helpers/compare_report.py benchmarks/helpers/tests/test_compare_report.py
git commit -m "feat(eval): render Run Receipt Breakdown section in generate_eval_report"
```

---

### Task 8: "Run Receipt Breakdown" section in the compare.sh multi-config report

**Files:**
- Modify: `benchmarks/helpers/compare_report.py:849-880` (`_render_compare_report_sections`, right after the existing "Cost Summary" section)
- Test: extend `benchmarks/helpers/tests/test_compare_report.py`

**Interfaces:**
- Consumes: the `input_tokens`/`output_tokens`/`cache_read_tokens`/`reasoning_tokens`/`tool_call_count`/`llm_time_s`/`tool_time_s`/`wall_time_s` top-level keys that Task 6 added to each `_parse_sdk_results()` return value (one such dict per run, stored as an entry of `model_data[config_key]`). This section averages *across runs* of one config (same basis as the existing "Cost Summary" section right above it), which is a different axis than `_aggregate_receipt_costs` (that one averages *across tasks within one run*) — so it reads `runs` directly rather than calling `_aggregate_receipt_costs`.
- Produces: no new function — `generate_report`'s returned string (via `_render_compare_report_sections`) gains a new section, present only when at least one run in `model_data` carries receipt data.

- [ ] **Step 1: Write the failing test**

Append to `benchmarks/helpers/tests/test_compare_report.py`:

```python
def test_generate_report_includes_receipt_breakdown_when_present(tmp_path):
    results = [
        {
            "task_name": "t1",
            "success": True,
            "total_tokens": 150,
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 20,
            "reasoning_tokens": 5,
            "tool_call_count": 2,
            "llm_time_s": 1.5,
            "tool_time_s": 0.5,
            "wall_time_s": 2.5,
        }
    ]
    result_file = _write_sdk_result_file(tmp_path, results)
    report = generate_report({"gpt-oss-120b": [result_file]})

    assert "Run Receipt Breakdown" in report
    assert "Input Tokens" in report


def test_generate_report_omits_receipt_breakdown_when_absent(tmp_path):
    results = [{"task_name": "t1", "success": True, "total_tokens": 150}]
    result_file = _write_sdk_result_file(tmp_path, results)
    report = generate_report({"gpt-oss-120b": [result_file]})

    assert "Run Receipt Breakdown" not in report
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/helpers/tests/test_compare_report.py -v -k "generate_report_includes_receipt or generate_report_omits_receipt"`
Expected: FAIL — first test's assertion fails (`"Run Receipt Breakdown" not in report`).

- [ ] **Step 3: Add the section to `_render_compare_report_sections`**

In `benchmarks/helpers/compare_report.py`, change:
```python
    lines.append(cost_header)
    lines.append("─" * len(cost_header))
    for config_key, runs in model_data.items():
        display = _format_config_label(config_key)
        n = len(runs)
        avg_tokens = sum(r["tokens"] for r in runs) / n
        avg_llm = sum(r["llm_calls"] for r in runs) / n
        avg_dur = _avg([r["duration"] for r in runs])
        avg_n_tasks = _avg([r["total"] for r in runs])
        per_task_tokens = (avg_tokens / avg_n_tasks) if avg_n_tasks else None
        per_task_llm = (avg_llm / avg_n_tasks) if avg_n_tasks else None
        per_task_dur = (avg_dur / avg_n_tasks) if (avg_dur is not None and avg_n_tasks) else None
        lines.append(
            f"{display:<28} {_fmt(avg_tokens):>10}  {_fmt(per_task_tokens):>10}  "
            f"{_fmt(avg_llm):>6}  {_fmt(per_task_llm):>9}  "
            f"{_fmt(avg_dur, 's'):>8}  {_fmt(per_task_dur, 's'):>9}"
        )
    if fence_close():
        lines.append(fence_close())
    lines.append("")

    # ---- 2b. Per-group breakdowns (only when result files carry the relevant
```
to:
```python
    lines.append(cost_header)
    lines.append("─" * len(cost_header))
    for config_key, runs in model_data.items():
        display = _format_config_label(config_key)
        n = len(runs)
        avg_tokens = sum(r["tokens"] for r in runs) / n
        avg_llm = sum(r["llm_calls"] for r in runs) / n
        avg_dur = _avg([r["duration"] for r in runs])
        avg_n_tasks = _avg([r["total"] for r in runs])
        per_task_tokens = (avg_tokens / avg_n_tasks) if avg_n_tasks else None
        per_task_llm = (avg_llm / avg_n_tasks) if avg_n_tasks else None
        per_task_dur = (avg_dur / avg_n_tasks) if (avg_dur is not None and avg_n_tasks) else None
        lines.append(
            f"{display:<28} {_fmt(avg_tokens):>10}  {_fmt(per_task_tokens):>10}  "
            f"{_fmt(avg_llm):>6}  {_fmt(per_task_llm):>9}  "
            f"{_fmt(avg_dur, 's'):>8}  {_fmt(per_task_dur, 's'):>9}"
        )
    if fence_close():
        lines.append(fence_close())
    lines.append("")

    # ---- 2a-2. Run Receipt Breakdown: only rendered when at least one run
    # carries Run Receipt data (cuga-eval#95 / cuga-agent#467) — bpo/oak/
    # appworld-default runs never will, so their reports are unchanged.
    any_receipt_data = any(
        (r.get("input_tokens") or r.get("output_tokens")) for runs in model_data.values() for r in runs
    )
    if any_receipt_data:
        lines.append(h2("Run Receipt Breakdown"))
        lines.append("")
        if fence_open():
            lines.append(fence_open())
        receipt_header = (
            f"{'Configuration':<28} {'In Tok':>9}  {'Out Tok':>9}  {'Cache Rd':>9}  "
            f"{'Reason':>8}  {'Tool#':>6}  {'LLM(s)':>8}  {'Tool(s)':>8}  {'Wall(s)':>8}"
        )
        lines.append(receipt_header)
        lines.append("─" * len(receipt_header))
        for config_key, runs in model_data.items():
            display = _format_config_label(config_key)
            n = len(runs)
            avg_in = sum(r.get("input_tokens", 0) or 0 for r in runs) / n
            avg_out = sum(r.get("output_tokens", 0) or 0 for r in runs) / n
            avg_cache = sum(r.get("cache_read_tokens", 0) or 0 for r in runs) / n
            avg_reason = sum(r.get("reasoning_tokens", 0) or 0 for r in runs) / n
            avg_tool_n = sum(r.get("tool_call_count", 0) or 0 for r in runs) / n
            avg_llm_t = sum(r.get("llm_time_s", 0) or 0 for r in runs) / n
            avg_tool_t = sum(r.get("tool_time_s", 0) or 0 for r in runs) / n
            avg_wall_t = sum(r.get("wall_time_s", 0) or 0 for r in runs) / n
            lines.append(
                f"{display:<28} {_fmt(avg_in):>9}  {_fmt(avg_out):>9}  {_fmt(avg_cache):>9}  "
                f"{_fmt(avg_reason):>8}  {_fmt(avg_tool_n):>6}  {_fmt(avg_llm_t, 's'):>8}  "
                f"{_fmt(avg_tool_t, 's'):>8}  {_fmt(avg_wall_t, 's'):>8}"
            )
        if fence_close():
            lines.append(fence_close())
        lines.append("")

    # ---- 2b. Per-group breakdowns (only when result files carry the relevant
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/helpers/tests/test_compare_report.py -v`
Expected: PASS, all tests in the file.

- [ ] **Step 5: Run the full helpers test suite once more, end to end**

Run: `cd /Users/harold/workspace/cuga-eval && uv run --no-sync pytest benchmarks/helpers/tests/ benchmarks/appworld/tests/ -v`
Expected: PASS across the board — this is the final integration check for the whole plan.

- [ ] **Step 6: Commit**

```bash
git add benchmarks/helpers/compare_report.py benchmarks/helpers/tests/test_compare_report.py
git commit -m "feat(eval): render Run Receipt Breakdown section in compare.sh's report"
```

---

## Post-plan manual smoke test (not automatable in this environment)

Once all 8 tasks are merged, a real run confirms the wiring end to end (the unit tests above mock `agent.invoke`, so they can't catch a cuga-agent-side surprise like the receipt shape changing again):

```bash
cd /Users/harold/workspace/cuga-eval
./benchmarks/m3/eval.sh --agent cuga --capability <one-capability> --domain <one-domain> --tasks 1
```

Check the produced `report.md` for a "Run Receipt Breakdown" section, and the results JSON for `token_source: "receipt"` on the one task. Repeat with `./benchmarks/appworld/eval.sh --sdk --agent cuga` for one task.
