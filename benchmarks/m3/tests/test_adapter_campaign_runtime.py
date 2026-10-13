"""Campaign-runtime fields: what reaches CUGA per invoke, the item timeout, demo tool names, settings pins."""

import asyncio
import sys
from dataclasses import replace
from types import ModuleType, SimpleNamespace

import pytest

from benchmarks.m3.adapter.agent import VakraAdapterAgent, apply_cuga_settings
from benchmarks.m3.adapter.config import PRESETS
from benchmarks.m3.adapter.demos import _format_call, bound_tool_namer, build_demo_index, select_prose_pairs
from benchmarks.m3.adapter.instructions import FC_ANSWER_FORMAT_LINE
from benchmarks.m3.adapter.recording import RecordingScopedToolProvider

pytestmark = pytest.mark.sanity


class _Result:
    def __init__(self, answer=""):
        self.answer = answer
        self.tool_calls = []
        self.thread_id = "t-1"
        self.error = None

    def model_copy(self, update=None):
        clone = _Result(self.answer)
        for k, v in (update or {}).items():
            setattr(clone, k, v)
        return clone


class _Inner:
    def __init__(self, answer="42", delay=0.0):
        self.answer, self.delay, self.configs = answer, delay, []

    async def invoke(self, message=None, thread_id=None, config=None, **kwargs):
        self.configs.append(config)
        if self.delay:
            await asyncio.sleep(self.delay)
        return _Result(self.answer)


class _Provider:
    def __init__(self, names=()):
        self.names = list(names)

    async def initialize(self):
        return None

    async def get_apps(self):
        return []

    async def get_tools(self, app_name):
        return await self.get_all_tools()

    async def get_all_tools(self):
        return [SimpleNamespace(name=n) for n in self.names]


def _agent(cfg, inner, names=(), demo_index=None):
    provider = RecordingScopedToolProvider(_Provider(names), tool_cap=cfg.tool_cap)
    # evidence so the answer guards keep the scripted answer
    provider.recorded_calls.append({"tool_name": "t", "arguments": {}, "result": "42"})
    return VakraAdapterAgent(inner, cfg, provider, demo_index)


async def test_campaign_runtime_keys_and_answer_format_reach_cuga():
    inner = _Inner()
    agent = _agent(replace(PRESETS["cap3"], agent_timeout=None), inner)
    await agent.invoke("How many?")
    conf = inner.configs[0]["configurable"]
    assert conf["cuga_lite_execution_mode"] == "function_calling"
    assert conf["cuga_lite_step_discipline"] == "one_tool_per_step"
    assert conf["cuga_lite_fc_prompt_fragments"] == ["evidence_first"]
    assert conf["shortlisting_tool_threshold"] == 10**6
    assert conf["cuga_lite_max_steps"] == 70
    assert conf["special_instructions"].startswith(FC_ANSWER_FORMAT_LINE)


async def test_agent_timeout_cancels_the_turn_with_a_named_error():
    agent = _agent(replace(PRESETS["cap3"], agent_timeout=1), _Inner(delay=5))
    with pytest.raises(TimeoutError, match="agent_timeout 1s exceeded"):
        await agent.invoke("slow")


async def test_turn_within_agent_timeout_returns_normally():
    agent = _agent(replace(PRESETS["cap3"], agent_timeout=5), _Inner(answer="7"))
    out = await agent.invoke("fast")
    assert out.answer == "7"


def test_bound_tool_namer_maps_raw_names_to_registry_names():
    namer = bound_tool_namer(["books_get_count", "books_get_count_by_language", "other"])
    assert namer("get_count") == "books_get_count"
    assert namer("get_count_by_language") == "books_get_count_by_language"
    assert namer("other") == "other"  # exact name wins
    assert namer("missing_tool") == "missing_tool"  # unknown names stay raw
    # several suffix matches: the shortest (plain domain prefix) wins
    assert bound_tool_namer(["a_b_get_x", "a_get_x"])("get_x") == "a_get_x"
    assert _format_call({"name": "get_count", "arguments": {"x": 1}}, namer) == 'books_get_count({"x": 1})'


