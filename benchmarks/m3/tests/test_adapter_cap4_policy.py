"""cap4 policy options: refusal on a retriever-only scope, topic match by domain, hidden retrievers,
refusal persistence outside that scope, and the per-stage answer trace."""

import json
from types import SimpleNamespace

import pytest

from benchmarks.m3.adapter import scope as scope_mod
from benchmarks.m3.adapter.agent import VakraAdapterAgent
from benchmarks.m3.adapter.config import AdapterConfig, TaskContext, resolve_adapter_config
from benchmarks.m3.adapter.guards import (
    REFUSAL_RECOVERY_CORRECTION,
    USE_API_CORRECTION,
    run_answer_pipeline,
)
from benchmarks.m3.adapter.recording import RecordingScopedToolProvider
from benchmarks.m3.adapter.scope import resolve_scope

pytestmark = pytest.mark.sanity

ABS_RETRIEVERS = "Use document retrievers to answer questions. Do not use any other type of tool."
COND_RETRIEVERS = (
    "If a user's query pertains to Sports & Athletics, which is/are about Topics covering athletes, games, "
    "and statistics from different leagues, make sure you try answering them by only using document "
    "retrievers. Do not use other types of tools."
)
API_CALL = {
    "tool_name": "hockey_get_x",
    "arguments": {"id": 1},
    "result": '{"x": 42}',
    "result_full": '{"x": 42}',
}
RETRIEVER_CALL = {"tool_name": "hockey_query_hockey", "arguments": {"q": "x"}, "result": "doc text"}


def _result(answer):
    return SimpleNamespace(answer=answer, error=None, tool_calls=[])


def _rounds(*answers, on_round=None):
    sent, queue = [], list(answers)

    async def invoke_round(correction):
        sent.append(correction)
        if on_round:
            on_round()
        return _result(queue.pop(0) if queue else "")

    return invoke_round, sent


def _llm(reply, prompts=None):
    async def ainvoke(prompt):
        if prompts is not None:
            prompts.append(prompt)
        if isinstance(reply, Exception):
            raise reply
        return reply

    return ainvoke


# ------------------------------------------------------------------ topic match by domain


@pytest.fixture(autouse=True)
def _fresh_domain_cache():
    scope_mod._DOMAIN_TOPIC.clear()
    yield
    scope_mod._DOMAIN_TOPIC.clear()


async def test_domain_topic_match_asks_once_per_domain_and_topic():
    prompts = []
    llm = _llm("YES", prompts)
    for query in ("Who scored most?", "List the teams."):
        assert await resolve_scope(COND_RETRIEVERS, query, llm, domain="hockey", topic_match="domain") == (
            "retriever_only"
        )
    assert len(prompts) == 1 and "Database: hockey" in prompts[0] and "Who scored" not in prompts[0]
    assert (
        await resolve_scope(COND_RETRIEVERS, "q", _llm("NO"), domain="movie", topic_match="domain") == "all"
    )


async def test_domain_topic_match_failure_assumes_a_match_and_is_not_cached():
    out = await resolve_scope(
        COND_RETRIEVERS, "q", _llm(RuntimeError("down")), domain="hockey", topic_match="domain"
    )
    assert out == "retriever_only" and ("hockey", "Sports & Athletics") not in scope_mod._DOMAIN_TOPIC


async def test_question_topic_match_is_the_default_and_unchanged():
    prompts = []
    assert await resolve_scope(COND_RETRIEVERS, "Who won?", _llm("NO", prompts), domain="hockey") == "all"
    assert "Question: Who won?" in prompts[0]
    assert await resolve_scope(ABS_RETRIEVERS, "q", None) == "retriever_only"


def test_topic_match_is_validated_and_read_from_the_environment():
    cfg = resolve_adapter_config("cap4", env={"M3_ADAPTER_TOPIC_MATCH": "domain"})
    assert cfg.topic_match == "domain"
    with pytest.raises(ValueError):
        resolve_adapter_config("cap4", env={"M3_ADAPTER_TOPIC_MATCH": "query"})


# ------------------------------------------------------------------ agent: scope refusal, hidden retrievers


class _Inner:
    def __init__(self):
        self.calls = 0

    async def invoke(self, message=None, thread_id=None, config=None, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            answer="42", tool_calls=[{"name": "hockey_get_x"}], thread_id=thread_id, error=None
        )


class _Provider:
    async def get_all_tools(self):
        return []


def _agent(cfg, inner, policy="", domain="hockey"):
    agent = VakraAdapterAgent(inner, cfg, RecordingScopedToolProvider(_Provider()))
    agent.set_task_context(additional_instructions=policy, domain=domain, task_id="u1")
    return agent


