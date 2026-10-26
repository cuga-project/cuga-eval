"""cap4 policy scoping + the recording/scoping tool provider."""

import asyncio

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from benchmarks.m3.adapter.recording import (
    RecordingScopedToolProvider,
    is_api_timeout,
    is_empty_handle,
    is_empty_or_zero,
)
from benchmarks.m3.adapter.scope import is_retriever, resolve_scope

pytestmark = pytest.mark.sanity


# ----------------------------- scope ---------------------------------------


def test_is_retriever():
    assert is_retriever("query_hockey")
    assert is_retriever("document_retriever")
    assert not is_retriever("get_players")


def test_is_retriever_sees_through_the_registry_app_prefix():
    """cuga's registry names MCP tools `<app>_<tool>`: the cap4 retriever `query_hockey` arrives
    as `hockey_query_hockey`. Missing it would make a retriever_only policy scope strip every tool."""
    assert is_retriever("hockey_query_hockey")
    assert is_retriever("capability_4_multiturn_query_hockey")
    assert not is_retriever("hockey_get_players_by_position")
    assert not is_retriever("professional_basketball_get_players_award_year")


async def test_scope_keeps_registry_prefixed_retrievers():
    provider = RecordingScopedToolProvider(
        _FakeProvider([_tool("hockey_get_players"), _tool("hockey_query_hockey")])
    )
    provider.scope = "retriever_only"
    assert [t.name for t in await provider.get_all_tools()] == ["hockey_query_hockey"]
    provider.scope = "no_retriever"
    assert [t.name for t in await provider.get_all_tools()] == ["hockey_get_players"]


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


# ------------------ fidelity: args, metadata, sync shim, memo ------------------


class _Args2(BaseModel):
    x: int = 0
    y: int = 0


def _tool2(name="get_xy"):
    async def coro(x: int = 0, y: int = 0):
        return f"ok:{x}:{y}"

    return StructuredTool(name=name, description="d", args_schema=_Args2, coroutine=coro)


async def test_positional_and_dict_bag_calls_resolve_like_raw_tools():
    """The sandbox calls tool.coroutine with whatever the model wrote; mirror cuga's merge."""
    provider = RecordingScopedToolProvider(_FakeProvider([_tool2()]))
    w = (await provider.get_all_tools())[0]
    assert await w.coroutine(1, 2) == "ok:1:2"  # positional -> schema order
    assert await w.coroutine({"x": 3, "y": 4}) == "ok:3:4"  # single dict of known keys = kwargs bag
    assert await w.coroutine(5, y=6) == "ok:5:6"  # mixed
    assert [c["arguments"] for c in provider.recorded_calls] == [
        {"x": 1, "y": 2},
        {"x": 3, "y": 4},
        {"x": 5, "y": 6},
    ]


async def test_dict_with_no_known_keys_is_nested_payload_for_first_param():
    provider = RecordingScopedToolProvider(_FakeProvider([_tool("get_a")]))
    w = (await provider.get_all_tools())[0]
    assert await w.coroutine({"z": 9}) == "ok:{'z': 9}"
    assert provider.recorded_calls[0]["arguments"] == {"x": {"z": 9}}


async def test_extra_positionals_reach_the_raw_tool_as_argN_and_fail_there():
    provider = RecordingScopedToolProvider(_FakeProvider([_tool2()]))
    w = (await provider.get_all_tools())[0]
    with pytest.raises(TypeError):  # the raw tool rejects arg2, exactly as it would unwrapped
        await w.coroutine(1, 2, 3)
    assert provider.recorded_calls[0]["arguments"] == {"x": 1, "y": 2, "arg2": 3}
    assert provider.recorded_calls[0]["result"].startswith("Error:")


async def test_function_metadata_survives_on_both_entry_points():
    """Prompt rendering reads _response_schemas/_param_constraints off tool.func;
    ToolGuard copies them from there; _cuga_tracked stops CUGA double-recording."""
    raw = _tool("get_a")
    raw.coroutine._param_constraints = {"x": {"minimum": 0}}
    raw.coroutine._response_schemas = {"success": {"type": "object"}}
    raw.coroutine._cuga_tracked = True
    raw._operation_id = "op-1"  # the registry sets this on func, coroutine and the tool itself
    provider = RecordingScopedToolProvider(_FakeProvider([raw]))
    w = (await provider.get_all_tools())[0]
    assert callable(w.func) and w.func.__name__ == "get_a" and w.coroutine.__name__ == "get_a"
    for entry in (w.func, w.coroutine):
        assert entry._param_constraints == {"x": {"minimum": 0}}
        assert entry._response_schemas == {"success": {"type": "object"}}
        assert entry._cuga_tracked is True
        assert entry._operation_id == "op-1"


