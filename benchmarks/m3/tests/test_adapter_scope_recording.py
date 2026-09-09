"""cap4 policy scoping + the recording/scoping tool provider."""

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from benchmarks.m3.adapter.recording import RecordingScopedToolProvider
from benchmarks.m3.adapter.scope import is_retriever, resolve_scope

pytestmark = pytest.mark.sanity


# ----------------------------- scope ---------------------------------------


def test_is_retriever():
    assert is_retriever("query_hockey")
    assert is_retriever("document_retriever")
    assert not is_retriever("get_players")


async def test_resolve_scope_absolute_rules():
    assert await resolve_scope("Do not use document retrievers for this task.", "q") == "no_retriever"
    assert (
        await resolve_scope("Use document retrievers only; do not use any other tools.", "q")
        == "retriever_only"
    )
    assert await resolve_scope("", "q") == "all"
    assert await resolve_scope("Answer politely.", "q") == "all"


async def test_resolve_scope_conditional_rule_classifies_topic():
    policy = (
        "If a user's query pertains to Sports, which is/are about games and athletes, "
        "make sure you try answering them by only using document retrievers."
    )

    async def yes(prompt):
        assert "Sports" in prompt
        return "YES"

    async def no(prompt):
        return "NO"

    assert await resolve_scope(policy, "who won the cup?", yes) == "retriever_only"
    assert await resolve_scope(policy, "list all books", no) == "all"

    forbid = (
        "If a user's query pertains to Sports, which is/are about games and athletes, "
        "do not use document retrievers."
    )
    assert await resolve_scope(forbid, "who won the cup?", yes) == "no_retriever"


async def test_resolve_scope_classifier_failure_assumes_match():
    policy = (
        "If a user's query pertains to Sports, which is/are about games, "
        "answer by only using document retrievers."
    )

    async def boom(prompt):
        raise RuntimeError("llm down")

    assert await resolve_scope(policy, "anything", boom) == "retriever_only"


# --------------------------- recording provider -----------------------------


class _Args(BaseModel):
    x: int = 0


def _tool(name: str, result="ok", fail=False):
    async def coro(x: int = 0):
        if fail:
            raise ValueError("boom")
        return f"{result}:{x}"

    return StructuredTool(
        name=name,
        description=f"{name} tool",
        args_schema=_Args,
        coroutine=coro,
        metadata={"app": "demo"},
    )


class _FakeProvider:
    def __init__(self, tools):
        self._tools = tools
        self.initialized = True

    async def initialize(self):
        return None

    async def get_apps(self):
        return ["demo"]

    async def get_tools(self, app_name):
        return list(self._tools)

    async def get_all_tools(self):
        return list(self._tools)


async def test_records_calls_in_submission_shape_and_preserves_metadata():
    provider = RecordingScopedToolProvider(_FakeProvider([_tool("get_a")]))
    tools = await provider.get_all_tools()
    assert tools[0].metadata == {"app": "demo"}  # model_copy keeps metadata
    out = await tools[0].coroutine(x=5)
    assert out == "ok:5"
    assert provider.recorded_calls == [{"tool_name": "get_a", "arguments": {"x": 5}, "result": "ok:5"}]


async def test_error_calls_record_error_and_reraise():
    provider = RecordingScopedToolProvider(_FakeProvider([_tool("get_a", fail=True)]))
    tools = await provider.get_all_tools()
    with pytest.raises(ValueError):
        await tools[0].coroutine(x=1)
    assert provider.recorded_calls[0]["result"].startswith("Error:")


async def test_tool_cap_raises_the_runaway_error():
    provider = RecordingScopedToolProvider(_FakeProvider([_tool("get_a")]), tool_cap=2)
    tools = await provider.get_all_tools()
    await tools[0].coroutine(x=1)
    await tools[0].coroutine(x=2)
    with pytest.raises(RuntimeError, match="Tool-call cap reached"):
        await tools[0].coroutine(x=3)
    assert len(provider.recorded_calls) == 2  # the capped call is not recorded


async def test_scope_filters_tools():
    provider = RecordingScopedToolProvider(_FakeProvider([_tool("get_a"), _tool("query_docs")]))
    provider.scope = "retriever_only"
    names = [t.name for t in await provider.get_all_tools()]
    assert names == ["query_docs"]
    provider.scope = "no_retriever"
    names = [t.name for t in await provider.get_all_tools()]
    assert names == ["get_a"]
    provider.scope = "all"
    assert len(await provider.get_all_tools()) == 2


async def test_result_truncated_to_4000():
    async def big(x: int = 0):
        return "z" * 9000

    tool = StructuredTool(name="big", description="d", args_schema=_Args, coroutine=big)
    provider = RecordingScopedToolProvider(_FakeProvider([tool]))
    tools = await provider.get_all_tools()
    await tools[0].coroutine(x=1)
    assert len(provider.recorded_calls[0]["result"]) == 4000
