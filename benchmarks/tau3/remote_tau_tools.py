from __future__ import annotations

import json
from typing import Any

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model


_UNLOCK_AGENT_TOOL = "unlock_discoverable_agent_tool"
_CALL_AGENT_TOOL = "call_discoverable_agent_tool"
_EXECUTE_AGENT_TOOL = "execute_discoverable_agent_tool"
_GIVE_USER_TOOL = "give_discoverable_user_tool"

# The bridge itself currently waits up to 300 seconds for Tau to execute a
# pending call. Give the HTTP client a slightly longer read timeout so the
# bridge can return its own useful timeout error first.
_TAU_BRIDGE_READ_TIMEOUT_SECONDS = 330.0


_TEXT_OBSERVATION_TOOL_NAMES = {"KB_search"}
_TEXT_OBSERVATION_PREFIXES = (
    "get_",
    "list_",
    "search_",
    "find_",
    "lookup_",
    "query_",
    "retrieve_",
)

_TEXT_OBSERVATION_SUFFIX = (
    "Returns human-readable text, not a structured Python object. "
    "Do not use .get(), field indexing, or attributes on the result. "
    "If a later tool call depends on values in this text, print it, end "
    "the current code block, and continue in the next reasoning step."
)


# ---------------------------------------------------------------------------
# Temporary compatibility API
# ---------------------------------------------------------------------------
# Older versions of benchmarks/tau3/server.py imported these names and used a
# separate server-side pending-call queue. The broker architecture supersedes
# that queue: all calls now travel through cuga_bridge_server and are surfaced
# by cuga_remote_agent as native Tau ToolCalls.
#
# Keep these no-op definitions until server.py is cleaned up, so replacing this
# file does not create an import error or a second competing call path.


class PendingTauToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


def reset_pending_tau_tool_calls(session_id: str) -> None:
    _log(
        "legacy pending-call reset ignored; broker owns calls for session:",
        session_id,
    )


def clear_pending_tau_tool_calls(session_id: str) -> None:
    _log(
        "legacy pending-call clear ignored; broker owns calls for session:",
        session_id,
    )


def drain_pending_tau_tool_calls(
    session_id: str,
) -> list[PendingTauToolCall]:
    _log(
        "legacy pending-call drain returned empty; broker owns calls for session:",
        session_id,
    )
    return []


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _log(*args: Any) -> None:
    print("[remote_tau_tools]", *args, flush=True)


def _json_schema_type_to_python(schema: dict[str, Any]) -> Any:
    schema_type = schema.get("type")

    if schema_type == "string":
        return str
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        return list
    if schema_type == "object":
        return dict

    return Any


def _make_args_schema(
    tool_name: str,
    parameters_schema: dict[str, Any],
) -> type[BaseModel]:
    properties = parameters_schema.get("properties", {}) or {}
    required = set(parameters_schema.get("required", []) or [])

    fields: dict[str, tuple[Any, Any]] = {}

    for arg_name, arg_schema in properties.items():
        py_type = _json_schema_type_to_python(arg_schema)
        description = arg_schema.get("description", "")

        default = ... if arg_name in required else arg_schema.get("default")

        fields[arg_name] = (
            py_type,
            Field(
                default,
                description=description,
            ),
        )

    return create_model(
        f"{tool_name}_Args",
        **fields,
    )


def _is_text_observation_tool(tool_name: str) -> bool:
    return (
        tool_name in _TEXT_OBSERVATION_TOOL_NAMES
        or tool_name.startswith(_TEXT_OBSERVATION_PREFIXES)
    )


def _adapt_tool_description(
    tool_name: str,
    description: str,
) -> str:
    base_description = description.strip() or tool_name

    if not _is_text_observation_tool(tool_name):
        return base_description

    return f"{base_description}\n\n{_TEXT_OBSERVATION_SUFFIX}"


def _get_tool_function_schema(
    tool_spec: dict[str, Any],
) -> dict[str, Any]:
    openai_schema = tool_spec.get("openai_schema")

    if not isinstance(openai_schema, dict):
        raise ValueError(
            "Tau tool specification is missing a valid 'openai_schema': "
            f"{tool_spec}"
        )

    function_schema = openai_schema.get("function")

    if not isinstance(function_schema, dict):
        raise ValueError(
            "Tau tool specification is missing a valid "
            f"'openai_schema.function': {tool_spec}"
        )

    return function_schema


