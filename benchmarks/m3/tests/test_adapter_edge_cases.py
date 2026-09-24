"""Edge cases across scope, recording, config, and the combined answer path."""

from types import SimpleNamespace

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from benchmarks.m3.adapter.config import (
    ENV_PREFIX,
    PRESETS,
    AdapterConfig,
    TaskContext,
    resolve_adapter_config,
)
from benchmarks.m3.adapter.final_answer import make_final_answer_fn
from benchmarks.m3.adapter.guards import run_answer_pipeline
from benchmarks.m3.adapter.recording import RecordingScopedToolProvider
from benchmarks.m3.adapter.scope import resolve_scope

pytestmark = pytest.mark.sanity


# ------------------------------ scope ---------------------------------------


async def test_scope_mentions_retriever_but_matches_no_rule_shape():
    # contains "document retriever" but neither absolute nor conditional form
    assert await resolve_scope("Use document retrievers wisely and be nice.", "q") == "all"


async def test_scope_conditional_without_llm_assumes_match():
    policy = (
        "If a user's query pertains to Sports, which is/are about games, "
        "answer by only using document retrievers."
    )
    # llm_ainvoke=None -> conservative: restriction applies
    assert await resolve_scope(policy, "anything", None) == "retriever_only"


async def test_scope_empty_and_none_policy():
    assert await resolve_scope("", "q") == "all"
    assert await resolve_scope(None, "q") == "all"


# --------------------------- recording provider -----------------------------


class _Args(BaseModel):
    x: int = 0


async def test_recording_wraps_sync_only_tool():
    def sync_fn(x: int = 0):
        return f"sync:{x}"

    tool = StructuredTool(name="s", description="d", args_schema=_Args, func=sync_fn)

    class _P:
        initialized = True

        async def initialize(self):
            return None

        async def get_apps(self):
            return []

        async def get_tools(self, app_name):
            return [tool]

        async def get_all_tools(self):
            return [tool]

    provider = RecordingScopedToolProvider(_P())
    wrapped = (await provider.get_all_tools())[0]
    out = await wrapped.coroutine(x=3)
    assert out == "sync:3"
    assert provider.recorded_calls[0] == {"tool_name": "s", "arguments": {"x": 3}, "result": "sync:3"}
    assert callable(wrapped.func)  # sync shim: keeps func-level metadata reachable for the prompt


async def test_recording_get_tools_path_applies_scope_too():
    q = StructuredTool(name="query_d", description="d", args_schema=_Args, func=lambda x=0: "r")
    g = StructuredTool(name="get_d", description="d", args_schema=_Args, func=lambda x=0: "r")

    class _P:
        initialized = True

        async def initialize(self):
            return None

        async def get_apps(self):
            return ["a"]

        async def get_tools(self, app_name):
            return [q, g]

        async def get_all_tools(self):
            return [q, g]

    provider = RecordingScopedToolProvider(_P())
    provider.scope = "no_retriever"
    assert [t.name for t in await provider.get_tools("a")] == ["get_d"]


async def test_zero_tool_cap_blocks_first_call():
    tool = StructuredTool(name="t", description="d", args_schema=_Args, func=lambda x=0: "r")

    class _P:
        initialized = True

        async def initialize(self):
            return None

        async def get_apps(self):
            return []

        async def get_tools(self, app_name):
            return [tool]

        async def get_all_tools(self):
            return [tool]

    provider = RecordingScopedToolProvider(_P(), tool_cap=0)
    wrapped = (await provider.get_all_tools())[0]
    with pytest.raises(RuntimeError, match="Tool-call cap reached"):
        await wrapped.coroutine(x=1)


# ------------------------------- config -------------------------------------


def test_invalid_preset_via_env_raises_too():
    with pytest.raises(ValueError, match="valid presets"):
        resolve_adapter_config(None, env={f"{ENV_PREFIX}PRESET": "bogus"})


def test_capability_env_override():
    cfg = resolve_adapter_config("cap2", env={f"{ENV_PREFIX}CAPABILITY": "3"})
    assert cfg.capability == 3


def test_enabled_env_override_can_force_off_behaviors_kept():
    # turning `enabled` off via env disables the whole adapter path even for a preset
    cfg = resolve_adapter_config("cap2", env={f"{ENV_PREFIX}ENABLED": "0"})
    assert cfg.enabled is False and cfg.gates is True  # fields kept, master switch off


# --------------------- combined answer-path interplay -----------------------


async def test_cap2_pipeline_source_suffix_end_to_end():
    """The exact smoke-test failure shape: right value + Source suffix -> bare value."""
    cfg = PRESETS["cap2"]
    result = SimpleNamespace(
        answer="Charles. Source: hockey_get_players_by_position_no_shoot_catch.",
        error=None,
        tool_calls=[],
    )

    async def no_retry(correction):
        raise AssertionError("no retry expected")

    ok_call = [{"tool_name": "t", "arguments": {}, "result": "Charles"}]
    out = await run_answer_pipeline(no_retry, result, cfg, TaskContext(), ok_call)
    assert out == "Charles"


def test_final_answer_fn_canonicalize_after_markdown_wrap():
    fn = make_final_answer_fn(PRESETS["cap3"])  # canonicalize on
    assert fn("**[[42]]**") == "42"
    assert fn("Answer: [[Moana]]") == "Moana"


async def test_refusal_survives_whole_cap4_pipeline():
    cfg = PRESETS["cap4_v3wx"]
    result = SimpleNamespace(answer="I can not answer.", error=None, tool_calls=[])

    async def no_retry(correction):
        raise AssertionError("no retry expected")

    out = await run_answer_pipeline(no_retry, result, cfg, TaskContext(last_scope="retriever_only"), [])
    assert out == "I can not answer."  # refusal passes every guard untouched


async def test_empty_answer_with_gates_off_stays_empty():
    cfg = AdapterConfig(enabled=True, normalize=True, bluff_map=True)
    result = SimpleNamespace(answer="", error=None, tool_calls=[])

    async def no_retry(correction):
        raise AssertionError("gates off -> no retry")

    out = await run_answer_pipeline(no_retry, result, cfg, TaskContext(), [])
    assert out == ""
