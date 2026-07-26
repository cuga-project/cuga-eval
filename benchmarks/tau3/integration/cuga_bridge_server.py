from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


# How long the CUGA-side remote tool call may wait for Tau to execute it.
#
# This is deliberately generous because the call must travel through:
# CUGA -> bridge -> cuga_remote_agent -> Tau -> cuga_remote_agent -> bridge.
TOOL_RESULT_TIMEOUT_SECONDS = 300.0


class TauToolCallRequest(BaseModel):
    arguments: dict[str, Any]


class TauToolCallResponse(BaseModel):
    result: Any = None
    error: str | None = None


class TauToolResultRequest(BaseModel):
    result: Any = None
    error: str | None = None


@dataclass(frozen=True)
class PendingTauToolCall:
    """
    Public representation consumed by cuga_remote_agent.

    cuga_remote_agent converts this object into a Tau AssistantMessage
    containing a ToolCall with the same call_id, name, and arguments.
    """

    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class _PendingCallState:
    """
    Internal state for one tool call while remote_tau_tools is awaiting it.
    """

    request: PendingTauToolCall
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: str | None = None
    completed: bool = False


@dataclass
class _TauSession:
    tools: dict[str, Any]

    # The condition protects pending_call_ids, pending_calls, and closed.
    condition: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock())
    )

    # Calls that have not yet been sent to Tau by cuga_remote_agent.
    pending_call_ids: deque[str] = field(default_factory=deque)

    # All calls that have been submitted but whose CUGA-side HTTP request
    # has not yet completed.
    pending_calls: dict[str, _PendingCallState] = field(default_factory=dict)

    closed: bool = False


app = FastAPI(title="Tau Tool Bridge")

_SESSIONS: dict[str, _TauSession] = {}
_SESSIONS_LOCK = threading.RLock()


def _normalize_tools(tools: Any) -> list[Any]:
    if isinstance(tools, dict):
        return list(tools.values())
    return list(tools or [])


def _get_session(session_id: str) -> _TauSession:
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(session_id)

    if session is None:
        raise KeyError(f"Unknown session {session_id}")

    return session


def register_tau_session(session_id: str, tools: Any) -> None:
    """
    Register the Tau tools available for a CUGA evaluation session.

    The actual tool objects are retained for schema listing and validation.
    They are no longer executed by the bridge endpoint.
    """

    tools_list = _normalize_tools(tools)
    new_session = _TauSession(
        tools={tool.name: tool for tool in tools_list},
    )

    # Close an existing session with the same ID before replacing it.
    unregister_tau_session(session_id)

    with _SESSIONS_LOCK:
        _SESSIONS[session_id] = new_session


def unregister_tau_session(session_id: str) -> None:
    """
    Remove a session and unblock any CUGA calls still awaiting Tau results.
    """

    with _SESSIONS_LOCK:
        session = _SESSIONS.pop(session_id, None)

    if session is None:
        return

    with session.condition:
        session.closed = True

        for pending in session.pending_calls.values():
            if pending.completed:
                continue

            pending.error = f"Tau session {session_id} was closed"
            pending.completed = True
            pending.done.set()

        session.pending_call_ids.clear()
        session.condition.notify_all()


def wait_for_pending_tau_tool_call(
    session_id: str,
    timeout: float | None = None,
) -> PendingTauToolCall | None:
    """
    Wait for CUGA to request a Tau-native tool call.

    This function is intended to be called by cuga_remote_agent. Since it is
    blocking, asynchronous agent code should call it through asyncio.to_thread:

        pending = await asyncio.to_thread(
            wait_for_pending_tau_tool_call,
            session_id,
            timeout,
        )

    Returning the request removes it from the delivery queue, but the call
    remains in pending_calls until its result is resolved and returned to CUGA.
    """

    session = _get_session(session_id)
    deadline = None if timeout is None else time.monotonic() + timeout

    with session.condition:
        while not session.pending_call_ids and not session.closed:
            if deadline is None:
                session.condition.wait()
                continue

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None

            session.condition.wait(timeout=remaining)

        if session.closed:
            return None

        call_id = session.pending_call_ids.popleft()
        pending = session.pending_calls.get(call_id)

        # This should not normally happen, but tolerate a call being cancelled
        # immediately before it is delivered.
        if pending is None:
            return None

        return pending.request


