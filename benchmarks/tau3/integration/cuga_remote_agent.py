from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import Future
from typing import Any, Optional

import httpx
from pydantic import BaseModel, Field

from tau2.agent.base_agent import HalfDuplexAgent, ValidAgentInputMessage
from tau2.data_model.message import (
    AssistantMessage,
    Message,
    MultiToolMessage,
    ToolCall,
    ToolMessage,
)
from tau2.environment.tool import Tool

from tau2.agent.cuga_bridge_server import (
    ensure_tau_bridge_server,
    register_tau_session,
    resolve_pending_tau_tool_call,
    unregister_tau_session,
    wait_for_pending_tau_tool_call,
)


AUTO_CONTINUE_RECOVERY_FAILED_PREFIX = (
    "Auto-continue recovery failed: the agent repeatedly produced "
    "non-terminal natural-language responses instead of a valid next output."
)

BRIDGE_POLL_INTERVAL_SECONDS = 0.1


class CugaRemoteAgentState(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)


def _log(*args: Any) -> None:
    print("[cuga_remote]", *args, flush=True)


def _normalize_tools(tools: Any) -> list[Tool]:
    if isinstance(tools, dict):
        return list(tools.values())
    return list(tools or [])


def _dump_message(message: Any) -> dict[str, Any]:
    if hasattr(message, "model_dump"):
        return message.model_dump()
    if isinstance(message, dict):
        return message
    return {"role": "unknown", "content": str(message)}


def _raise_for_status_with_body(
    response: httpx.Response,
    context: str,
) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _log(context, "failed")
        _log("status:", response.status_code)
        _log("body:", response.text)
        raise exc


def _is_unrecoverable_cuga_error(content: str) -> bool:
    return content.strip().startswith(
        AUTO_CONTINUE_RECOVERY_FAILED_PREFIX
    )


def _parse_assistant_tool_calls(
    raw_tool_calls: Any,
    *,
    available_tool_names: set[str],
) -> list[ToolCall]:
    """Convert CUGA-server tool-call payloads into native Tau ToolCalls.

    This is retained as a compatibility path while the older server-side
    deferred-call mechanism is being removed. New ordinary tool calls should
    arrive through wait_for_pending_tau_tool_call instead.
    """

    if raw_tool_calls is None:
        return []

    if not isinstance(raw_tool_calls, list):
        raise RuntimeError(
            "CUGA /respond field 'tool_calls' must be a list. "
            f"Received: {type(raw_tool_calls).__name__}"
        )

    parsed_calls: list[ToolCall] = []
    seen_call_ids: set[str] = set()

    for index, raw_call in enumerate(raw_tool_calls):
        if not isinstance(raw_call, dict):
            raise RuntimeError(
                "Each CUGA tool call must be an object. "
                f"Item {index} was {type(raw_call).__name__}."
            )

        call_id = raw_call.get("id")
        tool_name = raw_call.get("name")
        arguments = raw_call.get("arguments", {})

        if not isinstance(call_id, str) or not call_id.strip():
            raise RuntimeError(
                "CUGA returned a tool call without a valid string id. "
                f"Item {index}: {raw_call}"
            )

        if call_id in seen_call_ids:
            raise RuntimeError(
                f"CUGA returned duplicate tool-call id {call_id!r}."
            )
        seen_call_ids.add(call_id)

        if not isinstance(tool_name, str) or not tool_name.strip():
            raise RuntimeError(
                "CUGA returned a tool call without a valid tool name. "
                f"Item {index}: {raw_call}"
            )

        if tool_name not in available_tool_names:
            raise RuntimeError(
                "CUGA requested a Tau-native tool that is not registered "
                f"for this session: {tool_name!r}. Available tools: "
                f"{sorted(available_tool_names)}"
            )

        if not isinstance(arguments, dict):
            raise RuntimeError(
                "CUGA tool-call arguments must be an object. "
                f"Tool {tool_name!r} received "
                f"{type(arguments).__name__}."
            )

        parsed_calls.append(
            ToolCall(
                id=call_id,
                name=tool_name,
                arguments=arguments,
                requestor="assistant",
            )
        )

    return parsed_calls


