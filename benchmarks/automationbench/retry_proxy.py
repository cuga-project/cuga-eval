#!/usr/bin/env python3
"""Local OpenAI-compatible proxy that waits out gateway rate limits.

The LiteLLM deployment azure/FW-GLM-5.3-Flash allows 121k tokens/min. CUGA's
OpenAI client retries a 429 only twice within seconds, so one throttled call
ends the task. This proxy forwards every request to the upstream gateway and,
on 429 / 5xx / connection errors, waits (honouring x-ratelimit-reset-tokens /
retry-after) and retries. All requests share one "blocked until" time, so after
a 429 no request is sent until the window resets. A 400 quota_exceeded is waited
out the same way, for at most QUOTA_MAX_WAIT per request.

Every upstream call is logged to proxy_log.jsonl (status, attempts, waits, cost).

Usage:
  .venv/bin/python retry_proxy.py --port 8799
  # then point clients at http://127.0.0.1:8799 (CUGA) or .../v1 (auto-bench)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path

import httpx
import uvicorn
from dotenv import dotenv_values
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

HERE = Path(__file__).resolve().parent
EVAL_ROOT = HERE.parents[1]
LOG = HERE / "proxy_log.jsonl"
HOP_HEADERS = {"host", "content-length", "connection", "keep-alive", "transfer-encoding"}
MAX_ATTEMPTS = 60
ATTEMPT_TIMEOUT = 300.0
MIN_WAIT, MAX_WAIT = 3.0, 65.0
# a 400 quota_exceeded is waited out like a 429, for at most this long per request: a throughput quota clears in
# minutes (longest wait seen 2026-11-22..24: 378 s), and a daily or spend quota would hold every request for an hour
QUOTA_MAX_WAIT = 600.0

upstream = ""
NO_CACHE = False
client: httpx.AsyncClient
blocked_until = 0.0


def log(msg: str) -> None:
    print(f"{datetime.now().strftime('%H:%M:%S')} {msg}", flush=True)


def wait_seconds(resp: httpx.Response | None, attempt: int) -> float:
    if resp is not None:
        for key in ("x-ratelimit-reset-tokens", "llm_provider-x-ratelimit-reset-tokens", "retry-after"):
            value = resp.headers.get(key)
            if value:
                try:
                    return min(MAX_WAIT, max(MIN_WAIT, float(value)))
                except ValueError:
                    pass
    return min(MAX_WAIT, MIN_WAIT * 2**attempt)


async def forward(request: Request) -> Response:
    global blocked_until
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
    url = upstream + request.url.path + (f"?{request.url.query}" if request.url.query else "")
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {}
    if NO_CACHE and isinstance(payload, dict) and payload.get("messages"):
        payload["cache"] = {
            "no-cache": True
        }  # the gateway returns a stored reply for a repeated request otherwise
        body = json.dumps(payload).encode()
    stream = bool(payload.get("stream"))
    started, waited = time.monotonic(), 0.0
    resp: httpx.Response | None = None
    error = ""

    gave_up, quota_since = True, 0.0
    for attempt in range(MAX_ATTEMPTS):
        while (
            delay := blocked_until - time.monotonic()
        ) > 0:  # another request can extend the wait during the sleep
            waited += delay
            await asyncio.sleep(delay)
        try:
            req = client.build_request(request.method, url, headers=headers, content=body)
            resp = await client.send(req, stream=True)
        except httpx.HTTPError as exc:
            error = f"{type(exc).__name__}: {exc}"
            resp = None
        quota = False
        if resp is not None and resp.status_code == 400:
            await resp.aread()  # a short error body; read here to see whether it is a quota limit
            quota = (
                b"quota_exceeded" in resp.content
            )  # a throughput quota of the endpoint: wait, as for a 429
        if resp is not None and resp.status_code != 429 and resp.status_code < 500 and not quota:
            gave_up = False
            break
        pause = wait_seconds(resp, attempt)
        status = resp.status_code if resp is not None else error
        if resp is not None:
            error = f"HTTP {resp.status_code}{' quota_exceeded' if quota else ''}"
            await resp.aread()
            await resp.aclose()
        if quota:
            quota_since = quota_since or time.monotonic()
            if time.monotonic() - quota_since >= QUOTA_MAX_WAIT:
                error += f" for {QUOTA_MAX_WAIT:.0f}s: not a short throughput limit"
                break
        blocked_until = max(blocked_until, time.monotonic() + pause)
        log(f"retry {attempt + 1}/{MAX_ATTEMPTS} {request.url.path} after {status}; waiting {pause:.0f}s")
    if gave_up:
        record(request.url.path, payload, None, attempt + 1, waited, started, error)
        return JSONResponse(
            {"error": {"message": f"retry_proxy gave up after {attempt + 1} attempts: {error}", "code": 429}},
            429,
        )

    out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in HOP_HEADERS}
    if stream and not resp.is_stream_consumed:
        record(request.url.path, payload, resp, attempt + 1, waited, started, "")

        async def chunks():
            try:
                async for chunk in resp.aiter_raw():
                    yield chunk
            finally:
                await resp.aclose()

        return StreamingResponse(chunks(), status_code=resp.status_code, headers=out_headers)

    content = await resp.aread()  # decoded, so drop content-encoding below
    await resp.aclose()
    record(request.url.path, payload, resp, attempt + 1, waited, started, "", content)
    out_headers = {k: v for k, v in out_headers.items() if k.lower() != "content-encoding"}
    return Response(content, status_code=resp.status_code, headers=out_headers)


def record(path, payload, resp, attempts, waited, started, error, content: bytes | None = None) -> None:
    usage = None
    if content and resp is not None and "json" in resp.headers.get("content-type", ""):
        try:
            usage = json.loads(content).get("usage")
        except Exception:  # noqa: BLE001 — logging only
            usage = None
    row = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "path": path,
        "model": payload.get("model"),
        "stream": bool(payload.get("stream")),
        "status": resp.status_code if resp is not None else None,
        "attempts": attempts,
        "waited_s": round(waited, 1),
        "elapsed_s": round(time.monotonic() - started, 1),
        "cost": resp.headers.get("x-litellm-response-cost") if resp is not None else None,
        "usage": usage,
        "error": error or None,
    }
    with LOG.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def main() -> None:
    global upstream, client, NO_CACHE
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument(
        "--no-cache", action="store_true", help="ask the gateway for a fresh reply on every chat call"
    )
    args = parser.parse_args()
    NO_CACHE = args.no_cache
    upstream = (
        os.environ.get("UPSTREAM_BASE_URL") or dotenv_values(EVAL_ROOT / ".env")["OPENAI_BASE_URL"]
    ).rstrip("/")
    client = httpx.AsyncClient(timeout=httpx.Timeout(ATTEMPT_TIMEOUT, connect=30.0))
    log(f"forwarding 127.0.0.1:{args.port} -> {upstream}")
    app = Starlette(routes=[Route("/{path:path}", forward, methods=["GET", "POST"])])
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
