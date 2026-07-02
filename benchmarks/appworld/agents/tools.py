"""AppWorld tool bridge: CombinedToolProvider + LangChain tool execution."""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

import httpx
from cuga.backend.cuga_graph.nodes.cuga_lite.providers.combined import CombinedToolProvider
from cuga.config import settings
from loguru import logger


def get_registry_base_url() -> str:
    registry_port = os.getenv("DYNACONF_SERVER_PORTS__REGISTRY")
    if registry_port:
        return f"http://localhost:{registry_port}"

    server_ports = getattr(settings, "server_ports", None)
    for attr_name in ("registry", "registry_url", "registry_port"):
        port = getattr(server_ports, attr_name, None) if server_ports else None
        if port:
            return f"http://localhost:{port}"

    return "http://localhost:8001"


async def reset_registry() -> None:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{get_registry_base_url()}/api/reset", timeout=10.0)
        response.raise_for_status()


async def authenticate_apps(app_names: list[str]) -> dict[str, Any]:
    payload = {"apps": app_names}
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{get_registry_base_url()}/api/authenticate_apps",
            json=payload,
            timeout=15.0,
        )
        response.raise_for_status()
        try:
            return response.json()
        except Exception:
            return {"status_code": response.status_code, "text": response.text[:500]}


async def authenticate_apps_for_task(world: Any) -> dict[str, Any]:
    app_names = sorted(world.task.app_descriptions.keys())
    try:
        result = await authenticate_apps(app_names)
        logger.info(f"Registry authenticate_apps result: {result}")
        return result
    except Exception as exc:
        logger.warning(f"authenticate_apps failed before task run: {exc}")
        return {"error": str(exc)}


async def setup_appworld_tools(
    app_names: list[str] | None = None,
) -> tuple[CombinedToolProvider, list[Any]]:
    tool_provider = CombinedToolProvider(app_names=app_names)
    await tool_provider.initialize()
    tools = await tool_provider.get_all_tools()
    scope = f"apps {app_names}" if app_names else "all apps"
    logger.info(f"Loaded {len(tools)} AppWorld tools from CombinedToolProvider ({scope})")
    return tool_provider, tools


def task_app_names(world: Any) -> list[str]:
    return sorted(world.task.app_descriptions.keys())


def max_llm_bound_tools() -> int:
    raw = os.getenv("APPWORLD_MAX_LLM_TOOLS", "128")
    try:
        return max(1, int(raw))
    except ValueError:
        return 128


def build_tools_prompt(tools: list[Any]) -> str:
    lines: list[str] = []
    for tool in tools:
        name = getattr(tool, "name", "unknown_tool")
        description = getattr(tool, "description", "") or ""
        lines.append(f"- {name}: {description}".strip())
    return "\n".join(lines)


def normalize_tool_args(args: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(args)
    for key in list(args.keys()):
        snake_key = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
        if snake_key not in normalized:
            normalized[snake_key] = args[key]
    return normalized


def summarize_tool_result(result: Any) -> str:
    if isinstance(result, dict):
        summary_candidates: list[str] = []
        for key in ("answer", "result", "summary", "message", "data"):
            value = result.get(key)
            if value not in (None, "", [], {}):
                summary_candidates.append(f"{key}={value}")
        if summary_candidates:
            return " | ".join(summary_candidates)
    return ""


async def execute_langchain_tool(tool: Any, args: dict[str, Any]) -> str:
    normalized_args = normalize_tool_args(args)
    try:
        if hasattr(tool, "ainvoke"):
            result = await tool.ainvoke(normalized_args)
        elif hasattr(tool, "invoke"):
            result = tool.invoke(normalized_args)
            if asyncio.iscoroutine(result):
                result = await result
        elif callable(tool):
            result = tool(**normalized_args)
            if asyncio.iscoroutine(result):
                result = await result
        else:
            return f"Tool '{getattr(tool, 'name', 'unknown')}' is not invokable."
    except Exception as exc:
        name = getattr(tool, "name", "unknown")
        logger.warning(f"Tool call failed for {name}: {exc}")
        return f"Tool execution error for '{name}': {exc}"

    summary = summarize_tool_result(result)
    try:
        payload = json.dumps(result, ensure_ascii=False, default=str)
    except TypeError:
        payload = str(result)

    if summary:
        return f"{summary}\n\nFull output:\n{payload}"
    return payload


async def execute_tool_by_name(tools: list[Any], tool_name: str, args: dict[str, Any]) -> str:
    tool = next((t for t in tools if getattr(t, "name", None) == tool_name), None)
    if tool is None:
        return f"Tool '{tool_name}' not found."
    return await execute_langchain_tool(tool, args)


def create_eval_llm(model: str | None = None) -> Any:
    """Build an LLM client from AGENT_SETTING_CONFIG (same as GenericReactAgent)."""
    settings_config = os.getenv("AGENT_SETTING_CONFIG", "").strip()
    model_name = model or os.getenv("MODEL_NAME", "gpt-4o-mini")

    if settings_config == "settings.groq.toml":
        try:
            from langchain_groq import ChatGroq
            from pydantic import SecretStr
        except ImportError as exc:
            raise RuntimeError("langchain-groq is required. Install with: uv sync --group groq") from exc

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is required when AGENT_SETTING_CONFIG=settings.groq.toml")

        base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com").rstrip("/")
        return ChatGroq(
            model=model_name,
            temperature=0,
            api_key=SecretStr(api_key),
            base_url=base_url,
        )

    if settings_config == "settings.openai.toml":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "langchain-openai is required. Install with: pip install langchain-openai"
            ) from exc

        disable_ssl = os.getenv("CUGA_DISABLE_SSL", "").lower() in ("true", "1", "yes")
        ssl_verify = (
            os.getenv("OPENAI_SSL_VERIFY", "true").lower() not in ("false", "0", "no") and not disable_ssl
        )

        api_base = os.getenv("LITE_LLM_URL") or os.getenv("OPENAI_BASE_URL")
        api_key = os.getenv("LITE_LLM_KEY") or os.getenv("OPENAI_API_KEY")
        llm_kwargs: dict[str, Any] = {"model": model_name, "temperature": 0}
        if api_base:
            llm_kwargs["base_url"] = api_base.rstrip("/")
        if api_key:
            llm_kwargs["api_key"] = api_key
        if not ssl_verify:
            import httpx

            llm_kwargs["http_client"] = httpx.Client(verify=False)  # noqa: S501  # nosec B501 — opt-in for self-signed corporate endpoints
            llm_kwargs["http_async_client"] = httpx.AsyncClient(verify=False)  # noqa: S501  # nosec B501 — same

        return ChatOpenAI(**llm_kwargs)

    raise RuntimeError(
        "Unsupported AGENT_SETTING_CONFIG for external agents. "
        "Expected 'settings.groq.toml' or 'settings.openai.toml'."
    )
