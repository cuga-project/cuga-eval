"""A transparent logging reverse-proxy for OpenCode's LLM traffic.

OpenCode makes its own LLM calls directly to the configured endpoint, so the AppWorld harness
never sees the request it sends or the response it receives. This proxy sits between OpenCode and
the real gateway: OpenCode's provider ``baseURL`` is pointed at the proxy, which forwards every
request to the real gateway (preserving method, path, query, headers, body), streams the response
straight back in real time, and tees both request and response into a per-task JSONL file.

One JSON object is appended per LLM call::

    {"ts", "method", "path", "status", "latency_ms", "stream",
     "request_headers" (Authorization redacted), "request" (full body),
     "response": {"body"} | {"raw_sse", "reassembled", "usage"}}

``Authorization`` / api-key headers are forwarded upstream but redacted in the capture file.
"""

from __future__ import annotations

import contextlib
import json
import socket
import threading
import time
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx
import uvicorn
from loguru import logger
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route

# Headers redacted in the capture file (still forwarded upstream so auth works).
_SENSITIVE_HEADERS = {"authorization", "api-key", "x-api-key", "openai-api-key"}
# Request headers not to forward (let httpx set them correctly for the upstream connection).
# Stripping accept-encoding makes upstream return plaintext, so captures are readable and the
# bytes we stream back are the bytes we record.
_DROP_REQUEST_HEADERS = {"host", "content-length", "accept-encoding"}
# Response headers not to pass back (we re-stream the body, so length/encoding must be recomputed).
_DROP_RESPONSE_HEADERS = {"content-length", "content-encoding", "transfer-encoding", "connection"}


def _free_port(host: str = "127.0.0.1") -> int:
    s = socket.socket()
    s.bind((host, 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _try_json(raw: bytes) -> Optional[Any]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return None


def _redact_headers(headers: Any) -> dict[str, str]:
    return {
        k.lower(): ("***REDACTED***" if k.lower() in _SENSITIVE_HEADERS else v)
        for k, v in headers.items()
    }


def _reassemble_sse(text: str) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Concatenate OpenAI-style streaming ``data:`` deltas into one assistant message + usage."""
    content_parts: list[str] = []
    tool_calls: dict[int, dict[str, Any]] = {}
    usage: Optional[dict[str, Any]] = None

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            evt = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(evt, dict):
            continue
        if isinstance(evt.get("usage"), dict):
            usage = evt["usage"]
        for choice in evt.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                content_parts.append(str(delta["content"]))
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = tool_calls.setdefault(
                    idx,
                    {"id": tc.get("id"), "type": tc.get("type", "function"),
                     "function": {"name": "", "arguments": ""}},
                )
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]
                if tc.get("id"):
                    slot["id"] = tc["id"]

    reassembled: dict[str, Any] = {"role": "assistant", "content": "".join(content_parts)}
    if tool_calls:
        reassembled["tool_calls"] = [tool_calls[i] for i in sorted(tool_calls)]
    return reassembled, usage


class LLMCaptureProxy:
    """Forward LLM traffic to ``upstream_base_url`` and tee each call into ``capture_path``.

    Usage::

        proxy = LLMCaptureProxy(upstream_base_url="https://gw/v1", capture_path="calls.jsonl")
        base = proxy.start()      # -> "http://127.0.0.1:<port>/v1"  (use as OpenCode baseURL)
        ...                       # run opencode pointed at `base`
        proxy.stop()
    """

    def __init__(
        self,
        upstream_base_url: str,
        capture_path: str,
        host: str = "127.0.0.1",
        port: Optional[int] = None,
    ) -> None:
        parts = urlsplit(upstream_base_url)
        self._origin = f"{parts.scheme}://{parts.netloc}"
        self._base_path = parts.path.rstrip("/")  # e.g. "/v1" ("" if none)
        self.capture_path = capture_path
        self.host = host
        self.port = port or _free_port(host)
        self._write_lock = threading.Lock()
        self._server: Optional[uvicorn.Server] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}{self._base_path}"

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> str:
        config = uvicorn.Config(
            self._build_app(), host=self.host, port=self.port, log_level="warning", lifespan="on"
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, name="opencode-llm-proxy", daemon=True
        )
        self._thread.start()
        for _ in range(500):  # up to ~10s for the server loop to come up
            if self._server.started:
                break
            time.sleep(0.02)
        logger.info(f"[OPENCODE-LLM-PROXY] capturing to {self.capture_path}, forwarding to {self._origin}{self._base_path}")
        return self.url

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("[OPENCODE-LLM-PROXY] stopped")

    # ------------------------------------------------------------------ server
    def _build_app(self) -> Starlette:
        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette):
            async with httpx.AsyncClient(timeout=None) as client:
                app.state.client = client
                yield

        route = Route("/{rest:path}", self._handle, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
        return Starlette(routes=[route], lifespan=lifespan)

    async def _handle(self, request: Request) -> StreamingResponse:
        body = await request.body()
        method = request.method
        path = request.url.path
        query = request.url.query
        url = self._origin + path + (("?" + query) if query else "")
        fwd_headers = {
            k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQUEST_HEADERS
        }

        t0 = time.time()
        client: httpx.AsyncClient = request.app.state.client
        upstream_req = client.build_request(method, url, headers=fwd_headers, content=body)
        resp = await client.send(upstream_req, stream=True)

        resp_headers = {
            k: v for k, v in resp.headers.items() if k.lower() not in _DROP_RESPONSE_HEADERS
        }
        collected = bytearray()

        async def body_iter():
            try:
                async for chunk in resp.aiter_raw():
                    collected.extend(chunk)
                    yield chunk
            finally:
                await resp.aclose()
                self._write_record(
                    method=method,
                    path=path,
                    req_headers=request.headers,
                    req_body=body,
                    status=resp.status_code,
                    resp_bytes=bytes(collected),
                    t0=t0,
                )

        return StreamingResponse(body_iter(), status_code=resp.status_code, headers=resp_headers)

    # ------------------------------------------------------------------ capture
    def _write_record(
        self,
        *,
        method: str,
        path: str,
        req_headers: Any,
        req_body: bytes,
        status: int,
        resp_bytes: bytes,
        t0: float,
    ) -> None:
        try:
            req_json = _try_json(req_body)
            is_stream = bool(isinstance(req_json, dict) and req_json.get("stream"))
            record = {
                "ts": t0,
                "method": method,
                "path": path,
                "status": status,
                "latency_ms": int((time.time() - t0) * 1000),
                "stream": is_stream,
                "request_headers": _redact_headers(req_headers),
                "request": req_json if req_json is not None else {"_raw": _safe_text(req_body)},
                "response": self._parse_response(resp_bytes, is_stream),
            }
            line = json.dumps(record, ensure_ascii=False)
        except Exception as exc:  # never let a capture failure break the proxied call
            line = json.dumps({"ts": t0, "path": path, "capture_error": str(exc)})
        with self._write_lock:
            with open(self.capture_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    @staticmethod
    def _parse_response(resp_bytes: bytes, is_stream: bool) -> dict[str, Any]:
        text = resp_bytes.decode("utf-8", errors="replace")
        if is_stream:
            raw_sse = [ln for ln in text.splitlines() if ln.strip()]
            reassembled, usage = _reassemble_sse(text)
            return {"raw_sse": raw_sse, "reassembled": reassembled, "usage": usage}
        body = _try_json(resp_bytes)
        return {"body": body if body is not None else {"_raw": text}}


def _safe_text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")
