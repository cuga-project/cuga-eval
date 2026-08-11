"""Unit tests for AppWorld registry URL resolution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from benchmarks.appworld.utils.registry_auth import get_registry_base_url

pytestmark = pytest.mark.sanity


def test_registry_host_full_url_wins_over_port_fallbacks(monkeypatch):
    monkeypatch.delenv("DYNACONF_SERVER_PORTS__REGISTRY", raising=False)
    fake_settings = SimpleNamespace(
        server_ports=SimpleNamespace(
            registry_host="https://registry.example:9443/",
            registry=8001,
        )
    )
    with patch("benchmarks.appworld.utils.registry_auth.settings", fake_settings):
        assert get_registry_base_url() == "https://registry.example:9443"


def test_env_port_used_when_registry_host_unset(monkeypatch):
    monkeypatch.setenv("DYNACONF_SERVER_PORTS__REGISTRY", "8123")
    fake_settings = SimpleNamespace(server_ports=SimpleNamespace(registry=8001))
    with patch("benchmarks.appworld.utils.registry_auth.settings", fake_settings):
        assert get_registry_base_url() == "http://localhost:8123"


def test_settings_registry_port_fallback(monkeypatch):
    monkeypatch.delenv("DYNACONF_SERVER_PORTS__REGISTRY", raising=False)
    fake_settings = SimpleNamespace(server_ports=SimpleNamespace(registry=9009))
    with patch("benchmarks.appworld.utils.registry_auth.settings", fake_settings):
        assert get_registry_base_url() == "http://localhost:9009"
