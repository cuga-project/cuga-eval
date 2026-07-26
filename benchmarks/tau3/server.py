from __future__ import annotations

import inspect
import traceback
from dataclasses import dataclass
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException

from cuga import CugaAgent
from benchmarks.tau3.protocol import (
    CreateCugaSessionRequest,
    CreateCugaSessionResponse,
    CugaRespondRequest,
    CugaRespondResponse,
)
from benchmarks.tau3.remote_tau_tools import make_remote_tau_tools


@dataclass
class CugaSessionState:
    agent: CugaAgent
    tools: list[Any]
    history: list[dict[str, Any]]


app = FastAPI(title="CUGA Tau Adapter")

_SESSIONS: dict[str, CugaSessionState] = {}


def _log(*args: Any) -> None:
    print("[server]", *args, flush=True)


def _extract_text_from_tau_message(message: dict[str, Any]) -> str:
    """Convert a Tau input message into text that CUGA can consume.

    Under the broker architecture, Tau ToolMessages are handled by
    cuga_remote_agent and returned directly to the suspended remote tool.
    Therefore, /respond should normally receive only the message that starts a
    new CUGA turn, such as a user message.
    """

    content = message.get("content")
    if content is not None:
        return str(content)

    return str(message)


def _extract_message_content(message: Any) -> str | None:
    content = getattr(message, "content", None)
    if content is not None:
        return str(content)

    if isinstance(message, dict):
        dict_content = message.get("content")
        if dict_content is not None:
            return str(dict_content)

    return None


def _extract_content_from_cuga_result(result: Any) -> str:
    """Extract the final natural-language answer from common CUGA results."""

    if isinstance(result, str):
        return result

    if isinstance(result, dict):
        for key in ("content", "answer", "final_answer"):
            value = result.get(key)
            if value is not None:
                return str(value)

        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            content = _extract_message_content(messages[-1])
            if content is not None:
                return content

    if isinstance(result, list) and result:
        content = _extract_message_content(result[-1])
        if content is not None:
            return content

    for attr_name in ("content", "answer", "final_answer"):
        value = getattr(result, attr_name, None)
        if value is not None:
            return str(value)

    messages = getattr(result, "messages", None)
    if isinstance(messages, list) and messages:
        content = _extract_message_content(messages[-1])
        if content is not None:
            return content

    return str(result)


def _invoke_accepts_thread_id(agent: CugaAgent) -> bool:
    """Check support before invocation to avoid retrying partial execution."""

    try:
        signature = inspect.signature(agent.invoke)
    except (TypeError, ValueError):
        # CugaAgent versions used by this adapter normally support thread_id.
        # If inspection is unavailable, prefer the stateful invocation path.
        return True

    if "thread_id" in signature.parameters:
        return True

    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


async def _invoke_cuga_agent(
    agent: CugaAgent,
    user_text: str,
    session_id: str,
) -> Any:
    if _invoke_accepts_thread_id(agent):
        result = agent.invoke(
            user_text,
            thread_id=session_id,
        )
    else:
        _log(
            "CugaAgent.invoke does not accept thread_id; "
            "using invoke(user_text)"
        )
        result = agent.invoke(user_text)

    if inspect.isawaitable(result):
        result = await result

    return result


