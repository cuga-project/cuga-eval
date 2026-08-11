"""Shared AppWorld registry auth helpers for eval entry points."""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from cuga.config import settings


def get_registry_base_url() -> str:
    server_ports = getattr(settings, "server_ports", None)
    registry_host = getattr(server_ports, "registry_host", None) if server_ports else None
    if registry_host:
        return str(registry_host).rstrip("/")

    registry_port = os.getenv("DYNACONF_SERVER_PORTS__REGISTRY")
    if registry_port:
        return f"http://localhost:{registry_port}"

    for attr_name in ("registry", "registry_url", "registry_port"):
        port = getattr(server_ports, attr_name, None) if server_ports else None
        if port:
            return f"http://localhost:{port}"

    return "http://localhost:8001"


async def authenticate_apps(app_names: Optional[list[str]] = None) -> dict[str, Any]:
    """POST /api/authenticate_apps.

    Empty/None ``app_names`` means all configured apps (registry expands the
    list). Raises on HTTP errors; JSON parse failures return a text fallback.
    """
    payload = {"apps": list(app_names) if app_names is not None else []}
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
