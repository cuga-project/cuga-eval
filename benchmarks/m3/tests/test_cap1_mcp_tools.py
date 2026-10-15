"""cap1 runner's MCP tool binding: each tool calls ITSELF, with the schema's types, and the
recorded chain is exactly what was sent (the evaluator replays it verbatim)."""

import asyncio
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from benchmarks.m3.eval_m3_task_1_enterprise_style import (
    args_model_from_schema,
    drop_null_args,
    get_tools_from_session,
    mcp_structured_tool,
)

pytestmark = pytest.mark.sanity

_SELECT_SCHEMA = {
    "type": "object",
    "properties": {
        "data_label": {"type": "string", "description": "Handle string"},
        "key_name": {"type": "string"},
        "value": {"anyOf": [{"type": "string"}, {"type": "number"}]},
        "condition": {"type": "string", "enum": ["equal_to"], "default": "equal_to"},
        "limit": {"type": "integer", "default": -1},
        "distinct": {"type": "boolean", "default": False},
    },
    "required": ["data_label", "key_name", "value"],
    "additionalProperties": False,
}


class _FakeSession:
    def __init__(self, names):
        self.calls = []
        self._tools = [
            SimpleNamespace(name=n, description=f"{n} tool", inputSchema=_SELECT_SCHEMA) for n in names
        ]

    async def list_tools(self):
        return SimpleNamespace(tools=self._tools)

    async def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return SimpleNamespace(content=[SimpleNamespace(text=f"ran {name}")])


def test_every_tool_calls_itself_not_the_last_listed_tool():
    session = _FakeSession(["select_data_equal_to", "get_Names", "get_data"])
    tools = {t.name: t for t in (mcp_structured_tool(session, m) for m in session._tools)}
    for name in ("select_data_equal_to", "get_Names"):
        assert asyncio.run(tools[name].coroutine(data_label="h", key_name="k", value=1)) == f"ran {name}"
        assert tools[name].func(data_label="h", key_name="k", value=1) == f"ran {name}"
    assert [c[0] for c in session.calls] == [
        "select_data_equal_to",
        "select_data_equal_to",
        "get_Names",
        "get_Names",
    ]


def test_args_model_keeps_schema_types_defaults_and_enum_values():
    fields = args_model_from_schema("select_data_equal_to", _SELECT_SCHEMA).model_fields
    assert fields["data_label"].annotation is str and fields["data_label"].is_required()
    assert fields["value"].annotation is Any and fields["value"].is_required()
    assert fields["limit"].annotation == Optional[int] and fields["limit"].default == -1
    assert fields["distinct"].annotation == Optional[bool] and fields["distinct"].default is False
    assert fields["condition"].default == "equal_to"
    assert "Allowed values: equal_to" in fields["condition"].description
    assert args_model_from_schema("noargs", {}).model_fields == {}


def test_null_arguments_are_dropped_before_the_call_and_the_record(monkeypatch):
    from cuga.backend.cuga_graph.nodes.cuga_lite.tracking.tracker import ToolCallTracker

    recorded = []
    monkeypatch.setattr(ToolCallTracker, "record_call", staticmethod(lambda **kw: recorded.append(kw)))
    session = _FakeSession(["retrieve_data", "get_data"])
    tools = {t.name: t for t in asyncio.run(get_tools_from_session(session))}
    asyncio.run(
        tools["retrieve_data"].coroutine(data_label="h", key_name="k", value="x", limit=None, distinct=None)
    )
    sent = {"data_label": "h", "key_name": "k", "value": "x"}
    assert session.calls == [("retrieve_data", sent)]
    assert recorded[0]["tool_name"] == "retrieve_data" and recorded[0]["arguments"] == sent
    assert drop_null_args({"a": 0, "b": False, "c": None, "d": ""}) == {"a": 0, "b": False, "d": ""}