def test_sync_shim_works_outside_an_event_loop():
    provider = RecordingScopedToolProvider(_FakeProvider([_tool("get_a")]))
    w = asyncio.run(provider.get_all_tools())[0]
    assert w.func(x=4) == "ok:4"
    assert provider.recorded_calls == [{"tool_name": "get_a", "arguments": {"x": 4}, "result": "ok:4"}]


async def test_sync_shim_refuses_to_block_a_running_loop():
    provider = RecordingScopedToolProvider(_FakeProvider([_tool("get_a")]))
    w = (await provider.get_all_tools())[0]
    with pytest.raises(RuntimeError, match="synchronously"):
        w.func(x=1)
    assert provider.recorded_calls == []


async def test_wrapped_tools_are_memoized_per_raw_tool():
    """Stable wrapper identity per raw tool: ToolGuard caches by id(raw tool), so a
    fresh object per fetch would miss that cache on every one of CUGA's per-invoke fetches."""
    raw = _tool("get_a")
    base = _FakeProvider([raw])
    provider = RecordingScopedToolProvider(base)
    first = (await provider.get_all_tools())[0]
    assert (await provider.get_all_tools())[0] is first
    assert (await provider.get_tools("demo"))[0] is first  # both fetch paths share the memo
    base._tools = [_tool("get_a")]  # provider hands out a new raw object under the same name
    renewed = (await provider.get_all_tools())[0]
    assert renewed is not first
    provider.base_provider = _FakeProvider([raw])  # cap1 re-list swaps the provider: memo dropped
    swapped = (await provider.get_all_tools())[0]
    assert swapped is not first and swapped is not renewed
    assert await swapped.coroutine(x=1) == "ok:1"  # and still records through the new wrapper
    assert provider.recorded_calls[-1]["tool_name"] == "get_a"


# ----------------------------- tool-server timeouts ---------------------------


def _scripted_tool(name, replies):
    """A tool that returns (or raises) the scripted replies in order; ``calls`` counts the calls."""
    calls = []

    async def coro(x: int = 0):
        reply = replies[min(len(calls), len(replies) - 1)]
        calls.append(x)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    return StructuredTool(name=name, description=name, args_schema=_Args, coroutine=coro), calls


def test_is_api_timeout():
    assert is_api_timeout("Error calling API: ")
    assert is_api_timeout("Error calling API:")
    assert is_api_timeout("Error calling API: timed out")
    assert is_api_timeout("Error calling API: ReadTimeout")
    assert not is_api_timeout("Error calling API: Client error '404 Not Found' for url 'http://x'")
    assert not is_api_timeout("Error: bad arguments")
    assert not is_api_timeout("note: Error calling API: ")
    assert not is_api_timeout({"error": "Error calling API: "})
    assert not is_api_timeout("[[42]]")


async def test_a_tool_server_timeout_is_retried_until_the_api_answers():
    """A cold-database API times out on the tool server (30 s) and answers on a repeat:
    the agent sees the rows, and the call is recorded once with them."""
    tool, calls = _scripted_tool("get_a", ["Error calling API: ", "Error calling API: ", "[[90895834]]"])
    provider = RecordingScopedToolProvider(_FakeProvider([tool]))
    wrapped = (await provider.get_all_tools())[0]
    assert await wrapped.coroutine(x=4) == "[[90895834]]"
    assert calls == [4, 4, 4]
    assert provider.recorded_calls == [
        {"tool_name": "get_a", "arguments": {"x": 4}, "result": "[[90895834]]"}
    ]


async def test_timeout_retries_stop_at_the_limit_and_other_errors_are_not_retried():
    tool, calls = _scripted_tool("get_a", ["Error calling API: "])
    provider = RecordingScopedToolProvider(_FakeProvider([tool]))
    failures = []
    provider.on_failure = lambda: failures.append(1)
    wrapped = (await provider.get_all_tools())[0]
    assert await wrapped.coroutine(x=1) == "Error calling API: "
    assert len(calls) == 3 and failures == [1]  # 1 + API_TIMEOUT_RETRIES, then the agent sees the error

    for reply in ("Error calling API: Client error '404 Not Found'", "Error: bad arguments", "[]"):
        tool, calls = _scripted_tool("get_b", [reply])
        provider = RecordingScopedToolProvider(_FakeProvider([tool]))
        wrapped = (await provider.get_all_tools())[0]
        assert await wrapped.coroutine(x=1) == reply
        assert len(calls) == 1

    tool, calls = _scripted_tool("get_c", ["Error calling API: ", "[[1]]"])
    provider = RecordingScopedToolProvider(_FakeProvider([tool]))
    provider.api_timeout_retries = 0
    assert await (await provider.get_all_tools())[0].coroutine(x=1) == "Error calling API: "
    assert len(calls) == 1


