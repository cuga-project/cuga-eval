"""Factory contract: off-preset passthrough; enabled-preset SDK kwargs (fake cuga.sdk)."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from benchmarks.m3.adapter.config import PRESETS, AdapterConfig

pytestmark = pytest.mark.sanity


class _FakeCugaAgent:
    """Signature mirror of cuga.sdk.CugaAgent (incl. the #621 final_answer kwarg)."""

    def __init__(
        self,
        tools=None,
        tool_provider=None,
        model=None,
        callbacks=None,
        special_instructions=None,
        shortlister=None,
        final_answer=None,
        **kwargs,
    ):
        self.tool_provider = tool_provider
        self.callbacks = callbacks
        self.special_instructions = special_instructions
        self.shortlister = shortlister
        self.final_answer = final_answer
        self.kwargs = kwargs


class _FakeCugaAgentNoFinalAnswer:
    """Pre-#621 signature: no final_answer kwarg."""

    def __init__(self, tools=None, tool_provider=None, special_instructions=None, shortlister=None, **kwargs):
        self.tool_provider = tool_provider
        self.special_instructions = special_instructions
        self.shortlister = shortlister
        self.kwargs = kwargs


class _FakeToolGuard:
    """Shape mirror of cuga's ToolGuardingToolProvider: a `base_provider` slot + cache invalidation."""

    def __init__(self, base_provider):
        self.base_provider = base_provider
        self.invalidations = 0

    def invalidate_toolguard_runtime(self):
        self.invalidations += 1


@pytest.fixture
def fake_cuga(monkeypatch):
    """Install a fake cuga.sdk so agent.py's lazy imports resolve without CUGA."""

    def _install(agent_cls):
        sdk = ModuleType("cuga.sdk")
        sdk.CugaAgent = agent_cls
        # Real layout: Shortlister lives in the shortlister package (cuga.sdk
        # only names it under TYPE_CHECKING) — mirror that path here.
        shortlister_mod = ModuleType("cuga.backend.cuga_graph.nodes.cuga_lite.shortlister")
        shortlister_mod.Shortlister = lambda **kw: SimpleNamespace(**kw)
        cuga = ModuleType("cuga")
        cuga.sdk = sdk
        monkeypatch.setitem(sys.modules, "cuga", cuga)
        monkeypatch.setitem(sys.modules, "cuga.sdk", sdk)
        for name in (
            "cuga.backend",
            "cuga.backend.cuga_graph",
            "cuga.backend.cuga_graph.nodes",
            "cuga.backend.cuga_graph.nodes.cuga_lite",
        ):
            monkeypatch.setitem(sys.modules, name, ModuleType(name))
        monkeypatch.setitem(
            sys.modules, "cuga.backend.cuga_graph.nodes.cuga_lite.shortlister", shortlister_mod
        )
        # ToolGuard decorator class, so wrap_existing_agent can nest inside it.
        toolguard_mod = ModuleType("cuga.backend.cuga_graph.nodes.cuga_lite.providers.toolguard")
        toolguard_mod.ToolGuardingToolProvider = _FakeToolGuard
        monkeypatch.setitem(
            sys.modules,
            "cuga.backend.cuga_graph.nodes.cuga_lite.providers",
            ModuleType("cuga.backend.cuga_graph.nodes.cuga_lite.providers"),
        )
        monkeypatch.setitem(sys.modules, toolguard_mod.__name__, toolguard_mod)
        return sdk

    return _install


def test_off_preset_returns_plain_agent_with_todays_kwargs(fake_cuga):
    fake_cuga(_FakeCugaAgent)
    from benchmarks.m3.adapter.agent import build_m3_agent

    provider = object()
    agent = build_m3_agent(
        tool_provider=provider,
        special_instructions="rider",
        config=AdapterConfig(),  # off
        auto_load_policies=False,
        filesystem_sync=False,
    )
    assert type(agent) is _FakeCugaAgent  # NOT wrapped
    assert agent.tool_provider is provider  # NOT a recording wrapper
    assert agent.special_instructions == "rider"
    assert agent.kwargs == {"auto_load_policies": False, "filesystem_sync": False}
    assert agent.shortlister is None and agent.final_answer is None


def test_enabled_preset_wraps_provider_and_sets_sdk_kwargs(fake_cuga):
    fake_cuga(_FakeCugaAgent)
    from benchmarks.m3.adapter.agent import VakraAdapterAgent, build_m3_agent
    from benchmarks.m3.adapter.recording import RecordingScopedToolProvider
    from benchmarks.m3.adapter.shortlist import PINNED_STRATEGY_PATH

    provider = object()
    agent = build_m3_agent(tool_provider=provider, special_instructions="rider", config=PRESETS["cap4_v3wx"])
    assert isinstance(agent, VakraAdapterAgent)
    inner = agent._inner
    assert isinstance(inner.tool_provider, RecordingScopedToolProvider)
    assert inner.tool_provider.base_provider is provider
    assert inner.tool_provider.tool_cap == 16
    assert inner.special_instructions == "rider"  # constructor rider preserved
    assert callable(inner.final_answer)  # #621 path used
    assert inner.shortlister.strategy == PINNED_STRATEGY_PATH
    assert inner.shortlister.top_k == 40 and inner.shortlister.threshold == 40
    assert inner.shortlister.min_score == 0.0 and inner.shortlister.query_weight == 1.0


def test_caps123_shortlister_uses_plain_embedding_strategy(fake_cuga):
    fake_cuga(_FakeCugaAgent)
    from benchmarks.m3.adapter.agent import build_m3_agent

    agent = build_m3_agent(tool_provider=object(), config=PRESETS["cap2"])
    inner = agent._inner
    assert inner.shortlister.strategy == "embedding"
    assert inner.shortlister.top_k == 128
    assert "all-MiniLM-L6-v2" in inner.shortlister.embedding_model


def test_pre_621_sdk_degrades_to_post_invoke_final_answer(fake_cuga):
    fake_cuga(_FakeCugaAgentNoFinalAnswer)
    from benchmarks.m3.adapter.agent import build_m3_agent

    agent = build_m3_agent(tool_provider=object(), config=PRESETS["cap3"])
    assert agent._final_answer_installed is False  # fallback armed
    assert "final_answer" not in agent._inner.kwargs


def test_wrap_existing_agent_off_is_identity_and_on_wraps_provider(fake_cuga):
    fake_cuga(_FakeCugaAgent)
    from benchmarks.m3.adapter.agent import VakraAdapterAgent, wrap_existing_agent
    from benchmarks.m3.adapter.recording import RecordingScopedToolProvider

    plain = _FakeCugaAgent(tool_provider=object())
    assert wrap_existing_agent(plain, AdapterConfig()) is plain

    wrapped = wrap_existing_agent(plain, PRESETS["cap4_v3wx"])
    assert isinstance(wrapped, VakraAdapterAgent)
    assert isinstance(plain.tool_provider, RecordingScopedToolProvider)
    assert wrapped._final_answer_installed is False  # post-invoke fallback path
    # delegation: unknown attributes reach the inner agent
    plain.policies = "sentinel"
    assert wrapped.policies == "sentinel"


def test_set_task_context_resets_state(fake_cuga):
    fake_cuga(_FakeCugaAgent)
    from benchmarks.m3.adapter.agent import build_m3_agent

    agent = build_m3_agent(tool_provider=object(), config=PRESETS["cap4_v3wx"])
    agent.set_task_context(additional_instructions="P1", domain="hockey")
    assert agent._ctx.additional_instructions == "P1"
    agent.set_task_context(domain="olympics")
    assert agent._ctx.additional_instructions == ""  # fresh context per task
    assert agent._ctx.domain == "olympics"


def test_wrap_existing_agent_nests_inside_toolguard(fake_cuga):
    """CugaAgent installs ToolGuard around the caller's provider; the recorder goes inside it
    so ToolGuard stays outermost (positional-arg normalization, policy storage attach)."""
    fake_cuga(_FakeCugaAgent)
    from benchmarks.m3.adapter.agent import wrap_existing_agent
    from benchmarks.m3.adapter.recording import RecordingScopedToolProvider

    raw = object()
    guard = _FakeToolGuard(raw)
    plain = _FakeCugaAgent(tool_provider=guard)
    wrapped = wrap_existing_agent(plain, PRESETS["cap4_v3wx"])
    assert plain.tool_provider is guard  # ToolGuard still outermost
    assert isinstance(guard.base_provider, RecordingScopedToolProvider)
    assert guard.base_provider.base_provider is raw  # recorder sits right above the raw provider
    assert guard.base_provider.tool_cap == 16
    assert wrapped._provider is guard.base_provider  # the guards read the same sink
    assert guard.invalidations == 1  # guarded-tool cache dropped (keyed by raw tool id)
