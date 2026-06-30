"""Tests for the OpenCode LLM capture reverse-proxy.

Starts a FAKE upstream (a Starlette app returning canned chat completions — one non-streaming
JSON, one SSE stream), puts the ``LLMCaptureProxy`` in front of it, sends requests through the
proxy with ``httpx``, and asserts that:

  1. the client response passes through intact (streaming preserved),
  2. the per-call JSONL capture file holds the request body + the response
     (parsed body for non-streaming; reassembled message + raw SSE + usage for streaming),
  3. the ``Authorization`` header is redacted in the capture but forwarded upstream.

No AppWorld servers or the ``opencode`` binary are required.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

APPWORLD_DIR = Path(__file__).resolve().parents[2]
if str(APPWORLD_DIR) not in sys.path:
    sys.path.insert(0, str(APPWORLD_DIR))

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from opencode.llm_proxy import LLMCaptureProxy


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Server:
    """Run a Starlette app under uvicorn in a daemon thread (context manager)."""

    def __init__(self, app) -> None:
        self.port = _free_port()
        cfg = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        self._server = uvicorn.Server(cfg)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "_Server":
        self._thread.start()
        for _ in range(200):
            if self._server.started:
                break
            time.sleep(0.02)
        return self

    def __exit__(self, *exc) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)


# Mutable record of what the fake upstream actually received (proves forwarding).
SEEN: dict = {}


def _make_upstream() -> Starlette:
    async def chat(request):
        body = json.loads(await request.body())
        SEEN["auth"] = request.headers.get("authorization")
        if body.get("stream"):

            async def gen():
                for tok in ["Hel", "lo ", "world"]:
                    yield f'data: {json.dumps({"choices": [{"delta": {"content": tok}}]})}\n\n'.encode()
                final = {
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3},
                }
                yield f"data: {json.dumps(final)}\n\n".encode()
                yield b"data: [DONE]\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")

        return JSONResponse(
            {
                "id": "cmpl-1",
                "choices": [{"message": {"role": "assistant", "content": "Hello world"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            }
        )

    return Starlette(routes=[Route("/v1/chat/completions", chat, methods=["POST"])])


def _only_record(capture_path: Path) -> dict:
    lines = [ln for ln in capture_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected exactly one capture record, got {len(lines)}"
    return json.loads(lines[0])


def test_non_streaming_passthrough_and_capture(tmp_path):
    SEEN.clear()
    cap = tmp_path / "calls.jsonl"
    with _Server(_make_upstream()) as up:
        proxy = LLMCaptureProxy(upstream_base_url=up.base + "/v1", capture_path=str(cap))
        proxy_base = proxy.start()
        try:
            assert proxy_base.endswith("/v1")  # base path preserved for OpenCode
            req_body = {
                "model": "m",
                "messages": [
                    {"role": "system", "content": "SYS PROMPT"},
                    {"role": "user", "content": "hi"},
                ],
                "stream": False,
            }
            r = httpx.post(
                proxy_base + "/chat/completions",
                json=req_body,
                headers={"Authorization": "Bearer sk-SECRET123"},
                timeout=10,
            )
        finally:
            proxy.stop()

    # pass-through intact
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "Hello world"
    # the real auth header reached upstream (forwarded, not dropped)
    assert SEEN["auth"] == "Bearer sk-SECRET123"

    rec = _only_record(cap)
    assert rec["method"] == "POST"
    assert rec["path"] == "/v1/chat/completions"
    assert rec["status"] == 200
    assert rec["stream"] is False
    # what we SEND
    assert rec["request"]["messages"][0]["content"] == "SYS PROMPT"
    # what we RECEIVE
    assert rec["response"]["body"]["choices"][0]["message"]["content"] == "Hello world"
    # redaction: secret nowhere in the file, header masked in the record
    assert "sk-SECRET123" not in cap.read_text()
    assert rec["request_headers"]["authorization"] == "***REDACTED***"


def test_streaming_passthrough_and_capture(tmp_path):
    SEEN.clear()
    cap = tmp_path / "calls.jsonl"
    with _Server(_make_upstream()) as up:
        proxy = LLMCaptureProxy(upstream_base_url=up.base + "/v1", capture_path=str(cap))
        proxy_base = proxy.start()
        try:
            req_body = {"model": "m", "messages": [{"role": "user", "content": "hi"}], "stream": True}
            with httpx.stream(
                "POST",
                proxy_base + "/chat/completions",
                json=req_body,
                headers={"Authorization": "Bearer sk-SECRET123"},
                timeout=10,
            ) as resp:
                received = b"".join(resp.iter_raw()).decode()
        finally:
            proxy.stop()

    # client received the full SSE stream
    assert "Hel" in received and "world" in received and "[DONE]" in received

    rec = _only_record(cap)
    assert rec["stream"] is True
    # reassembled assistant message from the deltas
    assert rec["response"]["reassembled"]["content"] == "Hello world"
    # raw chunks preserved for byte-fidelity
    assert any("[DONE]" in chunk for chunk in rec["response"]["raw_sse"])
    # usage extracted from the stream
    assert rec["response"]["usage"]["completion_tokens"] == 3
    assert "sk-SECRET123" not in cap.read_text()