def _get_tool_name(tool_spec: dict[str, Any]) -> str:
    function_schema = _get_tool_function_schema(tool_spec)
    tool_name = function_schema.get("name")

    if not isinstance(tool_name, str) or not tool_name:
        raise ValueError(
            "Tau tool specification contains an invalid function name: "
            f"{tool_spec}"
        )

    return tool_name


def _stringify_tool_result(result: Any) -> str:
    if isinstance(result, str):
        return result

    try:
        return json.dumps(
            result,
            ensure_ascii=False,
            default=str,
        )
    except (TypeError, ValueError):
        return str(result)


def _normalize_arguments_json(arguments: str | None) -> str:
    raw_arguments = arguments or "{}"

    try:
        parsed_arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "The discoverable-tool arguments must be a valid JSON object "
            f"string. Received: {raw_arguments!r}"
        ) from exc

    if not isinstance(parsed_arguments, dict):
        raise ValueError(
            "The discoverable-tool arguments must decode to a JSON object, "
            f"not {type(parsed_arguments).__name__}."
        )

    return json.dumps(
        parsed_arguments,
        ensure_ascii=False,
    )


async def _call_tau_bridge_tool(
    *,
    session_id: str,
    tau_bridge_url: str,
    tool_name: str,
    arguments: dict[str, Any],
    client: httpx.AsyncClient | None = None,
) -> Any:
    """Request a Tau-native tool call and await its actual ToolMessage result.

    The bridge endpoint no longer executes the registered tool directly. It
    publishes the request to cuga_remote_agent, which sends a native ToolCall
    to Tau. Tau executes the environment tool, and cuga_remote_agent resolves
    the bridge request with the resulting ToolMessage.

    From CUGA's perspective this remains an ordinary awaited function call.
    """

    url = (
        f"{tau_bridge_url}/sessions/"
        f"{session_id}/tools/{tool_name}/call"
    )

    _log("requesting Tau-native tool:", tool_name)
    _log("session_id:", session_id)
    _log("url:", url)
    _log("args:", arguments)

    async def _send_request(http_client: httpx.AsyncClient) -> Any:
        response = await http_client.post(
            url,
            json={"arguments": arguments},
        )

        _log("Tau bridge status:", response.status_code)
        _log("Tau bridge raw body:", response.text)

        response.raise_for_status()

        data = response.json()
        _log("Tau bridge parsed body:", data)

        error = data.get("error")
        if error:
            _log("Tau-native tool returned error:", error)
            raise RuntimeError(
                f"Tau tool '{tool_name}' failed: {error}"
            )

        result = data.get("result")
        _log("Tau-native tool result:", result)
        return result

    try:
        if client is not None:
            return await _send_request(client)

        timeout = httpx.Timeout(
            connect=10.0,
            read=_TAU_BRIDGE_READ_TIMEOUT_SECONDS,
            write=30.0,
            pool=10.0,
        )
        async with httpx.AsyncClient(timeout=timeout) as owned_client:
            return await _send_request(owned_client)

    except Exception as exc:
        _log(
            "Tau-native tool request failed:",
            tool_name,
            type(exc).__name__,
            exc,
        )
        raise


# ---------------------------------------------------------------------------
# Ordinary Tau tools
# ---------------------------------------------------------------------------


def make_remote_tau_tool(
    *,
    session_id: str,
    tau_bridge_url: str,
    openai_schema: dict[str, Any],
) -> StructuredTool:
    function_schema = openai_schema["function"]

    tool_name = function_schema["name"]
    description = _adapt_tool_description(
        tool_name,
        function_schema.get("description", tool_name),
    )
    parameters = function_schema.get(
        "parameters",
        {
            "type": "object",
            "properties": {},
        },
    )

    args_schema = _make_args_schema(
        tool_name,
        parameters,
    )

    _log("creating brokered remote Tau tool:", tool_name)
    _log("tool description:", description)
    _log("tool parameters:", parameters)

    async def _call_remote_tau_tool(**kwargs: Any) -> str:
        result = await _call_tau_bridge_tool(
            session_id=session_id,
            tau_bridge_url=tau_bridge_url,
            tool_name=tool_name,
            arguments=kwargs,
        )

        return _stringify_tool_result(result)

    return StructuredTool.from_function(
        coroutine=_call_remote_tau_tool,
        name=tool_name,
        description=description,
        args_schema=args_schema,
    )


# ---------------------------------------------------------------------------
# User discoverable tool handoff
# ---------------------------------------------------------------------------


