"""Token metric helpers for AppWorld eval paths (no appworld package dependency)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from benchmarks.helpers.token_usage import TokenUsageCallback


def invoke_config_with_token_callback(
    token_callback: TokenUsageCallback,
    base: Optional[dict] = None,
) -> dict:
    cfg = dict(base or {})
    callbacks = list(cfg.get("callbacks") or [])
    if token_callback not in callbacks:
        callbacks.append(token_callback)
    cfg["callbacks"] = callbacks
    return cfg


def apply_token_metrics(
    result: Dict[str, Any],
    token_callback: TokenUsageCallback,
    langfuse_metrics: Any = None,
    receipt_metrics: Optional[Dict[str, Any]] = None,
) -> None:
    """Fill the token fields on ``result``, least to most authoritative.

    Three sources can report the same numbers and they do not always agree:

    1. ``token_callback`` — counted locally by this process. Always present, so
       it is the base: a task never ends up with empty token fields.
    2. ``langfuse_metrics`` — fetched from Langfuse, when a handler is attached.
       Overrides the local count field by field, only where it has a value.
    3. ``receipt_metrics`` — the SDK's own ``RunReceipt``
       (``advanced_features.run_receipt``). The agent's own accounting, so it
       wins outright over both (cuga-eval#95 / cuga-agent#467).
    """
    result.update(token_callback.as_result_fields())

    if not langfuse_metrics:
        if receipt_metrics:
            result.update(receipt_metrics)
        return

    if getattr(langfuse_metrics, "total_tokens", 0):
        result["total_tokens"] = langfuse_metrics.total_tokens
    if getattr(langfuse_metrics, "total_llm_calls", 0):
        result["total_llm_calls"] = langfuse_metrics.total_llm_calls
    if getattr(langfuse_metrics, "total_cost", None) is not None:
        result["total_cost"] = langfuse_metrics.total_cost
    if getattr(langfuse_metrics, "full_execution_time", None) is not None:
        result["full_execution_time"] = langfuse_metrics.full_execution_time
    cache_tokens = getattr(langfuse_metrics, "total_cache_input_tokens", 0) or 0
    if cache_tokens:
        result["total_cache_input_tokens"] = cache_tokens
    if getattr(langfuse_metrics, "generation_timings", None):
        result["generation_timings"] = langfuse_metrics.generation_timings
    if getattr(langfuse_metrics, "llm_call_details", None):
        result["llm_call_details"] = langfuse_metrics.llm_call_details
    if getattr(langfuse_metrics, "node_timings", None):
        result["node_timings"] = langfuse_metrics.node_timings

    if receipt_metrics:
        result.update(receipt_metrics)
