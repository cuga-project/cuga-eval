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
        k.endswith(BIND_CAP_SETTING) for k, _ in cuga_setting_pins(PRESETS["cap2"])
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
