# Design: Always-on LLM request/response capture for the OpenCode agent

Date: 2026-06-29
Status: Approved (pending spec review)
Scope: `benchmarks/appworld` OpenCode agent path only

## Problem

On the `--agent opencode` path, OpenCode makes its **own** LLM calls directly to the
configured endpoint (`OPENAI_BASE_URL` / litellm gateway). There is **no proxy**, so the
harness never sees the prompt sent or the completion received. The existing observability
captures:

- the **generated Python code** (via the MCP bridge → trajectory `steps[].data.args.code`),
- a **harness-level Langfuse trace** (`{task_id, intent}` → `{final_answer, score, metrics}`),
- **FastMCP tool-call spans** (tool name / session / method — no arguments, no result).

None of these contain the **LLM request** (system prompt + message history + tool schemas) or
the **LLM response** (assistant message / tool calls / usage). This spec adds that capture.

## Goal

For every OpenCode LLM call, record **exactly what we send** and **exactly what we receive**,
written per task to:

```
benchmarks/appworld/experiments/outputs/<run>/tasks/<task_id>_llm_calls.jsonl
```

Always-on for the OpenCode agent.

## Approach

A transparent local reverse-proxy is inserted between OpenCode and the real gateway. OpenCode's
provider `baseURL` (in the generated `opencode.json`) is rewritten to the proxy's local URL. The
proxy forwards each request to the real gateway (preserving method, path, query, headers, body),
streams the response straight back in real time, and tees both request and response into a
per-task JSONL capture file.

```
OpenCode ──HTTP──► capture proxy (127.0.0.1:<port>) ──HTTP──► litellm/Azure gateway
                          │ tees request + response
                          ▼
        experiments/outputs/<run>/tasks/<task_id>_llm_calls.jsonl
```

Rejected alternatives:

- **Gateway-side → Langfuse**: requires admin control over the shared IBM litellm gateway, which
  we do not have.
- **OpenCode `--print-logs --log-level DEBUG`**: undocumented, version-specific log format; not
  guaranteed to contain full request/response bodies; fragile parsing.

## Components

### 1. `benchmarks/appworld/utils/opencode_llm_proxy.py` (new)

A Starlette app served by uvicorn in a daemon thread (same pattern as `opencode_bridge.py`),
forwarding with `httpx.AsyncClient`. Both `httpx` and `uvicorn` are already dependencies.

- `class LLMCaptureProxy(upstream_base_url: str, capture_path: str, host="127.0.0.1", port=None)`
  - `start() -> str` — bind a free port, start the server thread, return the local base URL.
  - `stop()` — graceful shutdown; flush/close the capture file.
- Catch-all route (all methods, all paths). For each request:
  1. Read method, path, query, headers, body.
  2. Forward to `upstream_base_url` preserving the incoming path + query (so the gateway's path
     prefix such as `/v1` is preserved — see Path mapping).
  3. Stream the upstream response back to the client chunk-by-chunk (`StreamingResponse` over
     `httpx` `aiter_bytes`), so the agent is never blocked or slowed by capture.
  4. Tee the request body and the response bytes into the capture record; append one JSON line.
- **Path mapping**: OpenCode's `@ai-sdk/openai-compatible` provider posts to
  `${baseURL}/chat/completions`. The proxy is given `upstream_base_url` = the real configured base
  (the value that already ends in `/v1`, exactly what `build_opencode_config` computes today). From
  it the proxy derives the upstream **origin** (`scheme://host[:port]`) and **base path** (e.g.
  `/v1`). `start()` returns the local URL `http://127.0.0.1:<port><base_path>` (e.g.
  `http://127.0.0.1:<port>/v1`), which becomes OpenCode's `baseURL`; OpenCode therefore posts to
  `http://127.0.0.1:<port>/v1/chat/completions`. The proxy forwards the incoming path + query
  **verbatim** to the upstream origin, reproducing `https://gw/v1/chat/completions`. The captured
  `path` is the incoming request path (e.g. `/v1/chat/completions`). This exact join is pinned by
  the proxy unit test against a fake upstream.
- **Secret redaction**: `Authorization` and any `api-key` / `x-api-key` headers are stripped from
  the captured record. They are still forwarded upstream; they are never written to disk.

### 2. `benchmarks/appworld/utils/opencode_runner.py` (modified)