async def test_cuga_tool_timeout_is_retried_and_the_last_one_raises():
    tool, calls = _scripted_tool(
        "get_a", [TimeoutError("Tool call 'get_a' timed out after 30 seconds"), "[[7]]"]
    )
    provider = RecordingScopedToolProvider(_FakeProvider([tool]), tool_cap=1)
    wrapped = (await provider.get_all_tools())[0]
    assert await wrapped.coroutine(x=1) == "[[7]]"
    assert len(calls) == 2 and len(provider.recorded_calls) == 1  # retries are not extra agent calls

    tool, calls = _scripted_tool("get_b", [TimeoutError("timed out")])
    provider = RecordingScopedToolProvider(_FakeProvider([tool]))
    with pytest.raises(TimeoutError):
        await (await provider.get_all_tools())[0].coroutine(x=1)
    assert len(calls) == 3
    assert provider.recorded_calls[0]["result"].startswith("Error:")


# ----------------------------- lowercase retry ---------------------------------


class _NameArgs(BaseModel):
    name: str = ""
    n: int = 0


def _stored_lowercase_tool(calls):
    """A table that stores names in lowercase: only the lowercase spelling matches rows."""

    async def coro(name: str = "", n: int = 0):
        calls.append(name)
        return {"rows": [[name, 3]]} if name == "murray ave" else {"rows": []}

    return StructuredTool(name="get_reviews", description="d", args_schema=_NameArgs, coroutine=coro)


def test_is_empty_or_zero():
    assert is_empty_or_zero("[]") and is_empty_or_zero({"count": 0}) and is_empty_or_zero("[[0]]")
    assert is_empty_or_zero("{'count': 0}") and is_empty_or_zero({"rows": []})
    assert not is_empty_or_zero({"count": 3}) and not is_empty_or_zero("[[0, 'x']]")
    assert not is_empty_or_zero({"ok": False}) and not is_empty_or_zero("Error: boom")


async def test_lowercase_retry_finds_the_stored_spelling_and_records_it():
    calls = []
    provider = RecordingScopedToolProvider(_FakeProvider([_stored_lowercase_tool(calls)]))
    provider.lowercase_retry = True
    wrapped = (await provider.get_all_tools())[0]
    assert await wrapped.coroutine(name="Murray Ave", n=1) == {"rows": [["murray ave", 3]]}
    assert calls == ["Murray Ave", "murray ave"]
    assert provider.recorded_calls[0]["arguments"] == {"name": "murray ave", "n": 1}


async def test_lowercase_retry_only_when_enabled_and_keeps_a_still_empty_result():
    calls = []
    provider = RecordingScopedToolProvider(_FakeProvider([_stored_lowercase_tool(calls)]))
    wrapped = (await provider.get_all_tools())[0]
    assert await wrapped.coroutine(name="Murray Ave") == {"rows": []} and calls == ["Murray Ave"]  # off
    provider.lowercase_retry = True
    calls.clear()
    assert await wrapped.coroutine(name="Elm St") == {"rows": []}  # no match either way: original kept
    assert calls == ["Elm St", "elm st"] and provider.recorded_calls[-1]["arguments"]["name"] == "Elm St"
    calls.clear()
    assert await wrapped.coroutine(name="murray ave") == {"rows": [["murray ave", 3]]}
    assert calls == ["murray ave"]  # already lowercase: no retry


def _stored_lowercase_handle_tool(calls):
    """A cap1 data tool: a filter answers with a handle, and only the lowercase spelling has records."""

    async def coro(name: str = "", n: int = 0):
        calls.append(name)
        return {"handle": "filtered_1", "num_records": 4 if name == "oakland" else 0}

    return StructuredTool(name="filter_data", description="d", args_schema=_NameArgs, coroutine=coro)


def test_is_empty_handle():
    assert is_empty_handle({"handle": "h", "num_records": 0}) and is_empty_handle(
        '{"handle": "h", "num_records": 0}'
    )
    assert not is_empty_handle({"handle": "h", "num_records": 4}) and not is_empty_handle({"count": 0})
    assert not is_empty_handle("Error: boom") and not is_empty_handle([])


async def test_lowercase_retry_treats_an_empty_handle_as_empty_only_when_enabled():
    calls = []
    provider = RecordingScopedToolProvider(_FakeProvider([_stored_lowercase_handle_tool(calls)]))
    provider.lowercase_retry = True
    wrapped = (await provider.get_all_tools())[0]
    assert (await wrapped.coroutine(name="Oakland"))["num_records"] == 0 and calls == [
        "Oakland"
    ]  # a handle is a value
    provider.empty_handles = True
    calls.clear()
    assert (await wrapped.coroutine(name="Oakland"))["num_records"] == 4
    assert calls == ["Oakland", "oakland"] and provider.recorded_calls[-1]["arguments"]["name"] == "oakland"
