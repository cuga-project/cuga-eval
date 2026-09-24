"""VakraAdapterAgent.invoke unit tests — config merging, scoping, demos, retries."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from benchmarks.m3.adapter.agent import VakraAdapterAgent, _last_user_text
from benchmarks.m3.adapter.config import PRESETS, AdapterConfig
from benchmarks.m3.adapter.demos import build_demo_index
from benchmarks.m3.adapter.instructions import ANSWER_DISCIPLINE, VERBATIM_RULE
from benchmarks.m3.adapter.recording import RecordingScopedToolProvider

pytestmark = pytest.mark.sanity


class _Result:
    """InvokeResult stand-in with pydantic-like model_copy."""

    def __init__(self, answer="", tool_calls=None, thread_id="t-1", error=None):
        self.answer = answer
        self.tool_calls = tool_calls or []
        self.thread_id = thread_id
        self.error = error

    def model_copy(self, update=None):
        clone = _Result(self.answer, list(self.tool_calls), self.thread_id, self.error)
        for k, v in (update or {}).items():
            setattr(clone, k, v)
        return clone


class _FakeInner:
    """Captures every invoke; yields scripted results."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []  # (message, thread_id, config)

    async def invoke(self, message=None, thread_id=None, config=None, **kwargs):
        self.calls.append(SimpleNamespace(message=message, thread_id=thread_id, config=config, kwargs=kwargs))
        return self.results.pop(0) if self.results else _Result(answer="")


class _FakeProvider:
    def __init__(self, tools=()):
        self._tools = list(tools)
        self.initialized = True

    async def initialize(self):
        return None

    async def get_apps(self):
        return []

    async def get_tools(self, app_name):
        return list(self._tools)

    async def get_all_tools(self):
        return list(self._tools)


def _agent(cfg, results, tools=(), demo_index=None):
    provider = RecordingScopedToolProvider(_FakeProvider(tools), tool_cap=cfg.tool_cap)
    inner = _FakeInner(results)
    return VakraAdapterAgent(inner, cfg, provider, demo_index), inner, provider


async def test_off_style_config_passes_through_untouched():
    cfg = AdapterConfig(enabled=True)  # enabled but every behavior off
    agent, inner, _ = _agent(cfg, [_Result(answer="42")])
    out = await agent.invoke("q", thread_id="th", config={"configurable": {"thread_id": "th"}})
    assert out.answer == "42"
    conf = inner.calls[0].config["configurable"]
    assert "special_instructions" not in conf  # nothing composed
    assert conf["thread_id"] == "th"  # caller's configurable preserved


async def test_existing_special_instructions_are_merged_not_replaced():
    cfg = AdapterConfig(enabled=True, discipline=True)
    agent, inner, _ = _agent(cfg, [_Result(answer="ok")])
    await agent.invoke("q", config={"configurable": {"special_instructions": "CALLER RIDER"}})
    si = inner.calls[0].config["configurable"]["special_instructions"]
    assert si.startswith("CALLER RIDER")
    assert ANSWER_DISCIPLINE in si


async def test_policy_scope_filters_provider_and_injects_verbatim():
    cfg = PRESETS["cap4_v3wx"]
    agent, inner, provider = _agent(cfg, [_Result(answer="grounded fact", tool_calls=[])])
    agent.set_task_context(
        additional_instructions="Use document retrievers only. Do not use any other tools."
    )
    # evidence so the guards keep the answer
    provider.recorded_calls.append({"tool_name": "query_d", "arguments": {}, "result": "grounded fact"})

    async def never_llm(prompt):  # absolute rule -> no classify call expected
        raise AssertionError("classifier should not run for absolute rules")

    agent._llm_ainvoke = never_llm
    out = await agent.invoke("what does the doc say?")
    assert provider.scope == "retriever_only"
    conf = inner.calls[0].config["configurable"]
    assert VERBATIM_RULE in conf["special_instructions"]
    assert conf["special_instructions"].startswith("Use document retrievers only.")
    assert conf["shortlisting_tool_threshold"] == 10**6
    assert out.answer  # kept (supported by evidence)


