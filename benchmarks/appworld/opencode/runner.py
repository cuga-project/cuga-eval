"""Drive the OpenCode CLI as a subprocess against a live AppWorld ``world``.

OpenCode ships as a standalone CLI binary (TypeScript, but we never import TS — we invoke the
installed ``opencode`` binary as an external process). This module:

1. resolves the model name to match the framework's configured model profile,
2. renders the minimal AppWorld system prompt,
3. writes a per-task ``opencode.json`` (a custom openai-compatible provider pointing straight at the
   configured LLM endpoint, the AppWorld MCP bridge as a remote MCP server, built-in fs/exec tools
   disabled, and an ``appworld`` agent whose system prompt is the rendered instructions),
4. runs ``opencode run "<instruction>" --format json`` and parses the event stream for the final
   answer and token usage.

Metrics (tokens / cost / llm_calls) come from OpenCode's own ``--format json`` usage events. Cost for
models litellm/OpenCode don't price natively (e.g. Azure GPT-5.x) is computed here from token counts via
``MODEL_PRICES``. The actual task score still comes from ``world.evaluate()`` in the harness.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from opencode.llm_proxy import LLMCaptureProxy

PROMPT_PATH = Path(__file__).parent / "prompts" / "instructions.txt"

# Provider id used in opencode.json / the --model flag. Points directly at the configured LLM
# endpoint (an OpenAI-compatible gateway, or real OpenAI); no proxy.
PROVIDER_ID = "llm"

DEFAULT_BASE_URL = "https://api.openai.com/v1"

# Per-token prices ($/token) for models OpenCode/litellm don't price natively. Published $/1M ÷ 1e6.
# Matched leniently by substring so any prefix (azure/, Azure/, …) resolves.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    # name        (input $/token,   output $/token)
    "gpt-5.2": (1.75 / 1_000_000, 14.00 / 1_000_000),
    "gpt-5.5": (2.50 / 1_000_000, 15.00 / 1_000_000),
}

# Built-in OpenCode tools disabled so the agent can only act through AppWorld MCP tools
# (it must not "solve" tasks by touching the real filesystem / shell / web).
_DISABLED_BUILTIN_TOOLS = {
    "write": False,
    "edit": False,
    "patch": False,
    "bash": False,
    "read": False,
    "list": False,
    "glob": False,
    "grep": False,
    "webfetch": False,
}


@dataclass
class OpencodeResult:
    final_answer: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    returncode: int = 0
    stderr_tail: str = ""


def opencode_available(opencode_bin: str = "opencode") -> Optional[str]:
    """Return the resolved path to the opencode binary, or None if not installed."""
    return shutil.which(opencode_bin)


def resolve_model() -> str:
    """Resolve the model name to evaluate OpenCode with.

    Matches the framework's configured model (``MODEL_NAME``), mirroring how
    ``benchmarks/helpers/react_agent.py`` resolves it. Falls back to ``gpt-4o``.
    """
    model = os.getenv("MODEL_NAME")
    if model:
        return model.strip()
    logger.warning("[OPENCODE-RUNNER] MODEL_NAME not set; defaulting to gpt-4o")
    return "gpt-4o"


def model_price(model: str) -> Optional[tuple[float, float]]:
    """Return (input_$/token, output_$/token) for ``model`` if we price it, else None."""
    m = (model or "").lower()
    if "gpt-5.2" in m:
        return MODEL_PRICES["gpt-5.2"]
    if "gpt-5.5" in m:
        return MODEL_PRICES["gpt-5.5"]
    return None


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    """Compute $ cost from token counts using MODEL_PRICES; None if the model isn't priced here."""
    price = model_price(model)
    if not price:
        return None
    return input_tokens * price[0] + output_tokens * price[1]