class GiveDiscoverableUserToolArgs(BaseModel):
    discoverable_tool_name: str = Field(
        ...,
        description=(
            "The exact name of the user discoverable tool found in the "
            "knowledge base."
        ),
    )

    arguments: str | None = Field(
        default=None,
        description=(
            "Optional JSON object string containing concrete execution "
            "arguments to prefill for the user. Include this only when the "
            "knowledge base explicitly indicates that values should be "
            "prefilled and every supplied value is already known. Omit it "
            "when the user should supply the execution arguments."
        ),
    )


def make_give_discoverable_user_tool(
    *,
    session_id: str,
    tau_bridge_url: str,
    openai_schema: dict[str, Any],
) -> StructuredTool:
    """Create the user-tool handoff as a normal brokered Tau call.

    Unlike the old deferred implementation, this function does not return a
    placeholder and does not use a second pending-call queue. CUGA awaits the
    real result after Tau has recorded and executed give_discoverable_user_tool.

    The handoff preserves the distinction between omitted arguments and
    concrete prefilled arguments. The adapter never inserts an empty JSON
    object or placeholder values on CUGA's behalf.
    """

    function_schema = openai_schema["function"]

    original_description = function_schema.get(
        "description",
        _GIVE_USER_TOOL,
    )
    description = (
        f"{original_description.strip()}\n\n"
        "This is a Tau-native handoff. Always provide the exact discoverable "
        "tool name from the knowledge base. The optional arguments field is "
        "only for concrete execution values that should be prefilled for the "
        "user. Include it only when the knowledge base explicitly indicates "
        "that values should be prefilled and every value is already known "
        "from the conversation or prior tool results. Do not invent values, "
        "use placeholders such as '<your_user_id>', or include values that "
        "the user is expected to supply. When no concrete values should be "
        "prefilled, omit arguments entirely. Assign the result to a variable "
        "and print that variable as the final line; never use this call as a "
        "bare final await expression."
    )

    _log("creating brokered user discoverable tool:", _GIVE_USER_TOOL)
    _log("tool description:", description)
    _log("tool parameters:", GiveDiscoverableUserToolArgs.model_json_schema())

    async def _give_discoverable_user_tool(
        discoverable_tool_name: str,
        arguments: str | None = None,
    ) -> str:
        if not discoverable_tool_name.strip():
            raise ValueError(
                "discoverable_tool_name must be a non-empty string."
            )

        tau_arguments: dict[str, Any] = {
            "discoverable_tool_name": discoverable_tool_name,
        }

        if arguments is not None:
            stripped_arguments = arguments.strip()

            if stripped_arguments and stripped_arguments != "{}":
                tau_arguments["arguments"] = _normalize_arguments_json(
                    stripped_arguments
                )

        result = await _call_tau_bridge_tool(
            session_id=session_id,
            tau_bridge_url=tau_bridge_url,
            tool_name=_GIVE_USER_TOOL,
            arguments=tau_arguments,
        )

        return _stringify_tool_result(result)

    return StructuredTool.from_function(
        coroutine=_give_discoverable_user_tool,
        name=_GIVE_USER_TOOL,
        description=description,
        args_schema=GiveDiscoverableUserToolArgs,
    )


# ---------------------------------------------------------------------------
# Composite agent-discoverable tool
# ---------------------------------------------------------------------------


class ExecuteDiscoverableAgentToolArgs(BaseModel):
    agent_tool_name: str = Field(
        ...,
        description=(
            "The exact name of the agent discoverable tool found in the "
            "knowledge base."
        ),
    )

    arguments: str = Field(
        default="{}",
        description=(
            "A JSON object string containing the arguments required by the "
            "discoverable tool, for example: "
            "'{\"user_id\": \"abc123\"}'."
        ),
    )


