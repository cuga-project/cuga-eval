"""Token usage tracking callback for LangChain/LangGraph agents."""

from typing import Any, Optional


def _int_or_zero(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _nested_int(mapping: dict, *keys: str) -> int:
    current: object = mapping
    for key in keys:
        if not isinstance(current, dict):
            return 0
        current = current.get(key)
    return _int_or_zero(current)


def _cache_tokens_from_mapping(mapping: dict) -> int:
    if not mapping:
        return 0
    for value in (
        mapping.get("input_cache_read"),
        mapping.get("cache_read_input_tokens"),
        mapping.get("cached_tokens"),
        mapping.get("cache_creation_input_tokens"),
        _nested_int(mapping, "input_tokens_details", "cached_tokens"),
        _nested_int(mapping, "prompt_tokens_details", "cached_tokens"),
        _nested_int(mapping, "input_token_details", "cached_tokens"),
    ):
        cache = _int_or_zero(value)
        if cache:
            return cache
    return 0


def _add_usage_from_mapping(mapping: dict, callback: "TokenUsageCallback") -> bool:
    if not mapping:
        return False
    input_tokens = _int_or_zero(
        mapping.get("input_tokens")
        or mapping.get("prompt_tokens")
        or mapping.get("prompt_token_count")
    )
    output_tokens = _int_or_zero(
        mapping.get("output_tokens")
        or mapping.get("completion_tokens")
        or mapping.get("completion_token_count")
    )
    cache_tokens = _cache_tokens_from_mapping(mapping)
    if input_tokens or output_tokens or cache_tokens:
        callback.input_tokens += input_tokens
        callback.output_tokens += output_tokens
        callback.cache_input_tokens += cache_tokens
        return True
    return False


class TokenUsageCallback:
    """Resettable callback that accumulates LLM token usage per task.

    Attach once at agent creation via extra_callbacks; call reset() before each
    task so counts reflect only that task's invoke.
    """

    def __init__(self):
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cache_input_tokens: int = 0
        self.llm_calls: int = 0
        self._handler = None

    def _ensure_handler(self):
        if self._handler is not None:
            return self._handler
        from langchain_core.callbacks import BaseCallbackHandler

        outer = self

        class _Inner(BaseCallbackHandler):
            def on_llm_end(self, response, **kwargs):
                outer.llm_calls += 1
                counted = False

                if response.llm_output:
                    out = response.llm_output
                    counted = _add_usage_from_mapping(out.get("usage", {}) or {}, outer)
                    if not counted:
                        counted = _add_usage_from_mapping(out.get("token_usage", {}) or {}, outer)
                    if not counted:
                        cache_only = _cache_tokens_from_mapping(out.get("usage", {}) or {})
                        cache_only += _cache_tokens_from_mapping(out.get("token_usage", {}) or {})
                        if cache_only:
                            outer.cache_input_tokens += cache_only
                            counted = True

                if not counted and getattr(response, "generations", None):
                    for generation_list in response.generations:
                        for generation in generation_list:
                            message = getattr(generation, "message", None)
                            usage_metadata = getattr(message, "usage_metadata", None)
                            if isinstance(usage_metadata, dict) and _add_usage_from_mapping(
                                usage_metadata, outer
                            ):
                                counted = True

        self._handler = _Inner()
        return self._handler

    def __getattr__(self, name: str):
        return getattr(self._ensure_handler(), name)

    def reset(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_input_tokens = 0
        self.llm_calls = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_result_fields(self) -> dict[str, int]:
        fields = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "total_llm_calls": self.llm_calls,
        }
        if self.cache_input_tokens:
            fields["total_cache_input_tokens"] = self.cache_input_tokens
        return fields


def rollup_token_metrics(results: list[dict]) -> dict[str, float | int]:
    total = len(results) or 1
    total_input = sum(r.get("input_tokens", 0) or 0 for r in results)
    total_output = sum(r.get("output_tokens", 0) or 0 for r in results)
    total_tokens = sum(r.get("total_tokens", 0) or 0 for r in results)
    total_llm_calls = sum(r.get("total_llm_calls", 0) or 0 for r in results)
    total_cache = sum(r.get("total_cache_input_tokens", 0) or 0 for r in results)
    rollup: dict[str, float | int] = {
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_tokens,
        "avg_input_tokens_per_task": total_input / total,
        "avg_output_tokens_per_task": total_output / total,
        "avg_tokens_per_task": total_tokens / total,
        "total_llm_calls": total_llm_calls,
        "avg_llm_calls_per_task": total_llm_calls / total,
    }
    if total_cache:
        rollup["total_cache_input_tokens"] = total_cache
        rollup["avg_cache_input_tokens_per_task"] = total_cache / total
    return rollup


def invoke_config_with_token_callback(
    token_callback: "TokenUsageCallback",
    base: Optional[dict] = None,
) -> dict:
    cfg = dict(base or {})
    callbacks = list(cfg.get("callbacks") or [])
    if token_callback not in callbacks:
        callbacks.append(token_callback)
    cfg["callbacks"] = callbacks
    return cfg


def apply_token_metrics(
    result: dict,
    token_callback: "TokenUsageCallback",
    langfuse_metrics: Any = None,
) -> None:
    """Fill per-task token fields from callbacks; Langfuse overrides totals when present."""
    result.update(token_callback.as_result_fields())

    if not langfuse_metrics:
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


# Backward-compatible aliases used by AppWorld harness imports.
_invoke_config_with_token_callback = invoke_config_with_token_callback
_apply_token_metrics = apply_token_metrics


def format_token_summary(result: dict) -> str:
    parts = [
        f"in={result.get('input_tokens', 0):,}",
        f"out={result.get('output_tokens', 0):,}",
        f"total={result.get('total_tokens', 0):,}",
    ]
    cache = result.get("total_cache_input_tokens")
    if cache:
        parts.append(f"cache={cache:,}")
    llm_calls = result.get("total_llm_calls")
    if llm_calls:
        parts.append(f"calls={llm_calls}")
    return "tok[" + " ".join(parts) + "]"