def _stub_index():
    pytest.importorskip("numpy")
    import numpy as np

    sample = {
        "dialogue": {"turns": [{"turn_id": 0, "query": "Which language?"}]},
        "expected_output": {
            "gold_sequence": [{"tool_call": [{"name": "get_language", "arguments": {"isbn": "1"}}]}],
            "answer_per_turn": ["English"],
        },
    }
    index = build_demo_index([sample])

    class _StubModel:
        def encode(self, texts, convert_to_numpy=True):
            return np.ones((len(texts), 2))

    index._model = _StubModel()
    return index


def test_demo_chain_names_follow_the_namer():
    index = _stub_index()
    raw = select_prose_pairs(index, "Which book?", k=1)
    bound = select_prose_pairs(index, "Which book?", k=1, namer=bound_tool_namer(["books_get_language"]))
    assert "Chain used: get_language(" in raw[1]["content"]
    assert "Chain used: books_get_language(" in bound[1]["content"]


async def test_agent_renders_demos_with_the_provider_tool_names():
    inner = _Inner()
    # registry names on the wire: the namer maps corpus names onto them
    cfg = replace(PRESETS["cap3"], agent_timeout=None, bare_tool_names=False)
    agent = _agent(cfg, inner, names=["books_get_language"], demo_index=_stub_index())
    await agent.invoke("Which book?")
    demos = inner.configs[0]["configurable"]["mcp_few_shot_examples"]
    assert "books_get_language(" in demos[1]["content"]
    off = _Inner()
    agent_raw = _agent(
        replace(cfg, demo_bound_names=False), off, names=["books_get_language"], demo_index=_stub_index()
    )
    await agent_raw.invoke("Which book?")
    assert (
        "Chain used: get_language(" in off.configs[0]["configurable"]["mcp_few_shot_examples"][1]["content"]
    )


class _Settings:
    def __init__(self):
        self.values = {"advanced_features.force_autonomous_mode": True, "connections.llm_http_timeout": 61}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value


def _install_settings(monkeypatch, settings):
    mod = ModuleType("cuga.config")
    mod.settings = settings
    monkeypatch.setitem(sys.modules, "cuga", sys.modules.get("cuga") or ModuleType("cuga"))
    monkeypatch.setitem(sys.modules, "cuga.config", mod)


def test_apply_cuga_settings_pins_campaign_values(monkeypatch):
    settings = _Settings()
    _install_settings(monkeypatch, settings)
    apply_cuga_settings(PRESETS["cap3"])
    assert settings.values["advanced_features.force_autonomous_mode"] is False
    assert settings.values["advanced_features.reflection_enabled"] is False
    assert settings.values["connections.llm_http_timeout"] == 150


def test_apply_cuga_settings_is_a_noop_for_off_and_tolerates_unpinnable_settings(monkeypatch):
    settings = _Settings()
    _install_settings(monkeypatch, settings)
    apply_cuga_settings(PRESETS["off"])
    assert settings.values["connections.llm_http_timeout"] == 61
    _install_settings(monkeypatch, SimpleNamespace())  # no get/set: warn, do not raise
    apply_cuga_settings(PRESETS["cap3"])


async def test_with_bare_tool_names_demos_keep_the_corpus_names():
    inner = _Inner()
    cfg = replace(PRESETS["cap3"], agent_timeout=None)  # bare names: corpus names == bound names
    agent = _agent(cfg, inner, names=["books_get_language"], demo_index=_stub_index())
    await agent.invoke("Which book?")
    assert (
        "Chain used: get_language(" in inner.configs[0]["configurable"]["mcp_few_shot_examples"][1]["content"]
    )


def _registry_tool(app, name, calls):
    from langchain_core.tools import StructuredTool

    async def run(isbn: str = "") -> str:
        calls.append((name, isbn))
        return f"{name}:{isbn}"

    run._app_name = app  # what cuga's registry provider stamps
    return StructuredTool.from_function(coroutine=run, name=f"{app}_{name}", description=f"{name} tool")