async def test_gate_retry_reuses_thread_and_merges_tool_calls():
    cfg = AdapterConfig(enabled=True, gates=True)
    first = _Result(answer="", tool_calls=[{"a": 1}], thread_id="inner-th")
    second = _Result(answer="7", tool_calls=[{"b": 2}], thread_id="inner-th")
    agent, inner, provider = _agent(cfg, [first, second])
    provider.recorded_calls.append({"tool_name": "t", "arguments": {}, "result": "7"})
    out = await agent.invoke("q", thread_id="caller-th")
    assert out.answer == "7"
    assert out.tool_calls == [{"a": 1}, {"b": 2}]  # merged across rounds
    retry = inner.calls[1]
    assert retry.thread_id == "inner-th"  # result thread wins for continuation
    assert isinstance(retry.message[0], HumanMessage)


async def test_recorded_calls_cleared_between_invokes():
    cfg = AdapterConfig(enabled=True)
    agent, _, provider = _agent(cfg, [_Result(answer="a"), _Result(answer="b")])
    provider.recorded_calls.append({"tool_name": "stale", "arguments": {}, "result": "x"})
    await agent.invoke("q1")
    assert provider.recorded_calls == []  # cleared at invoke start
    provider.recorded_calls.append({"tool_name": "fresh", "arguments": {}, "result": "y"})
    await agent.invoke("q2")
    assert provider.recorded_calls == []


async def test_demos_injected_and_self_leak_free(monkeypatch):
    sample = {
        "dialogue": {"turns": [{"turn_id": 0, "query": "solved question"}]},
        "expected_output": {
            "gold_sequence": [{"tool_call": [{"name": "get_x", "arguments": {}}]}],
            "answer_per_turn": ["42"],
        },
    }
    index = build_demo_index([sample])

    class _Stub:
        def encode(self, texts, convert_to_numpy=True):
            import numpy as np

            return np.ones((len(texts), 2))

    index._model = _Stub()
    cfg = AdapterConfig(enabled=True, demos=True, demos_k=2)
    agent, inner, _ = _agent(cfg, [_Result(answer="ok")], demo_index=index)
    await agent.invoke("new question")
    conf = inner.calls[0].config["configurable"]
    assert conf["mcp_few_shot_examples"][0]["content"] == "solved question"
    assert conf["cuga_lite_enable_few_shots"] is True
    # identical query -> self-leak guard -> no demos key at all
    agent2, inner2, _ = _agent(cfg, [_Result(answer="ok")], demo_index=index)
    await agent2.invoke("solved question")
    assert "mcp_few_shot_examples" not in inner2.calls[0].config["configurable"]


async def test_multiturn_message_uses_last_human_for_query():
    msgs = [
        HumanMessage(content="first turn"),
        AIMessage(content="answer one"),
        HumanMessage(content="second turn"),
    ]
    assert _last_user_text(msgs) == "second turn"
    assert _last_user_text("plain") == "plain"
    assert _last_user_text(None) == ""
    assert _last_user_text([AIMessage(content=[{"type": "text", "text": "blk"}])]) == "blk"


async def test_non_pydantic_result_mutated_in_place():
    class _Bare:
        answer = "x"
        tool_calls = None
        thread_id = None
        error = None

    cfg = AdapterConfig(enabled=True)
    agent, _, _ = _agent(cfg, [_Bare()])
    out = await agent.invoke("q")
    assert out.answer == "x"
    assert out.tool_calls == []


async def test_function_calling_preset_sets_the_fc_configurable_keys():
    agent, inner, _ = _agent(PRESETS["cap2"], [_Result(answer="7")])
    await agent.invoke("q", config={"configurable": {"thread_id": "th"}})
    conf = inner.calls[0].config["configurable"]
    assert conf["cuga_lite_execution_mode"] == "function_calling"
    assert conf["cuga_lite_bind_tools_mode"] == "all"
    assert conf["cuga_lite_bind_tools_max_count"] == 0
    assert conf["thread_id"] == "th"  # caller's configurable preserved


async def test_codeact_mode_leaves_the_execution_keys_alone():
    from dataclasses import replace

    cfg = replace(PRESETS["cap2"], execution_mode="codeact")  # the CodeAct arm of an A/B
    agent, inner, _ = _agent(cfg, [_Result(answer="7")])
    await agent.invoke("q")
    conf = inner.calls[0].config["configurable"]
    assert not [k for k in conf if k.startswith(("cuga_lite_execution_mode", "cuga_lite_bind_tools"))]
    agent4, inner4, _ = _agent(PRESETS["cap4_v3wx"], [_Result(answer="I can not answer.")])
    await agent4.invoke("q")
    assert "cuga_lite_execution_mode" not in inner4.calls[0].config["configurable"]  # V3WX is CodeAct
