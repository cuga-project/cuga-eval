"""TokenUsageCallback accumulates LangChain LLM usage per task."""

from types import SimpleNamespace

from benchmarks.helpers.token_usage import TokenUsageCallback


def _llm_result(*, llm_output=None, generations=None):
    return SimpleNamespace(llm_output=llm_output, generations=generations or [])


def test_token_usage_from_llm_output_usage():
    cb = TokenUsageCallback()
    cb.on_llm_end(_llm_result(llm_output={"usage": {"input_tokens": 10, "output_tokens": 4}}))
    assert cb.input_tokens == 10
    assert cb.output_tokens == 4
    assert cb.total_tokens == 14
    assert cb.llm_calls == 1


def test_token_usage_from_llm_output_token_usage():
    cb = TokenUsageCallback()
    cb.on_llm_end(
        _llm_result(llm_output={"token_usage": {"prompt_tokens": 20, "completion_tokens": 5}})
    )
    assert cb.input_tokens == 20
    assert cb.output_tokens == 5
    assert cb.total_tokens == 25
    assert cb.llm_calls == 1


def test_token_usage_from_usage_metadata():
    cb = TokenUsageCallback()
    message = SimpleNamespace(
        usage_metadata={"input_tokens": 100, "output_tokens": 25, "total_tokens": 125}
    )
    generation = SimpleNamespace(message=message)
    cb.on_llm_end(_llm_result(generations=[[generation]]))
    assert cb.input_tokens == 100
    assert cb.output_tokens == 25
    assert cb.total_tokens == 125
    assert cb.llm_calls == 1


def test_reset_clears_counts():
    cb = TokenUsageCallback()
    cb.on_llm_end(_llm_result(llm_output={"usage": {"input_tokens": 3, "output_tokens": 1}}))
    cb.reset()
    assert cb.input_tokens == 0
    assert cb.output_tokens == 0
    assert cb.total_tokens == 0
    assert cb.llm_calls == 0


def test_as_result_fields():
    cb = TokenUsageCallback()
    cb.on_llm_end(_llm_result(llm_output={"usage": {"input_tokens": 7, "output_tokens": 2}}))
    assert cb.as_result_fields() == {
        "input_tokens": 7,
        "output_tokens": 2,
        "total_tokens": 9,
        "total_llm_calls": 1,
    }


def test_cache_tokens_from_usage_metadata():
    cb = TokenUsageCallback()
    message = SimpleNamespace(
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 10,
            "input_tokens_details": {"cached_tokens": 40},
        }
    )
    generation = SimpleNamespace(message=message)
    cb.on_llm_end(_llm_result(generations=[[generation]]))
    assert cb.input_tokens == 100
    assert cb.output_tokens == 10
    assert cb.cache_input_tokens == 40
    assert cb.as_result_fields()["total_cache_input_tokens"] == 40


def test_invoke_config_with_token_callback():
    from benchmarks.helpers.token_usage import invoke_config_with_token_callback

    cb = TokenUsageCallback()
    cfg = invoke_config_with_token_callback(cb, {"callbacks": ["existing"]})
    assert cfg["callbacks"] == ["existing", cb]


def test_apply_token_metrics_from_callback():
    from benchmarks.helpers.token_usage import apply_token_metrics

    cb = TokenUsageCallback()
    cb.on_llm_end(_llm_result(llm_output={"usage": {"input_tokens": 12, "output_tokens": 3}}))
    result: dict = {}
    apply_token_metrics(result, cb)
    assert result["total_tokens"] == 15
    assert result["total_llm_calls"] == 1


def test_rollup_and_format_token_summary():
    from benchmarks.helpers.token_usage import format_token_summary, rollup_token_metrics

    rows = [
        {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "total_llm_calls": 2,
            "total_cache_input_tokens": 30,
        },
        {"input_tokens": 50, "output_tokens": 5, "total_tokens": 55, "total_llm_calls": 1},
    ]
    rollup = rollup_token_metrics(rows)
    assert rollup["total_input_tokens"] == 150
    assert rollup["total_output_tokens"] == 25
    assert rollup["total_cache_input_tokens"] == 30
    summary = format_token_summary(rows[0])
    assert "in=100" in summary
    assert "out=20" in summary
    assert "cache=30" in summary