def render_system_prompt(app_descriptions: dict[str, str], mode: str = "repl") -> str:
    """Render the minimal AppWorld system prompt with the task's app descriptions."""
    template = PROMPT_PATH.read_text(encoding="utf-8")
    apps_json = json.dumps(
        [{"name": k, "description": v} for (k, v) in app_descriptions.items()], indent=1
    )
    return template.replace("{app_descriptions}", apps_json)


def build_opencode_config(
    *,
    model: str,
    base_url: str,
    api_key: str,
    bridge_url: str,
    system_prompt: str,
    mode: str = "repl",
) -> dict[str, Any]:
    """Build the ``opencode.json`` config dict for one task run."""
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"

    return {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            PROVIDER_ID: {
                "npm": "@ai-sdk/openai-compatible",
                "name": "AppWorld eval LLM",
                "options": {"baseURL": base, "apiKey": api_key},
                "models": {model: {"name": model}},
            }
        },
        "mcp": {
            "appworld": {"type": "remote", "url": bridge_url, "enabled": True},
        },
        # Disable built-in tools; only AppWorld MCP tools (+ planning) remain.
        "tools": dict(_DISABLED_BUILTIN_TOOLS),
        "agent": {
            "appworld": {
                "mode": "primary",
                "prompt": system_prompt,
                "tools": {"appworld*": True},
            }
        },
    }


def _extract_tokens(tok: Any) -> Optional[tuple[int, int]]:
    """Pull (input, output) token counts from an OpenCode ``tokens`` object, if present."""
    if not isinstance(tok, dict):
        return None
    inp = tok.get("input") or tok.get("input_tokens") or tok.get("prompt_tokens") or tok.get("promptTokens")
    out = (
        tok.get("output")
        or tok.get("output_tokens")
        or tok.get("completion_tokens")
        or tok.get("completionTokens")
    )
    if inp is None and out is None:
        return None
    try:
        return int(inp or 0), int(out or 0)
    except (TypeError, ValueError):
        return None


