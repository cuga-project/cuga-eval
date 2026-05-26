import pytest
from langchain_core.messages import HumanMessage

from benchmarks.helpers.react_agent import GenericReactAgent

pytestmark = pytest.mark.stability


class FakeTool:
    def __init__(self, name: str, description: str, handler):
        self.name = name
        self.description = description
        self._handler = handler

    async def ainvoke(self, args):
        return self._handler(args)


class FakeToolProvider:
    def __init__(self, tools):
        self._tools = tools

    async def get_all_tools(self):
        return self._tools


class ScriptedReactAgent(GenericReactAgent):
    def __init__(self, tool_provider, scripted_responses, **kwargs):
        super().__init__(tool_provider=tool_provider, model="test-model", **kwargs)
        self.scripted_responses = list(scripted_responses)
        self.llm_inputs = []

    async def _call_llm(self, messages):
        snapshot = [{"role": m["role"], "content": m["content"]} for m in messages]
        self.llm_inputs.append(snapshot)
        if not self.scripted_responses:
            raise AssertionError("No scripted response left for _call_llm")
        return self.scripted_responses.pop(0)


@pytest.mark.asyncio
async def test_react_agent_executes_multi_step_tool_loop_and_logs_observations():
    execution_log = []

    def add_handler(args):
        execution_log.append({"tool": "adder", "args": dict(args)})
        return {"sum": int(args["a"]) + int(args["b"])}

    def multiply_handler(args):
        execution_log.append({"tool": "multiplier", "args": dict(args)})
        return {"product": int(args["value"]) * int(args["factor"])}

    tools = [
        FakeTool("adder", "Add two integers.", add_handler),
        FakeTool("multiplier", "Multiply an integer by a factor.", multiply_handler),
    ]
    provider = FakeToolProvider(tools)

    scripted_responses = [
        """```json
{
  "action": "tool",
  "tool_name": "adder",
  "args": {"a": 2, "b": 3}
}
```""",
        """```json
{
  "action": "tool",
  "tool_name": "multiplier",
  "args": {"value": 5, "factor": 4}
}
```""",
        "Final Answer: 20",
    ]

    agent = ScriptedReactAgent(
        tool_provider=provider,
        scripted_responses=scripted_responses,
        max_steps=5,
        special_instructions="Test mode. Complete the calculation exactly.",
    )

    result = await agent.invoke(
        [HumanMessage(content="Add 2 and 3, then multiply by 4.")],
        thread_id="test-thread",
        user_context="Return only the computed number.",
        track_tool_calls=True,
    )

    assert result.answer == "20"
    assert result.tool_calls == [
        {"name": "adder", "arguments": {"a": 2, "b": 3}},
        {"name": "multiplier", "arguments": {"value": 5, "factor": 4}},
    ]

    assert execution_log == [
        {"tool": "adder", "args": {"a": 2, "b": 3}},
        {"tool": "multiplier", "args": {"value": 5, "factor": 4}},
    ]

    assert len(agent.llm_inputs) == 3

    second_turn_messages = agent.llm_inputs[1]
    assert any(
        msg["role"] == "user" and 'Output:\n```\n{"sum": 5}\n```' in msg["content"]
        for msg in second_turn_messages
    )

    third_turn_messages = agent.llm_inputs[2]
    assert any(
        msg["role"] == "user" and 'Output:\n```\n{"product": 20}\n```' in msg["content"]
        for msg in third_turn_messages
    )

    assert result.raw_messages[-1]["role"] == "assistant"
    assert result.raw_messages[-1]["content"] == "Final Answer: 20"


@pytest.mark.asyncio
async def test_react_agent_returns_tool_error_observation_and_continues():
    execution_log = []

    def failing_handler(args):
        execution_log.append({"tool": "unstable_tool", "args": dict(args)})
        raise RuntimeError("boom")

    provider = FakeToolProvider([FakeTool("unstable_tool", "Always fails.", failing_handler)])

    scripted_responses = [
        """```json
{
  "action": "tool",
  "tool_name": "unstable_tool",
  "args": {"attempt": 1}
}
```""",
        "Final Answer: FAILED - tool failed as expected",
    ]

    agent = ScriptedReactAgent(
        tool_provider=provider,
        scripted_responses=scripted_responses,
        max_steps=3,
    )

    result = await agent.invoke(
        [HumanMessage(content="Try the unstable tool once, then stop.")],
        thread_id="error-thread",
        track_tool_calls=True,
    )

    assert result.answer == "FAILED - tool failed as expected"
    assert result.tool_calls == [
        {"name": "unstable_tool", "arguments": {"attempt": 1}},
    ]
    assert execution_log == [
        {"tool": "unstable_tool", "args": {"attempt": 1}},
    ]

    second_turn_messages = agent.llm_inputs[1]
    assert any(
        msg["role"] == "user" and "Tool execution error for 'unstable_tool': boom" in msg["content"]
        for msg in second_turn_messages
    )


# Made with Bob