- `run_opencode(...)` gains `llm_capture_path: Optional[str] = None`.
- When set:
  1. Start an `LLMCaptureProxy` with `upstream_base_url = base_url`, `capture_path = llm_capture_path`.
  2. Call `build_opencode_config(..., base_url=<proxy_url>)` so `opencode.json` points at the proxy.
  3. Launch OpenCode as today.
  4. In a `finally`, `stop()` the proxy (alongside / mirroring existing cleanup).
- `build_opencode_config` is unchanged in shape; it just receives the proxy URL as `base_url`. The
  apiKey continues to be embedded as today and is forwarded by OpenCode → proxy → gateway; the
  proxy does not need the key itself.

### 3. `benchmarks/appworld/appworld_eval_opencode.py` (modified)

- Compute the per-task capture path from the experiment-output directory + `task_id`:
  `…/experiments/outputs/<run>/tasks/<task_id>_llm_calls.jsonl`. If the experiment output dir is
  unavailable, fall back to `scratch_dir/<task_id>_llm_calls.jsonl`.
- Pass it as `llm_capture_path` to `run_opencode` for every OpenCode run (always-on).

## Record format (JSONL, one object per LLM call)

```json
{
  "ts": 1782717864.4,
  "method": "POST",
  "path": "/v1/chat/completions",
  "status": 200,
  "latency_ms": 1234,
  "stream": true,
  "request": { "model": "...", "messages": [ ... ], "tools": [ ... ] },
  "response": {
    "reassembled": { "role": "assistant", "content": "...", "tool_calls": [ ... ] },
    "usage": { "prompt_tokens": 1815, "completion_tokens": 3 },
    "raw_sse": [ "data: {...}", "data: {...}", "data: [DONE]" ]
  }
}
```

- **What we send** = `request` (full body, parsed JSON when possible; raw string otherwise).
- **What we receive** = `response`. For streaming (`text/event-stream`), `raw_sse` preserves the
  exact chunks (byte fidelity) and `reassembled` concatenates `choices[].delta` into a final
  message for readability. For non-streaming, `response` is the parsed JSON body and `raw_sse` is
  omitted.
- `ts` and `latency_ms` are stamped by the proxy at request time using `time.time()`.

## Error handling

- **Upstream errors** (4xx/5xx) are passed through to OpenCode unchanged — capture must never
  alter agent behavior — and are still recorded (with their status/body).
- **Proxy fails to start**: log a warning and fall back to pointing OpenCode directly at the real
  gateway. The run still succeeds, without capture (graceful degradation despite always-on).
- **Per-request handler errors** (e.g. a logging/serialization failure) are caught so they can
  never kill an in-flight LLM call; the forward still completes, and a minimal error record is
  written.

## Testing

- New `benchmarks/appworld/tests/test_opencode_llm_proxy.py` (mirrors `test_opencode_bridge.py`):
  start the proxy in front of a **fake upstream** Starlette app returning canned completions — one
  non-streaming JSON, one SSE stream — send requests through the proxy with `httpx`, and assert:
  1. the client response matches the upstream response (pass-through intact, streaming preserved);
  2. the capture file contains the request body and the reassembled response (+ `raw_sse` for the
     streaming case);
  3. `Authorization` is redacted in the captured record but was forwarded upstream.
- The existing `test_opencode_runner.py` / `test_opencode_bridge.py` suites remain green.

## Scope / non-goals (YAGNI)

- OpenCode agent only. The cuga/codeact/react agents call LLMs in-process via LangChain and are
  separately traceable; they are out of scope.
- The capture files are written to disk under the experiment output dir. Wiring them into the
  reproducibility bundle is deferred (can be added later if needed).
- Capture files can be large: the final turn's `request` contains the full accumulated message
  history. This is intended ("what we send" on each call) and accepted.

## Affected files

| File | Change |
|------|--------|
| `benchmarks/appworld/utils/opencode_llm_proxy.py` | New: the capture reverse-proxy. |
| `benchmarks/appworld/utils/opencode_runner.py` | `run_opencode` gains `llm_capture_path`; starts/stops the proxy; points `opencode.json` at it. |
| `benchmarks/appworld/appworld_eval_opencode.py` | Computes the per-task capture path and passes it in (always-on). |
| `benchmarks/appworld/tests/test_opencode_llm_proxy.py` | New: proxy pass-through + capture + redaction tests. |