async def test_bare_tool_names_expose_mcp_names_and_still_route_to_the_registry_tool():
    from benchmarks.m3.adapter.recording import bare_tool_name

    calls = []
    raw = [_registry_tool("books", "get_language", calls), _registry_tool("books", "query_books_docs", calls)]

    class _Reg:
        async def get_all_tools(self):
            return raw

    provider = RecordingScopedToolProvider(_Reg(), bare_names=True)
    tools = await provider.get_all_tools()
    assert [t.name for t in tools] == ["get_language", "query_books_docs"]
    assert [bare_tool_name(t) for t in raw] == ["get_language", "query_books_docs"]
    assert await tools[0].ainvoke({"isbn": "9"}) == "get_language:9"
    assert calls == [("get_language", "9")]  # the raw registry coroutine ran
    assert provider.recorded_calls[0]["tool_name"] == "get_language"
    assert (await provider.get_all_tools())[0] is tools[0]  # wrappers stay memoized
    registry = RecordingScopedToolProvider(_Reg())  # default: registry names untouched
    assert [t.name for t in await registry.get_all_tools()] == [
        "books_get_language",
        "books_query_books_docs",
    ]


async def test_bare_name_collisions_keep_registry_names():
    calls = []
    raw = [_registry_tool("a", "get_x", calls), _registry_tool("b", "get_x", calls)]

    class _Reg:
        async def get_all_tools(self):
            return raw

    provider = RecordingScopedToolProvider(_Reg(), bare_names=True)
    assert [t.name for t in await provider.get_all_tools()] == ["a_get_x", "b_get_x"]


def _tools(*names):
    return [SimpleNamespace(name=n, description=f"{n} does things") for n in names]


def test_campaign_rank_is_a_noop_within_top_k_and_pins_retrievers():
    from benchmarks.m3.adapter.shortlist import campaign_rank

    def never(texts):
        raise AssertionError("no embedding when the catalog fits")

    tools = _tools("a", "b")
    assert [t.name for t, _, _ in campaign_rank("q", tools, 2, never)] == ["a", "b"]
    tools = _tools("query_docs", "a", "b", "c")
    assert [t.name for t, _, _ in campaign_rank("q", tools, 1, never)] == ["query_docs"]  # pins fill top_k
    assert [t.name for t, _, _ in campaign_rank("q", tools, 4, never)] == ["query_docs", "a", "b", "c"]


def test_campaign_rank_orders_by_cosine_over_name_and_description():
    import numpy as np

    from benchmarks.m3.adapter.shortlist import campaign_rank

    seen = []

    def encode(texts):
        seen.extend(texts)
        vec = {"q": [1.0, 0.0], "a: a does things": [0.0, 1.0], "b: b does things": [3.0, 0.1]}
        vec["c: c does things"] = [1.0, 1.0]
        return np.array([vec[t] for t in texts])

    ranked = campaign_rank("q", _tools("a", "b", "c"), 2, encode)
    assert [t.name for t, _, _ in ranked] == ["b", "c"]  # cosine, not raw dot product
    assert "a: a does things" in seen  # the campaign's text: "<name>: <description>"
    assert ranked[0][1] > ranked[1][1]


async def test_campaign_strategy_returns_sdk_candidates(monkeypatch):
    import numpy as np

    from benchmarks.m3.adapter import shortlist

    monkeypatch.setattr(
        shortlist, "_encode", lambda model, texts: np.array([[1.0, float(len(t))] for t in texts])
    )
    request = SimpleNamespace(tools=_tools("query_x", "a", "bb", "ccc"), top_k=2, query="q", task_context="")
    result = await shortlist.CampaignMiniLMStrategy(SimpleNamespace(embedding_model="m")).shortlist(request)
    assert [c.name for c in result.candidates][0] == "query_x" and len(result.candidates) == 2


def test_temperature_pins_every_model_block_cuga_defines(monkeypatch):
    settings = _Settings()
    settings.values.update(
        {"agent.code.model": {"temperature": 0.1}, "agent.chat.model": {"temperature": 0.1}}
    )
    _install_settings(monkeypatch, settings)
    apply_cuga_settings(PRESETS["cap3"])
    assert settings.values["agent.code.model.temperature"] == 1.0
    assert settings.values["agent.chat.model.temperature"] == 1.0
    assert "agent.planner.model.temperature" not in settings.values  # block not defined: skipped