def make_execute_discoverable_agent_tool(
    *,
    session_id: str,
    tau_bridge_url: str,
) -> StructuredTool:
    description = (
        "Unlock and execute an agent discoverable tool found in the "
        "knowledge base.\n\n"
        "Use this only when the knowledge base says that the assistant, "
        "agent, or an internal support employee should use a specialized "
        "tool. Do not use this for tools that the customer must execute. "
        "For a customer-facing discoverable tool, use "
        "give_discoverable_user_tool instead.\n\n"
        "This function automatically performs the required sequence:\n"
        "1. Unlock the named agent discoverable tool.\n"
        "2. Wait for Tau to execute and record the unlock.\n"
        "3. Execute the tool using the supplied JSON arguments.\n"
        "4. Wait for Tau to execute and record the tool call.\n\n"
        "Use the exact tool name and argument fields returned by the "
        "knowledge base. Do not invent tool names."
    )

    _log(
        "creating composite brokered Tau tool:",
        _EXECUTE_AGENT_TOOL,
    )

    async def _execute_discoverable_agent_tool(
        agent_tool_name: str,
        arguments: str = "{}",
    ) -> str:
        normalized_arguments = _normalize_arguments_json(arguments)

        _log(
            "executing discoverable agent tool:",
            agent_tool_name,
        )
        _log(
            "normalized discoverable arguments:",
            normalized_arguments,
        )

        timeout = httpx.Timeout(
            connect=10.0,
            read=_TAU_BRIDGE_READ_TIMEOUT_SECONDS,
            write=30.0,
            pool=10.0,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            unlock_result = await _call_tau_bridge_tool(
                session_id=session_id,
                tau_bridge_url=tau_bridge_url,
                tool_name=_UNLOCK_AGENT_TOOL,
                arguments={
                    "agent_tool_name": agent_tool_name,
                },
                client=client,
            )

            _log(
                "discoverable agent tool unlocked:",
                agent_tool_name,
            )
            _log("unlock result:", unlock_result)

            call_result = await _call_tau_bridge_tool(
                session_id=session_id,
                tau_bridge_url=tau_bridge_url,
                tool_name=_CALL_AGENT_TOOL,
                arguments={
                    "agent_tool_name": agent_tool_name,
                    "arguments": normalized_arguments,
                },
                client=client,
            )

        _log(
            "discoverable agent tool completed:",
            agent_tool_name,
        )

        return _stringify_tool_result(call_result)

    return StructuredTool.from_function(
        coroutine=_execute_discoverable_agent_tool,
        name=_EXECUTE_AGENT_TOOL,
        description=description,
        args_schema=ExecuteDiscoverableAgentToolArgs,
    )


# ---------------------------------------------------------------------------
# Tool-set construction
# ---------------------------------------------------------------------------


def make_remote_tau_tools(
    *,
    session_id: str,
    tau_bridge_url: str,
    tool_specs: list[dict[str, Any]],
) -> list[StructuredTool]:
    _log("creating remote Tau tools")
    _log("session_id:", session_id)
    _log("tau_bridge_url:", tau_bridge_url)
    _log("tool_specs count:", len(tool_specs))

    tool_names = [
        _get_tool_name(spec)
        for spec in tool_specs
    ]

    if len(tool_names) != len(set(tool_names)):
        duplicate_names = sorted(
            {
                name
                for name in tool_names
                if tool_names.count(name) > 1
            }
        )

        raise ValueError(
            "Duplicate Tau tool specifications received: "
            f"{duplicate_names}"
        )

    has_unlock_tool = _UNLOCK_AGENT_TOOL in tool_names
    has_call_tool = _CALL_AGENT_TOOL in tool_names

    if has_unlock_tool != has_call_tool:
        raise ValueError(
            "The Tau tool set must contain both "
            f"'{_UNLOCK_AGENT_TOOL}' and '{_CALL_AGENT_TOOL}', "
            "or neither of them."
        )

    if _EXECUTE_AGENT_TOOL in tool_names:
        raise ValueError(
            f"Tau already provides a tool named '{_EXECUTE_AGENT_TOOL}'. "
            "The server cannot add the composite tool using the same name."
        )

    tools: list[StructuredTool] = []
    composite_tool_added = False

    for spec in tool_specs:
        openai_schema = spec["openai_schema"]
        tool_name = _get_tool_name(spec)

        if tool_name == _GIVE_USER_TOOL:
            tools.append(
                make_give_discoverable_user_tool(
                    session_id=session_id,
                    tau_bridge_url=tau_bridge_url,
                    openai_schema=openai_schema,
                )
            )
            continue

        if tool_name == _UNLOCK_AGENT_TOOL:
            if has_call_tool and not composite_tool_added:
                tools.append(
                    make_execute_discoverable_agent_tool(
                        session_id=session_id,
                        tau_bridge_url=tau_bridge_url,
                    )
                )
                composite_tool_added = True

            _log(
                "hiding low-level tool from CUGA:",
                tool_name,
            )
            continue

        if tool_name == _CALL_AGENT_TOOL:
            _log(
                "hiding low-level tool from CUGA:",
                tool_name,
            )
            continue

        tools.append(
            make_remote_tau_tool(
                session_id=session_id,
                tau_bridge_url=tau_bridge_url,
                openai_schema=openai_schema,
            )
        )

    _log(
        "created tools:",
        [tool.name for tool in tools],
    )

    return tools