def _build_special_instructions(domain_policy: str) -> str:
    return (
        "You are being evaluated inside tau-bench.\n"
        "Follow the domain policy exactly.\n"
        "Use the provided external tools whenever the policy or knowledge "
        "base requires an action or lookup.\n"
        "Do not mention implementation details about the bridge.\n\n"
        f"Domain policy:\n{domain_policy}\n\n"
        "Adapter-specific discoverable-tool mapping:\n"
        "These instructions override earlier low-level instructions about "
        "separately unlocking and calling an agent discoverable tool.\n"
        "- For a specialized tool used by the assistant, support agent, or "
        "internal employee, call execute_discoverable_agent_tool with the "
        "exact tool name and JSON arguments from the knowledge base. It "
        "automatically unlocks and executes the tool.\n"
        "- Do not call unlock_discoverable_agent_tool or "
        "call_discoverable_agent_tool. They are intentionally not exposed.\n"
        "- For a tool that the customer must execute, call "
        "give_discoverable_user_tool with the exact tool name and arguments "
        "from the knowledge base. The outer Tau runtime executes and records "
        "the handoff, and the function returns the real Tau result. Call it "
        "only once for the same requested action.\n"
        "- Do not use execute_discoverable_agent_tool for a customer-facing "
        "tool.\n"
        "- Never invent a discoverable tool name or arguments. Search the "
        "knowledge base first.\n"
        "- If a tool returns an error, do not claim that the requested action "
        "succeeded.\n"
        "Critical execution rule:\n"
        "- Never describe an internal action that you have not executed.\n"
        "- Statements such as 'I will verify', 'I will search', or "
        "'I will retrieve' are invalid.\n"
        "- When an internal lookup or action is required and the necessary "
        "arguments are available, your next output must be executable Python "
        "that awaits the relevant tool and ends with print().\n"
        "When the domain policy requires information from a tool and the required "
        "arguments are available, execute the appropriate tool instead of"
        "describing the intended action.\n"
        "Tau tool-result contract:\n"
        "- Every external Tau tool returns a human-readable text "
        "observation.\n"
        "- Treat every returned tool value as opaque text, even when the "
        "tool performs a database lookup or returns multiple records.\n"
        "- Never assume a tool result is a dictionary, list, JSON object, "
        "or typed Python object.\n"
        "- Never call .get(), .items(), .keys(), access attributes, or "
        "index a tool result by field name.\n"
        "- A Python block may contain multiple independent tool calls.\n"
        "- A Python block must not contain a later tool call whose arguments "
        "depend on information returned by an earlier tool call in that "
        "same block.\n"
        "- For dependent calls, call the first tool, assign its observation "
        "to a descriptive variable, print it, and end the code block.\n"
        "- After observing the printed text, reason over it and generate a "
        "new Python block containing the dependent tool call with explicit "
        "argument values.\n"
        "- Do not pass an entire human-readable tool response into another "
        "tool merely by applying str() to it.\n"
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sessions", response_model=CreateCugaSessionResponse)
def create_session(
    request: CreateCugaSessionRequest,
) -> CreateCugaSessionResponse:
    try:
        if request.session_id in _SESSIONS:
            _log("replacing existing CUGA session:", request.session_id)
            _SESSIONS.pop(request.session_id, None)

        remote_tools = make_remote_tau_tools(
            session_id=request.session_id,
            tau_bridge_url=request.tau_bridge_url,
            tool_specs=[tool.model_dump() for tool in request.tools],
        )

        cuga_agent = CugaAgent(
            tool_mode="external",
            tools=remote_tools,
            special_instructions=_build_special_instructions(
                request.domain_policy
            ),
            enable_knowledge=False,
            enable_skills=False,
        )

        _SESSIONS[request.session_id] = CugaSessionState(
            agent=cuga_agent,
            tools=remote_tools,
            history=[],
        )

        _log("==== CUGA /sessions ====")
        _log("session_id:", request.session_id)
        _log("remote_tools count:", len(remote_tools))
        _log("remote tool names:", [tool.name for tool in remote_tools])
        _log("cuga_agent type:", type(cuga_agent))

        return CreateCugaSessionResponse(
            session_id=request.session_id,
        )

    except Exception as exc:
        _SESSIONS.pop(request.session_id, None)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to create CUGA session: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc


@app.post(
    "/sessions/{session_id}/respond",
    response_model=CugaRespondResponse,
)
async def respond(
    session_id: str,
    request: CugaRespondRequest,
) -> CugaRespondResponse:
    session = _SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown session {session_id}",
        )

    try:
        agent = session.agent

        _log("==== CUGA /respond ====")
        _log("session_id:", session_id)
        _log("incoming message:", request.message)
        _log("incoming history length:", len(request.history))

        if not hasattr(agent, "invoke"):
            raise TypeError(
                "Stored session agent is not a CugaAgent-like object. "
                f"Got {type(agent)} with value: {agent}"
            )

        user_text = _extract_text_from_tau_message(request.message)
        _log("extracted user_text:", user_text)

        # This invocation may remain suspended while one or more remote tools
        # are sent to Tau and their ToolMessages are routed back through the
        # broker. That is expected: cuga_remote_agent keeps this HTTP request
        # alive in a background thread until CUGA produces its final answer.
        result = await _invoke_cuga_agent(
            agent=agent,
            user_text=user_text,
            session_id=session_id,
        )
        content = _extract_content_from_cuga_result(result)

        _log("cuga result type:", type(result))
        _log("extracted content:", content)

        session.history.append(request.message)
        session.history.append(
            {
                "role": "assistant",
                "content": content,
            }
        )

        # Tool calls are no longer returned by this endpoint. They are emitted
        # live by cuga_remote_agent when the bridge publishes a pending call.
        return CugaRespondResponse(content=content)

    except HTTPException:
        raise

    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to get CUGA response: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, str]:
    _SESSIONS.pop(session_id, None)
    return {"status": "deleted"}


def main() -> None:
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8765,
        reload=False,
        log_level="debug",
    )


if __name__ == "__main__":
    main()