async def test_retriever_scope_refusal_answers_without_running_the_agent():
    inner = _Inner()
    cfg = AdapterConfig(enabled=True, scope=True, retriever_scope_refusal=True)
    out = await _agent(cfg, inner, ABS_RETRIEVERS).invoke("q", thread_id="t")
    assert out.answer == "I can not answer." and out.tool_calls == [] and inner.calls == 0
    out = await _agent(cfg, inner, "").invoke("q", thread_id="t")  # no policy: the agent runs
    assert out.answer == "42" and inner.calls == 1


async def test_hide_retrievers_scopes_every_task_outside_a_retriever_only_policy():
    agent = _agent(AdapterConfig(enabled=True, scope=True, hide_retrievers=True), _Inner())
    await agent.invoke("q", thread_id="t")
    assert agent._provider.scope == "no_retriever"
    agent = _agent(AdapterConfig(enabled=True, scope=True, hide_retrievers=True), _Inner(), ABS_RETRIEVERS)
    await agent.invoke("q", thread_id="t")
    assert agent._provider.scope == "retriever_only"  # the policy's own scope wins


# ------------------------------------------------------------------ refusal persistence


async def test_persist_asks_for_a_database_call_then_recovery_then_the_composer():
    calls = []
    invoke_round, sent = _rounds(
        "I can not answer.", "I can not answer.", on_round=lambda: calls.append(API_CALL)
    )
    out = await run_answer_pipeline(
        invoke_round,
        _result("I can not answer."),
        AdapterConfig(refusal_persist=True),
        TaskContext(),
        calls,
        _llm("Final answer: 42"),
        question="What is x?",
    )
    assert sent == [USE_API_CORRECTION, REFUSAL_RECOVERY_CORRECTION] and out == "42"


async def test_persist_skips_the_database_reask_after_a_successful_api_call_and_stops_once_answered():
    invoke_round, sent = _rounds("42")
    out = await run_answer_pipeline(
        invoke_round,
        _result("I can not answer."),
        AdapterConfig(refusal_persist=True),
        TaskContext(),
        [API_CALL],
    )
    assert sent == [REFUSAL_RECOVERY_CORRECTION] and out == "42"


async def test_persist_reasks_when_only_retrievers_answered():
    invoke_round, sent = _rounds("42")
    out = await run_answer_pipeline(
        invoke_round,
        _result("I can not answer."),
        AdapterConfig(refusal_persist=True),
        TaskContext(),
        [RETRIEVER_CALL],
    )
    assert sent[0] == USE_API_CORRECTION and out == "42"


async def test_persist_leaves_retriever_scope_answers_and_keeps_the_refusal_on_an_empty_reask():
    invoke_round, sent = _rounds("42")
    ctx = TaskContext(last_scope="retriever_only")
    out = await run_answer_pipeline(
        invoke_round, _result("I can not answer."), AdapterConfig(refusal_persist=True), ctx, []
    )
    assert out == "I can not answer." and sent == []
    invoke_round, sent = _rounds("")  # the re-ask ends empty: the refusal stays
    out = await run_answer_pipeline(
        invoke_round, _result("I can not answer."), AdapterConfig(refusal_persist=True), TaskContext(), []
    )
    assert out == "I can not answer." and sent == [USE_API_CORRECTION]


# ------------------------------------------------------------------ stage trace


async def test_stage_trace_records_each_stage_with_its_tool_call_count(tmp_path, monkeypatch):
    monkeypatch.setenv("M3_RESULTS_DIR", str(tmp_path))
    cfg = AdapterConfig(enabled=True, refusal_persist=True, stage_trace=True)

    class _Refuses(_Inner):
        async def invoke(self, message=None, thread_id=None, config=None, **kwargs):
            self.calls += 1
            answer = "I can not answer." if self.calls == 1 else "42"
            return SimpleNamespace(
                answer=answer, tool_calls=[{"name": "hockey_get_x"}], thread_id=thread_id, error=None
            )

    out = await _agent(cfg, _Refuses()).invoke("What is x?", thread_id="t")
    assert out.answer == "42"
    (trace,) = list(tmp_path.glob("adapter_trace.*.jsonl"))
    rec = json.loads(trace.read_text().splitlines()[0])
    assert rec["task_id"] == "u1" and rec["domain"] == "hockey" and rec["final"] == "42"
    assert [(s["stage"], s["answer"], s["n_calls"]) for s in rec["stages"]] == [
        ("base", "I can not answer.", 1),
        ("persist-api", "42", 2),
    ]


async def test_scope_refusal_is_traced(tmp_path, monkeypatch):
    monkeypatch.setenv("M3_RESULTS_DIR", str(tmp_path))
    cfg = AdapterConfig(enabled=True, scope=True, retriever_scope_refusal=True, stage_trace=True)
    await _agent(cfg, _Inner(), ABS_RETRIEVERS).invoke("q", thread_id="t")
    rec = json.loads(next(tmp_path.glob("adapter_trace.*.jsonl")).read_text())
    assert rec["scope"] == "retriever_only" and rec["stages"][0]["stage"] == "scope-refusal"
