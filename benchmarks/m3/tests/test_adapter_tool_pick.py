"""Two-stage tool pick (cosine top-N, then one LLM pick) and the empty-result hint."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from benchmarks.m3.adapter.config import BIND_CAP_SETTING, PRESETS, cuga_setting_pins, resolve_adapter_config
from benchmarks.m3.adapter.recording import (
    EMPTY_RESULT_HINT,
    RecordingScopedToolProvider,
    is_empty_result,
)
from benchmarks.m3.adapter.shortlist import (
    PICK_STRATEGY_PATH,
    CosinePickStrategy,
    build_shortlister,
    parse_tool_pick,
    render_tool_for_pick,
)

pytestmark = pytest.mark.sanity

NAMES = ["d_get_a", "d_get_b", "d_get_c", "d_get_d", "d_get_e"]


def test_tool_pick_config_env_validation_and_bind_cap_pin():
    cfg = resolve_adapter_config(
        "cap2", env={"M3_ADAPTER_TOOL_PICK": "true", "M3_ADAPTER_TOOL_PICK_BIND": "2"}
    )
    assert cfg.tool_pick and cfg.tool_pick_pool == 32 and cfg.tool_pick_bind == 2
    assert (f"advanced_features.{BIND_CAP_SETTING}", 2) in cuga_setting_pins(cfg)
    assert not any(
        k.endswith(BIND_CAP_SETTING) for k, _ in cuga_setting_pins(PRESETS["cap2_campaign"])
    )  # off: cap untouched
    with pytest.raises(ValueError, match="TOOL_PICK_BIND"):
        resolve_adapter_config("cap2", env={"M3_ADAPTER_TOOL_PICK": "1", "M3_ADAPTER_TOOL_PICK_BIND": "40"})


def test_parse_tool_pick_validates_names_and_resolves_bare_ones():
    assert parse_tool_pick('{"tool": "d_get_b", "runner_up": "d_get_c"}', NAMES) == ("d_get_b", "d_get_c")
    assert parse_tool_pick('noise {"tool": "get_b", "runner_up": "get_b"} noise', NAMES) == ("d_get_b", None)
    assert parse_tool_pick('{"tool": "invented", "runner_up": "d_get_a"}', NAMES) == (None, "d_get_a")
    assert parse_tool_pick("no json here", NAMES) == (None, None)


def test_render_tool_for_pick_lists_parameter_types_and_descriptions():
    class Args(BaseModel):
        state: str = Field(description="two-letter state code")

    async def run(state: str) -> str:
        return state

    tool = StructuredTool.from_function(
        coroutine=run, name="d_get_sales", description="Sales by state.", args_schema=Args
    )
    text = render_tool_for_pick(tool)
    assert (
        text.startswith("- d_get_sales: Sales by state.") and "state (string): two-letter state code" in text
    )
    assert "parameters: none" in render_tool_for_pick(
        SimpleNamespace(name="x", description="", args_schema=None)
    )


class _LLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    async def ainvoke(self, prompt):
        self.calls += 1
        self.prompt = prompt
        if isinstance(self.reply, Exception):
            raise self.reply
        return SimpleNamespace(content=self.reply)


def _request(llm, query="q?", top_k=3):
    from cuga.backend.cuga_graph.nodes.cuga_lite.shortlister.base import ShortlistRequest

    tools = [SimpleNamespace(name=n, description=f"{n} desc", args_schema=None) for n in NAMES]
    return ShortlistRequest(query=query, tools=tools, apps=[], top_k=top_k, llm=llm)


@pytest.fixture
def strategy(monkeypatch):
    monkeypatch.setattr(CosinePickStrategy, "_picks", {})
    monkeypatch.setattr(CosinePickStrategy, "pool", 4)
    s = CosinePickStrategy()

    async def cosine(request):  # cosine order: e, d, c, b (a is cut by the pool of 4)
        return ["d_get_e", "d_get_d", "d_get_c", "d_get_b"][: CosinePickStrategy.pool]

    monkeypatch.setattr(s, "_cosine_order", cosine)
    return s


async def test_pick_and_runner_up_lead_then_cosine_order_clamped_to_the_bind_count(strategy):
    llm = _LLM('{"tool": "d_get_c", "arguments": {}, "runner_up": "d_get_b"}')
    result = await strategy.shortlist(_request(llm))
    assert [c.name for c in result.candidates] == ["d_get_c", "d_get_b", "d_get_e"]
    assert "Question: q?" in llm.prompt and "d_get_a" not in llm.prompt  # only the cosine pool is shown
    again = await strategy.shortlist(_request(llm))  # same task, next model call: no second pick
    assert [c.name for c in again.candidates] == ["d_get_c", "d_get_b", "d_get_e"] and llm.calls == 1


async def test_failed_or_unparsable_pick_keeps_the_cosine_order(strategy):
    for llm in (_LLM(RuntimeError("proxy down")), _LLM("I think d_get_c")):
        CosinePickStrategy._picks.clear()
        result = await strategy.shortlist(_request(llm))
        assert [c.name for c in result.candidates] == ["d_get_e", "d_get_d", "d_get_c"]
    CosinePickStrategy._picks.clear()
    assert [c.name for c in (await strategy.shortlist(_request(None))).candidates][0] == "d_get_e"


def test_build_shortlister_uses_the_pick_strategy_at_the_bind_count(monkeypatch):
    import benchmarks.m3.adapter.shortlist as sl

    monkeypatch.setattr(sl, "prewarm_embedding_backend", lambda cfg: True)
    cfg = replace(PRESETS["cap2"], tool_pick=True, tool_pick_pool=24, tool_pick_bind=3)
    shortlister = build_shortlister(cfg)
    assert (shortlister.strategy, shortlister.top_k, shortlister.threshold) == (PICK_STRATEGY_PATH, 3, 3)
    assert CosinePickStrategy.pool == 24


@pytest.mark.parametrize(
    "result,empty",
    [
        ("[]", True),
        ("[[]]", True),
        ("[[null]]", True),
        ("{}", True),
        ('{"rows": []}', True),
        (None, True),
        ([], True),
        ("[[0]]", False),
        ('{"count": 0}', False),
        ("[[11355]]", False),
        ("no rows found", False),
    ],
)
def test_is_empty_result(result, empty):
    assert is_empty_result(result) is empty


async def test_empty_result_hint_reaches_the_agent_but_not_the_record():
    async def run(code: str = "") -> object:
        return {"CA": "[]", "XX": [], "TX": "[[3]]"}[code]

    tool = StructuredTool.from_function(coroutine=run, name="d_get_x", description="x")

    class _Reg:
        async def get_all_tools(self):
            return [tool]

    for any_type, list_hinted in ((False, False), (True, True)):
        provider = RecordingScopedToolProvider(
            _Reg(), empty_result_hint=True, hint_non_string_results=any_type
        )
        wrapped = (await provider.get_all_tools())[0]
        assert (await wrapped.ainvoke({"code": "CA"})).endswith(EMPTY_RESULT_HINT)
        assert provider.recorded_calls[-1]["result"] == "[]"  # the record keeps the raw result
        assert await wrapped.ainvoke({"code": "TX"}) == "[[3]]"
        listed = await wrapped.ainvoke({"code": "XX"})
        assert (isinstance(listed, str) and listed.endswith(EMPTY_RESULT_HINT)) is list_hinted
    plain = RecordingScopedToolProvider(_Reg())
    assert await (await plain.get_all_tools())[0].ainvoke({"code": "CA"}) == "[]"  # off by default


def _corpus():
    def sample(query, calls):
        return {
            "dialogue": {"turns": [{"query": query}]},
            "expected_output": {"gold_sequence": [{"tool_call": calls}], "answer_per_turn": ["x"]},
        }

    return [
        sample("asked question?", [{"name": "get_site", "arguments": {"cohort": "SELF", "race": "W"}}]),
        sample(
            "other one?",
            [{"name": "get_a", "arguments": {"cohort": "2y all", "race": "A", "database_path": "/x"}}],
        ),
        sample("another?", [{"name": "get_b", "arguments": {"cohort": "2y all", "rows": [1], "year": None}}]),
        sample("third?", [{"name": "get_c", "arguments": {"cohort": "4y other", "note": "z" * 80}}]),
    ]


def test_param_value_index_never_shows_the_asked_question_and_skips_unusable_values():
    from benchmarks.m3.adapter.demos import build_param_value_index

    index = build_param_value_index(_corpus())
    got = index.examples(
        ["cohort", "race", "rows", "year", "note", "database_path"], exclude_query="asked question?"
    )
    assert got == {"cohort": ["2y all", "4y other"], "race": ["A"]}  # SELF / W come only from the asked one
    assert index.examples(["cohort"], exclude_query="asked question?", k=1) == {"cohort": ["2y all"]}


async def test_empty_result_hint_lists_the_example_values_of_the_called_tools_parameters():
    async def run(cohort: str = "", race: str = "") -> str:
        return "[]"

    tool = StructuredTool.from_function(coroutine=run, name="d_get_site", description="site")

    class _Reg:
        async def get_all_tools(self):
            return [tool]

    provider = RecordingScopedToolProvider(_Reg(), empty_result_hint=True)
    provider.value_examples = lambda params: {"cohort": ["2y all", "4y other"], "race": []}
    reply = await (await provider.get_all_tools())[0].ainvoke({"cohort": "2-year"})
    assert reply.endswith("for these parameters: cohort: '2y all', '4y other'.")


def test_agent_value_lookup_is_per_task_and_needs_both_options():
    from benchmarks.m3.adapter.agent import VakraAdapterAgent
    from benchmarks.m3.adapter.demos import build_param_value_index

    index = build_param_value_index(_corpus())
    on = replace(PRESETS["cap2"], empty_result_hint=True, param_value_examples=3)
    agent = VakraAdapterAgent(object(), on, RecordingScopedToolProvider(None), value_index=index)
    assert agent._value_examples_for("asked question?")(["race"]) == {"race": ["A"]}
    for cfg in (replace(on, param_value_examples=0), replace(on, empty_result_hint=False)):
        assert (
            VakraAdapterAgent(
                object(), cfg, RecordingScopedToolProvider(None), value_index=index
            )._value_examples_for("q")
            is None
        )


def test_demo_corpus_loads_for_value_examples_even_with_demos_off(tmp_path):
    from benchmarks.m3.adapter.demos import load_demo_corpus

    class _Loader:
        def __init__(self, source):
            pass

        def load_domain(self, task_id, domain):
            return _corpus()

    off = replace(PRESETS["cap2"], demos=False, param_value_examples=0, demo_data=str(tmp_path))
    assert load_demo_corpus(off, task_id=2, domain="d", loader_factory=_Loader) is None
    on = replace(off, param_value_examples=4)
    assert len(load_demo_corpus(on, task_id=2, domain="d", loader_factory=_Loader)) == 4


# ---------------- per-turn tool set (CodeAct: campaign top-k prefilter, conversation-aware pick) ----------------


def _fake_encode(model_name, texts):  # deterministic bag-of-letters vectors: no model download
    import numpy as np

    return np.array(
        [[t.lower().count(c) + 0.01 for c in "abcdefghijklmnopqrstuvwxyz_"] for t in texts], dtype=float
    )


def _registry(names):
    async def run(**kwargs):
        return "[]"

    return [
        StructuredTool.from_function(coroutine=run, name=n, description=f"{n.replace('_', ' ')} tool")
        for n in names
    ]


CAT = ["d_get_sales_by_state", "d_get_population", "d_get_zip_codes", "d_get_area_code", "query_d_docs"]


async def test_provider_allowed_filters_before_the_policy_scope():
    tools = _registry(CAT)

    class _Reg:
        async def get_all_tools(self):
            return tools

    provider = RecordingScopedToolProvider(_Reg())
    provider.allowed = {"d_get_population", "query_d_docs"}
    assert [t.name for t in await provider.get_all_tools()] == ["d_get_population", "query_d_docs"]
    provider.scope = "no_retriever"
    assert [t.name for t in await provider.get_all_tools()] == ["d_get_population"]
    provider.allowed, provider.scope = None, "all"
    assert len(await provider.get_all_tools()) == len(CAT)


def test_conversation_history_drops_the_latest_user_turn():
    from langchain_core.messages import AIMessage, HumanMessage

    from benchmarks.m3.adapter.shortlist import conversation_history

    msgs = [HumanMessage(content="q1"), AIMessage(content="a" * 500), HumanMessage(content="q2")]
    text = conversation_history(msgs, max_answer_chars=5)
    assert text == "User: q1\nAssistant: aaaaa" and conversation_history("plain") == "(none)"


async def test_pick_turn_tools_exposes_pick_runner_up_fill_and_the_retrievers(monkeypatch):
    import benchmarks.m3.adapter.shortlist as sl

    monkeypatch.setattr(sl, "_encode", _fake_encode)
    cfg = replace(PRESETS["cap4_v3wx"], tool_pick=True, tool_pick_pool=5, tool_pick_bind=3)
    seen = {}

    async def llm(prompt):
        seen["prompt"] = prompt
        return '{"tool": "d_get_zip_codes", "runner_up": "d_get_area_code"}'

    names = await sl.pick_turn_tools("zip codes?", "User: q1", "use APIs only", _registry(CAT), cfg, llm)
    assert (
        names[:2] == ["d_get_zip_codes", "d_get_area_code"]
        and len(names) == 4
        and names[-1] == "query_d_docs"
    )
    assert "Policy: use APIs only" in seen["prompt"] and "Latest question: zip codes?" in seen["prompt"]

    async def bad(prompt):
        return "no idea"

    fallback = await sl.pick_turn_tools("zip codes?", "(none)", "", _registry(CAT), cfg, bad)
    assert len(fallback) == 4 and "query_d_docs" in fallback  # cosine order kept, retrievers still exposed


async def test_turn_tools_prefilter_pick_off_and_failure(monkeypatch):
    import benchmarks.m3.adapter.shortlist as sl
    from benchmarks.m3.adapter.agent import VakraAdapterAgent

    monkeypatch.setattr(sl, "_encode", _fake_encode)
    tools = _registry(CAT)

    class _Reg:
        async def get_all_tools(self):
            return tools

    def agent(cfg):
        a = VakraAdapterAgent(object(), cfg, RecordingScopedToolProvider(_Reg()))

        async def llm(prompt):
            return '{"tool": "d_get_population"}'

        a._llm_ainvoke = llm
        return a

    base = PRESETS["cap4_v3wx"]
    assert await agent(base)._turn_tools("population?", None) is None  # off: the full catalog
    top = await agent(replace(base, prefilter_top_k=3))._turn_tools("population?", None)
    assert len(top) == 3 and "query_d_docs" in top  # the campaign's top-k, retriever pinned
    picked = await agent(replace(base, tool_pick=True, tool_pick_pool=5, tool_pick_bind=1))._turn_tools(
        "population?", None
    )
    assert picked == {"d_get_population", "query_d_docs"}
    fc = replace(base, tool_pick=True, execution_mode="function_calling")
    assert await agent(fc)._turn_tools("population?", None) is None  # FC picks at bind time instead

    class _Broken:
        async def get_all_tools(self):
            raise RuntimeError("registry down")

    broken = VakraAdapterAgent(
        object(), replace(base, prefilter_top_k=3), RecordingScopedToolProvider(_Broken())
    )
    assert await broken._turn_tools("population?", None) is None


def test_bind_cap_and_pick_shortlister_only_in_function_calling(monkeypatch):
    import benchmarks.m3.adapter.shortlist as sl

    monkeypatch.setattr(sl, "prewarm_embedding_backend", lambda cfg: True)
    codeact = replace(PRESETS["cap4_v3wx"], tool_pick=True)
    assert not any(k.endswith(BIND_CAP_SETTING) for k, _ in cuga_setting_pins(codeact))
    shortlister = build_shortlister(codeact)
    assert shortlister is None or shortlister.strategy != PICK_STRATEGY_PATH