def parse_opencode_events(stdout: str) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Parse ``opencode run --format json`` stdout into (final_answer, events, usage).

    The event stream is JSON-lines. We concatenate assistant ``text`` parts for the final answer and
    aggregate per-message token usage (input/output) and cost. The exact event schema varies by
    OpenCode version; this is defensive and assumes one usage object per assistant turn — validate
    against your installed OpenCode if the totals look off.
    """
    events: list[dict[str, Any]] = []
    text_parts: list[str] = []
    in_tok = 0
    out_tok = 0
    calls = 0
    cost = 0.0
    saw_cost = False

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(evt, dict):
            continue
        events.append(evt)

        if evt.get("type") == "text":
            part = evt.get("part") or {}
            text = part.get("text") if isinstance(part, dict) else None
            if text:
                text_parts.append(str(text))

        # Find the first container in this event that carries a tokens object (avoid double-count).
        for container in (evt, evt.get("part"), evt.get("message"), evt.get("info")):
            if not isinstance(container, dict):
                continue
            toks = _extract_tokens(container.get("tokens") or container.get("usage"))
            if toks is None:
                continue
            in_tok += toks[0]
            out_tok += toks[1]
            calls += 1
            c = container.get("cost")
            if isinstance(c, (int, float)):
                cost += float(c)
                saw_cost = True
            break

    usage = {
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "total_tokens": in_tok + out_tok,
        "llm_calls": calls,
        "cost": (cost if saw_cost else None),
    }
    return "\n".join(text_parts).strip(), events, usage


async def run_opencode(
    *,
    instruction: str,
    app_descriptions: dict[str, str],
    bridge_url: str,
    base_url: str,
    api_key: str,
    mode: str = "repl",
    model: Optional[str] = None,
    opencode_bin: str = "opencode",
    scratch_dir: str,
    extra_args: Optional[list[str]] = None,
    timeout: float = 900.0,
    llm_capture_path: Optional[str] = None,
) -> OpencodeResult:
    """Run one AppWorld task through OpenCode and return the parsed result.

    Raises ``RuntimeError`` if the ``opencode`` binary is not installed.
    """
    binary = opencode_available(opencode_bin)
    if not binary:
        raise RuntimeError(
            f"opencode CLI not found (looked for {opencode_bin!r} on PATH). "
            "Install it (e.g. `npm i -g opencode-ai` or `brew install opencode`) and retry."
        )

    model = model or resolve_model()
    system_prompt = render_system_prompt(app_descriptions, mode=mode)

    # Optional capture proxy: OpenCode talks to it instead of the gateway, and it tees every LLM
    # request/response to `llm_capture_path` while forwarding upstream. Degrades gracefully — if the
    # proxy can't start, point OpenCode straight at the gateway (run succeeds, just no capture).
    proxy: Optional[LLMCaptureProxy] = None
    effective_base_url = base_url
    if llm_capture_path:
        try:
            proxy = LLMCaptureProxy(upstream_base_url=base_url, capture_path=llm_capture_path)
            effective_base_url = proxy.start()
        except Exception as exc:  # never block the run on capture setup
            logger.warning(f"[OPENCODE-LLM-PROXY] failed to start ({exc}); continuing without capture")
            proxy = None
            effective_base_url = base_url

    config = build_opencode_config(
        model=model,
        base_url=effective_base_url,
        api_key=api_key,
        bridge_url=bridge_url,
        system_prompt=system_prompt,
        mode=mode,
    )

    scratch = Path(scratch_dir)
    scratch.mkdir(parents=True, exist_ok=True)
    config_path = scratch / "opencode.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    args = [
        binary,
        "run",
        instruction,
        "--agent",
        "appworld",
        "--model",
        f"{PROVIDER_ID}/{model}",
        "--format",
        "json",
        # NOTE: `-q`/`--quiet` was removed from the `opencode run` CLI (gone as of v1.17.x).
        # Passing it makes yargs strict-mode reject the whole invocation (exit 1, usage dump,
        # 0 LLM calls) before any work happens. `--format json` already gives non-interactive
        # JSON output, so no quiet flag is needed.
        "--dangerously-skip-permissions",
        "--dir",
        str(scratch),
    ]
    if extra_args:
        args.extend(extra_args)

    env = dict(os.environ)
    # Belt-and-suspenders config discovery (binary may honor --dir cwd and/or this env var).
    env["OPENCODE_CONFIG"] = str(config_path)

    logger.info(
        f"[OPENCODE-RUNNER] launching: opencode run <instruction> "
        f"--agent appworld --model {PROVIDER_ID}/{model} "
        f"(mode={mode}, mcp={bridge_url}, base={effective_base_url}, "
        f"capture={'on' if proxy is not None else 'off'})"
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            cwd=str(scratch),
            env=env,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"[OPENCODE-RUNNER] opencode run timed out after {timeout}s; killing")
            proc.kill()
            stdout_b, stderr_b = await proc.communicate()
    finally:
        # OpenCode has exited (or been killed), so all LLM calls are captured; tear down the proxy.
        if proxy is not None:
            proxy.stop()

    stdout = (stdout_b or b"").decode("utf-8", errors="replace")
    stderr = (stderr_b or b"").decode("utf-8", errors="replace")
    final_answer, events, usage = parse_opencode_events(stdout)

    # Fill in cost from token counts when OpenCode didn't report one (e.g. Azure GPT-5.x).
    if usage.get("cost") is None:
        usage["cost"] = compute_cost(model, usage["input_tokens"], usage["output_tokens"])

    if proc.returncode not in (0, None):
        logger.warning(
            f"[OPENCODE-RUNNER] opencode exited with code {proc.returncode}; "
            f"stderr tail: {stderr[-500:]}"
        )

    return OpencodeResult(
        final_answer=final_answer,
        events=events,
        usage=usage,
        returncode=proc.returncode or 0,
        stderr_tail=stderr[-1000:],
    )


# Made with Bob
