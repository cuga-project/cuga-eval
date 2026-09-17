"""Unit tests for the LLM preflight check that guards `--sdk` runs.

Lives next to test_require_tools_guard.py: both test guards in
benchmarks/helpers/sdk_eval_helpers.py that abort a run before it can burn hours.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from benchmarks.helpers.sdk_eval_helpers import preflight_llm

pytestmark = pytest.mark.sanity


class _FakeModel:
    """Stands in for the ChatOpenAI instance LLMManager hands back."""

    model_name = "aws/gpt-oss-120b"
    openai_api_base = "https://gateway.example"
    request_timeout = 0.2

    def __init__(self, reply=None, exc=None, hang=False):
        self._reply, self._exc, self._hang = reply, exc, hang

    async def ainvoke(self, messages):
        if self._hang:
            await asyncio.sleep(60)
        if self._exc:
            raise self._exc
        return SimpleNamespace(content=self._reply)


def _patched(model):
    manager = SimpleNamespace(get_model=lambda _cfg: model)
    return patch.dict(
        "sys.modules",
        {
            "cuga.backend.llm.models": SimpleNamespace(LLMManager=lambda: manager),
            "cuga.config": SimpleNamespace(
                settings=SimpleNamespace(agent=SimpleNamespace(code=SimpleNamespace(model={})))
            ),
        },
    )


def test_live_endpoint_passes():
    with _patched(_FakeModel(reply="Hello! How can I help?")):
        asyncio.run(preflight_llm())  # no raise


def test_hanging_endpoint_fails_fast_with_vpn_hint():
    """The hang must be bounded by request_timeout — this test returning at all proves it."""
    with _patched(_FakeModel(hang=True)):
        with pytest.raises(RuntimeError, match="VPN not connected"):
            asyncio.run(preflight_llm())


def test_error_response_surfaces_the_provider_message():
    with _patched(_FakeModel(exc=ValueError("model not found"))):
        with pytest.raises(RuntimeError, match="ValueError: model not found"):
            asyncio.run(preflight_llm())


def test_empty_response_fails_the_preflight():
    """A 200 with no content is a gateway that is up but does not serve the model."""
    with _patched(_FakeModel(reply="")):
        with pytest.raises(RuntimeError, match="empty response"):
            asyncio.run(preflight_llm())


@pytest.mark.asyncio
async def test_setup_preflights_before_building_the_agent():
    """The guard must be wired into setup() and run before the expensive agent build."""
    # eval_appworld_sdk imports `appworld` at module level; CI does not install it.
    pytest.importorskip(
        "appworld",
        reason="AppWorld package not installed; run ./setup_appworld.sh to enable this test.",
    )
    from benchmarks.appworld import eval_appworld_sdk as mod

    calls = []

    async def _preflight():
        calls.append("preflight")

    async def _build_agent(**_kwargs):
        calls.append("agent")
        return MagicMock(), None

    with (
        patch.object(mod, "preflight_llm", new=AsyncMock(side_effect=_preflight)),
        patch.object(mod, "setup_agent_with_tools", new=AsyncMock(side_effect=_build_agent)),
    ):
        await mod.AppWorldSdkEvaluator(dataset_name="test_normal").setup()

    assert calls == ["preflight", "agent"]