class CugaRemoteAgent(HalfDuplexAgent[CugaRemoteAgentState]):
    def __init__(
        self,
        tools: list[Tool],
        domain_policy: str,
        cuga_server_url: Optional[str] = None,
        tau_bridge_host: Optional[str] = None,
        tau_bridge_port: Optional[int] = None,
        **kwargs: Any,
    ):
        _log("__init__ started")
        _log("__init__ kwargs:", kwargs)

        super().__init__(
            tools=tools,
            domain_policy=domain_policy,
        )

        self.session_id = str(uuid.uuid4())
        self.cuga_server_url = (
            cuga_server_url
            or os.environ.get("CUGA_SERVER_URL")
            or "http://127.0.0.1:8765"
        )
        self.tau_bridge_host = tau_bridge_host or os.environ.get(
            "TAU_BRIDGE_HOST",
            "127.0.0.1",
        )
        self.tau_bridge_port = int(
            tau_bridge_port
            or os.environ.get("TAU_BRIDGE_PORT", "8766")
        )
        self.tau_bridge_url = (
            f"http://{self.tau_bridge_host}:{self.tau_bridge_port}"
        )

        self._tools_list = _normalize_tools(tools)
        self._available_tool_names = {
            tool.name for tool in self._tools_list
        }

        # A CUGA /respond request can span several Tau tool-call turns.
        # The request runs in a daemon thread while this agent returns each
        # pending ToolCall to Tau and later routes its ToolMessage back.
        self._active_respond_future: Future[httpx.Response] | None = None
        self._active_respond_thread: threading.Thread | None = None
        self._outstanding_tool_call_ids: set[str] = set()

        _log("ensuring tau bridge server")
        ensure_tau_bridge_server(
            host=self.tau_bridge_host,
            port=self.tau_bridge_port,
        )

        _log("registering tau session")
        register_tau_session(
            self.session_id,
            self._tools_list,
        )

        _log("creating CUGA session")
        self._create_cuga_session()

    def _create_cuga_session(self) -> None:
        tools_payload: list[dict[str, Any]] = []

        for tool in self._tools_list:
            openai_schema = tool.openai_schema
            function_schema = openai_schema.get("function", {})

            tools_payload.append(
                {
                    "name": tool.name,
                    "description": function_schema.get(
                        "description",
                        "",
                    ),
                    "openai_schema": openai_schema,
                }
            )

        payload = {
            "session_id": self.session_id,
            "domain_policy": self.domain_policy,
            "tau_bridge_url": self.tau_bridge_url,
            "tools": tools_payload,
        }

        response = httpx.post(
            f"{self.cuga_server_url}/sessions",
            json=payload,
            timeout=httpx.Timeout(
                connect=10,
                read=120,
                write=30,
                pool=10,
            ),
        )

        _raise_for_status_with_body(
            response,
            "POST /sessions",
        )

    def get_init_state(
        self,
        message_history: Optional[list[Message]] = None,
    ) -> CugaRemoteAgentState:
        messages = [
            _dump_message(message)
            for message in message_history or []
        ]
        return CugaRemoteAgentState(messages=messages)

    def _post_cuga_respond(
        self,
        *,
        message_payload: dict[str, Any],
        history_payload: list[dict[str, Any]],
    ) -> httpx.Response:
        """Run one potentially long-lived CUGA /respond request."""

        return httpx.post(
            (
                f"{self.cuga_server_url}/sessions/"
                f"{self.session_id}/respond"
            ),
            json={
                "message": message_payload,
                "history": history_payload,
            },
            # CUGA may remain suspended while Tau executes several tools.
            # The benchmark/orchestrator owns the overall timeout.
            timeout=httpx.Timeout(
                connect=10,
                read=None,
                write=30,
                pool=10,
            ),
        )

    def _start_cuga_respond(
        self,
        *,
        message_payload: dict[str, Any],
        history_payload: list[dict[str, Any]],
    ) -> None:
        if (
            self._active_respond_future is not None
            and not self._active_respond_future.done()
        ):
            raise RuntimeError(
                "Cannot start a new CUGA /respond request while another "
                "request is still active."
            )

        future: Future[httpx.Response] = Future()

        def run_request() -> None:
            try:
                response = self._post_cuga_respond(
                    message_payload=message_payload,
                    history_payload=history_payload,
                )
                future.set_result(response)
            except BaseException as exc:
                future.set_exception(exc)

        thread = threading.Thread(
            target=run_request,
            daemon=True,
            name=f"cuga-respond-{self.session_id[:8]}",
        )

        self._active_respond_future = future
        self._active_respond_thread = thread
        thread.start()

    def _make_pending_tool_message(self, pending: Any) -> AssistantMessage:
        tool_name = pending.name
        call_id = pending.call_id
        arguments = pending.arguments

        if tool_name not in self._available_tool_names:
            raise RuntimeError(
                "CUGA requested a Tau-native tool that is not registered "
                f"for this session: {tool_name!r}. Available tools: "
                f"{sorted(self._available_tool_names)}"
            )

        if call_id in self._outstanding_tool_call_ids:
            raise RuntimeError(
                f"Duplicate pending Tau tool-call id {call_id!r}."
            )

        self._outstanding_tool_call_ids.add(call_id)

        tool_call = ToolCall(
            id=call_id,
            name=tool_name,
            arguments=dict(arguments),
            requestor="assistant",
        )

        _log("sending Tau-native tool call:", tool_call.model_dump())

        # Tau's half-duplex protocol requires either text or tool calls,
        # not both. Empty content is valid here because tool_calls is set.
        return AssistantMessage.text(
            "",
            tool_calls=[tool_call],
        )

    def _consume_completed_cuga_response(self) -> AssistantMessage:
        future = self._active_respond_future
        if future is None or not future.done():
            raise RuntimeError("No completed CUGA /respond request exists.")

        self._active_respond_future = None
        self._active_respond_thread = None

        response = future.result()

        _raise_for_status_with_body(
            response,
            "POST /respond",
        )

        data = response.json()
        content = data.get("content")

        if content is None:
            raise RuntimeError(
                "CUGA /respond response did not contain 'content'. "
                f"Body: {data}"
            )

        content_text = str(content)

        if _is_unrecoverable_cuga_error(content_text):
            _log(
                "unrecoverable CUGA error:",
                content_text,
            )

            self._cleanup_session()
            raise RuntimeError(content_text)

        # Compatibility path for the old server-side pending-call queue.
        # Once remote_tau_tools.py is fully migrated, this should normally
        # remain empty and can be removed.
        assistant_tool_calls = _parse_assistant_tool_calls(
            data.get("tool_calls"),
            available_tool_names=self._available_tool_names,
        )

        if assistant_tool_calls:
            for call in assistant_tool_calls:
                if call.id in self._outstanding_tool_call_ids:
                    raise RuntimeError(
                        "CUGA returned a duplicate tool call through both "
                        f"bridge paths: {call.id!r}."
                    )
                self._outstanding_tool_call_ids.add(call.id)

        _log("assistant content:", content_text)
        _log(
            "assistant compatibility tool calls:",
            [call.model_dump() for call in assistant_tool_calls],
        )

        return AssistantMessage.text(
            content_text,
            tool_calls=assistant_tool_calls or None,
        )

    def _wait_for_next_cuga_output(self) -> AssistantMessage:
        """Wait for either a pending Tau tool request or final CUGA text."""

        while True:
            future = self._active_respond_future
            if future is None:
                raise RuntimeError(
                    "No active CUGA /respond request while waiting for output."
                )

            if future.done():
                return self._consume_completed_cuga_response()

            pending = wait_for_pending_tau_tool_call(
                self.session_id,
                timeout=BRIDGE_POLL_INTERVAL_SECONDS,
            )

            if pending is not None:
                return self._make_pending_tool_message(pending)

    def _resolve_tool_message(self, message: ToolMessage) -> None:
        if message.requestor != "assistant":
            raise RuntimeError(
                "CugaRemoteAgent received a tool result whose requestor "
                f"was {message.requestor!r}, expected 'assistant'."
            )

        if message.id not in self._outstanding_tool_call_ids:
            raise RuntimeError(
                "CugaRemoteAgent received a ToolMessage for an unknown "
                f"or already-resolved call id: {message.id!r}."
            )

        error_text = None
        result: Any = message.content

        if message.error:
            error_text = message.content or "Tau tool execution failed"
            result = None

        _log(
            "routing Tau tool result back to CUGA:",
            {
                "call_id": message.id,
                "error": error_text,
                "result": result,
            },
        )

        resolve_pending_tau_tool_call(
            session_id=self.session_id,
            call_id=message.id,
            result=result,
            error=error_text,
        )

        self._outstanding_tool_call_ids.remove(message.id)

    def _record_input_message(
        self,
        message: ValidAgentInputMessage,
        state: CugaRemoteAgentState,
    ) -> None:
        if isinstance(message, MultiToolMessage):
            state.messages.extend(
                _dump_message(tool_message)
                for tool_message in message.tool_messages
            )
            return

        state.messages.append(_dump_message(message))

    def _resolve_incoming_tool_results(
        self,
        message: ValidAgentInputMessage,
    ) -> None:
        if isinstance(message, ToolMessage):
            self._resolve_tool_message(message)
            return

        if isinstance(message, MultiToolMessage):
            for tool_message in message.tool_messages:
                self._resolve_tool_message(tool_message)
            return

        raise RuntimeError(
            "Expected ToolMessage or MultiToolMessage while a CUGA "
            "request was suspended on a Tau tool call. "
            f"Received {type(message).__name__}."
        )

    def _cleanup_session(self) -> None:
        try:
            unregister_tau_session(self.session_id)
        except Exception as exc:
            _log(
                "unregister_tau_session failed:",
                type(exc).__name__,
                exc,
            )

        try:
            response = httpx.delete(
                f"{self.cuga_server_url}/sessions/{self.session_id}",
                timeout=httpx.Timeout(
                    connect=10,
                    read=10,
                    write=10,
                    pool=10,
                ),
            )
            _raise_for_status_with_body(
                response,
                "DELETE /sessions",
            )
        except Exception as exc:
            _log(
                "DELETE /sessions failed:",
                type(exc).__name__,
                exc,
            )

        self._active_respond_future = None
        self._active_respond_thread = None
        self._outstanding_tool_call_ids.clear()

    def generate_next_message(
        self,
        message: ValidAgentInputMessage,
        state: CugaRemoteAgentState,
    ) -> tuple[AssistantMessage, CugaRemoteAgentState]:
        message_payload = _dump_message(message)

        _log(
            "incoming role:",
            message_payload.get("role"),
        )
        _log(
            "incoming content:",
            message_payload.get("content"),
        )

        active_future = self._active_respond_future
        has_active_request = (
            active_future is not None and not active_future.done()
        )

        # Snapshot the history before recording the new customer message,
        # because /respond receives the current message separately.
        history_payload = list(state.messages)
        self._record_input_message(message, state)

        if has_active_request:
            # The only valid re-entry while /respond is active is the Tau
            # ToolMessage corresponding to the ToolCall returned previously.
            self._resolve_incoming_tool_results(message)
        else:
            if isinstance(message, (ToolMessage, MultiToolMessage)):
                raise RuntimeError(
                    "Received a Tau ToolMessage but no CUGA /respond request "
                    "is currently waiting for a tool result."
                )

            self._start_cuga_respond(
                message_payload=message_payload,
                history_payload=history_payload,
            )

        assistant_message = self._wait_for_next_cuga_output()
        state.messages.append(assistant_message.model_dump())

        _log(
            "assistant tool calls:",
            [
                call.model_dump()
                for call in assistant_message.tool_calls or []
            ],
        )

        return assistant_message, state

    def stop(
        self,
        message: Optional[ValidAgentInputMessage] = None,
        state: Optional[CugaRemoteAgentState] = None,
    ) -> None:
        self._cleanup_session()


def create_cuga_remote_agent(
    tools: Any,
    domain_policy: str,
    **kwargs: Any,
) -> CugaRemoteAgent:
    return CugaRemoteAgent(
        tools=tools,
        domain_policy=domain_policy,
        **kwargs,
    )