"""Adapter integration against the real cuga SDK — no LLM call, no containers.

The sanity tests mock ``cuga.sdk``; these build a real ``CugaAgent`` (fake chat
model) and check the seams the adapter relies on: the provider chain the
constructor builds, ToolGuard's metadata copy and guarded-tool cache, prompt-doc
parity for wrapped tools, and positional-arg normalization through ToolGuard.
"""

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

pytest.importorskip("cuga.sdk", reason="needs the ../cuga-agent sibling checkout")

from cuga.backend.cuga_graph.nodes.cuga_lite.prompt_utils import PromptUtils
from cuga.backend.cuga_graph.nodes.cuga_lite.providers.langchain import DirectLangChainToolsProvider
from cuga.backend.cuga_graph.nodes.cuga_lite.providers.toolguard import (
    ToolGuardingToolProvider,
    configure_toolguard_provider,
)
from cuga.sdk import CugaAgent

from benchmarks.m3.adapter import PRESETS, AdapterConfig, build_m3_agent, wrap_existing_agent
from benchmarks.m3.adapter.agent import VakraAdapterAgent
from benchmarks.m3.adapter.recording import RecordingScopedToolProvider

pytestmark = pytest.mark.regression


class _Args(BaseModel):
    x: int = 0
    y: int = 0


def _raw_tool() -> StructuredTool:
    async def get_xy(x: int = 0, y: int = 0) -> str:
        return f"ok:{x}:{y}"

    def get_xy_sync(x: int = 0, y: int = 0) -> str:
        return f"ok:{x}:{y}"

    tool = StructuredTool(
        name="get_xy", description="Get xy", args_schema=_Args, coroutine=get_xy, func=get_xy_sync
    )
    # What the registry provider hangs on real tools (registry.py); prompt rendering reads it back off func.
    for fn in (tool.func, tool.coroutine):
        fn._param_constraints = {"x": ["x >= 0"]}
        fn._response_schemas = {"success": {"type": "string"}}
        fn._operation_id = "op-xy"
    return tool


def _agent_kwargs() -> dict:
    return {
        "model": FakeListChatModel(responses=["unused"]),
        "auto_load_policies": False,
        "filesystem_sync": False,
    }


def _build(config: AdapterConfig):
    raw = _raw_tool()
    agent = build_m3_agent(
        tool_provider=DirectLangChainToolsProvider(tools=[raw]), config=config, **_agent_kwargs()
    )
    return agent, raw


async def _guard(agent: VakraAdapterAgent) -> ToolGuardingToolProvider:
    guard = agent._inner.tool_provider
    guard.enabled = True  # independent of settings.policy.enabled in the test process
    await agent._inner.initialize()  # the real init path runs through the recorder
    return guard


def _without_callables(payload: dict) -> dict:
    return {
        k: v for k, v in payload.items() if k not in ("func", "coroutine")
    }  # differ by identity, inherently


def test_enabled_preset_keeps_toolguard_outermost_and_off_is_a_plain_agent():
    agent, _ = _build(PRESETS["cap2"])
    assert isinstance(agent, VakraAdapterAgent)
    guard = agent._inner.tool_provider
    assert isinstance(guard, ToolGuardingToolProvider)  # CugaAgent's decorator stays outermost
    assert isinstance(guard.base_provider, RecordingScopedToolProvider)  # recorder right inside it
    assert isinstance(guard.base_provider.base_provider, DirectLangChainToolsProvider)
    assert agent._provider is guard.base_provider

    off, _ = _build(AdapterConfig())
    assert type(off) is CugaAgent  # not wrapped at all
    assert isinstance(off.tool_provider, ToolGuardingToolProvider)
    assert isinstance(off.tool_provider.base_provider, DirectLangChainToolsProvider)


async def test_guarded_tools_render_the_same_docs_as_the_raw_tool():
    """ToolGuard copies its metadata from tool.func; the recorder's func shim has to carry it."""
    agent, raw = _build(PRESETS["cap2"])
    guard = await _guard(agent)
    guarded = (await guard.get_all_tools())[0]
    assert guarded.func._param_constraints == {"x": ["x >= 0"]}
    assert guarded.func._response_schemas == {"success": {"type": "string"}}
    assert guarded.func._operation_id == "op-xy"
    assert PromptUtils.get_tool_docs(guarded) == PromptUtils.get_tool_docs(raw)
    payload_raw = PromptUtils._build_shortlister_payload([raw], [])[0]["get_xy"]
    payload_guarded = PromptUtils._build_shortlister_payload([guarded], [])[0]["get_xy"]
    assert _without_callables(payload_guarded) == _without_callables(payload_raw)


async def test_toolguard_cache_does_not_grow_across_fetches():
    agent, _ = _build(PRESETS["cap2"])
    guard = await _guard(agent)
    await guard.get_all_tools()
    assert len(guard._guarded_tools_cache) == 1
    for _ in range(3):
        await guard.get_all_tools()
    await guard.get_tools(guard.base_provider.base_provider.app_name)
    assert len(guard._guarded_tools_cache) == 1  # memoized recorder => stable raw-tool ids => cache hits


async def test_positional_and_dict_calls_through_toolguard_are_recorded():
    agent, _ = _build(PRESETS["cap2"])
    guard = await _guard(agent)
    guarded = (await guard.get_all_tools())[0]
    assert await guarded.coroutine(1, 2) == "ok:1:2"
    assert await guarded.coroutine({"x": 3, "y": 4}) == "ok:3:4"
    assert await guarded.coroutine(x=5, y=6) == "ok:5:6"
    assert [c["arguments"] for c in agent._provider.recorded_calls] == [
        {"x": 1, "y": 2},
        {"x": 3, "y": 4},
        {"x": 5, "y": 6},
    ]


def test_wrap_existing_agent_nests_inside_the_real_toolguard():
    plain = CugaAgent(tool_provider=DirectLangChainToolsProvider(tools=[_raw_tool()]), **_agent_kwargs())
    outer = plain.tool_provider
    wrapped = wrap_existing_agent(plain, PRESETS["cap4_v3wx"])
    assert plain.tool_provider is outer  # ToolGuard still outermost
    assert isinstance(outer.base_provider, RecordingScopedToolProvider)
    assert isinstance(outer.base_provider.base_provider, DirectLangChainToolsProvider)
    assert wrapped._provider is outer.base_provider
    sentinel = object()
    configure_toolguard_provider(
        plain.tool_provider, policy_storage=sentinel
    )  # what the SDK's policy manager does
    assert outer.policy_storage is sentinel