def resolve_pending_tau_tool_call(
    session_id: str,
    call_id: str,
    *,
    result: Any = None,
    error: str | None = None,
) -> None:
    """
    Supply the ToolMessage result returned by Tau.

    This resolves the await inside remote_tau_tools and allows CUGA's generated
    Python execution to continue.
    """

    session = _get_session(session_id)

    with session.condition:
        pending = session.pending_calls.get(call_id)

        if pending is None:
            raise KeyError(
                f"Unknown pending tool call {call_id} "
                f"for session {session_id}"
            )

        if pending.completed:
            raise RuntimeError(
                f"Tool call {call_id} for session {session_id} "
                "has already been resolved"
            )

        pending.result = result
        pending.error = error
        pending.completed = True
        pending.done.set()


def get_pending_tau_tool_call_count(session_id: str) -> int:
    """
    Debug helper used to inspect how many calls are awaiting Tau execution.
    """

    session = _get_session(session_id)

    with session.condition:
        return len(session.pending_call_ids)


def _submit_and_wait_for_tau_tool_call(
    session_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    timeout: float = TOOL_RESULT_TIMEOUT_SECONDS,
) -> TauToolCallResponse:
    """
    Register a CUGA tool request and block until cuga_remote_agent routes the
    corresponding Tau ToolMessage back through resolve_pending_tau_tool_call.
    """

    session = _get_session(session_id)

    if tool_name not in session.tools:
        raise KeyError(f"Unknown tool {tool_name}")

    call_id = f"call_{uuid.uuid4().hex}"
    pending = _PendingCallState(
        request=PendingTauToolCall(
            call_id=call_id,
            name=tool_name,
            arguments=dict(arguments),
        )
    )

    with session.condition:
        if session.closed:
            return TauToolCallResponse(
                result=None,
                error=f"Tau session {session_id} is closed",
            )

        session.pending_calls[call_id] = pending
        session.pending_call_ids.append(call_id)
        session.condition.notify_all()

    completed = pending.done.wait(timeout=timeout)

    if not completed:
        with session.condition:
            session.pending_calls.pop(call_id, None)

            try:
                session.pending_call_ids.remove(call_id)
            except ValueError:
                # The request may already have been delivered to
                # cuga_remote_agent.
                pass

        return TauToolCallResponse(
            result=None,
            error=(
                f"Timed out after {timeout:.1f} seconds waiting for Tau "
                f"to execute tool {tool_name!r} "
                f"(call_id={call_id})"
            ),
        )

    with session.condition:
        session.pending_calls.pop(call_id, None)

    return TauToolCallResponse(
        result=pending.result,
        error=pending.error,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sessions/{session_id}/tools")
def list_tools(session_id: str) -> list[dict[str, Any]]:
    try:
        session = _get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return [
        {
            "name": tool.name,
            "openai_schema": tool.openai_schema,
        }
        for tool in session.tools.values()
    ]


@app.post(
    "/sessions/{session_id}/tools/{tool_name}/call",
    response_model=TauToolCallResponse,
)
def call_tool(
    session_id: str,
    tool_name: str,
    request: TauToolCallRequest,
) -> TauToolCallResponse:
    """
    Called by remote_tau_tools inside the CUGA server.

    Unlike the previous implementation, this endpoint does not execute the
    registered tool. It waits for the outer Tau loop to execute the call.
    """

    try:
        return _submit_and_wait_for_tau_tool_call(
            session_id=session_id,
            tool_name=tool_name,
            arguments=request.arguments,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        return TauToolCallResponse(
            result=None,
            error=f"{type(exc).__name__}: {exc}",
        )


@app.post(
    "/sessions/{session_id}/tool-results/{call_id}",
    response_model=dict[str, str],
)
def submit_tool_result(
    session_id: str,
    call_id: str,
    request: TauToolResultRequest,
) -> dict[str, str]:
    """
    Optional HTTP form of resolve_pending_tau_tool_call.

    cuga_remote_agent is in the same process and can call the Python function
    directly. This endpoint is retained for debugging and future process
    separation.
    """

    try:
        resolve_pending_tau_tool_call(
            session_id=session_id,
            call_id=call_id,
            result=request.result,
            error=request.error,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"status": "resolved"}


_server_started = False
_SERVER_LOCK = threading.Lock()


def ensure_tau_bridge_server(
    host: str = "127.0.0.1",
    port: int = 8766,
) -> None:
    global _server_started

    with _SERVER_LOCK:
        if _server_started:
            return

        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
        )
        server = uvicorn.Server(config)

        thread = threading.Thread(
            target=server.run,
            daemon=True,
            name="tau-tool-bridge",
        )
        thread.start()

        time.sleep(0.5)
        _server_started = True