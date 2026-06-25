import pytest

from benchmarks.bpo.llm_judge import get_llm_judge


@pytest.fixture(autouse=True)
def clean_judge_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "API_KEY",
        "LLM_JUDGE_API_KEY",
        "LLM_JUDGE_BASE_URL",
        "LLM_JUDGE_MODEL",
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "QWEN_API_KEY",
        "QWEN_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_qwen_judge_is_default_llm_provider_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_JUDGE_MODEL", raising=False)

    judge = get_llm_judge("qwen")

    assert judge.name == "qwen:qwen3.7-max"


def test_openrouter_qwen_slug_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("LLM_JUDGE_MODEL", raising=False)
    monkeypatch.delenv("LLM_JUDGE_BASE_URL", raising=False)

    judge = get_llm_judge("qwen")

    assert judge.name == "qwen:qwen/qwen3.7-max"


def test_openrouter_qwen_route_ignores_qwen_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "qwen-key")
    monkeypatch.setenv("QWEN_BASE_URL", "https://dashscope.example.test/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("LLM_JUDGE_MODEL", "qwen/qwen3.7-max")
    monkeypatch.delenv("LLM_JUDGE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)

    judge = get_llm_judge("qwen")

    assert judge.name == "qwen:qwen/qwen3.7-max"
    assert judge._api_key == "openrouter-key"
    assert judge._base_url == "https://openrouter.ai/api/v1"


def test_generic_api_key_does_not_configure_qwen_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_JUDGE_API_KEY", raising=False)
    monkeypatch.setenv("API_KEY", "generic-provider-key")

    with pytest.raises(ValueError, match="QWEN_API_KEY"):
        get_llm_judge("qwen")


def test_groq_provider_is_rejected_for_task_judging() -> None:
    with pytest.raises(ValueError, match="qwen"):
        get_llm_judge("groq")
