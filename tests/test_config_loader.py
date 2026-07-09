"""Regression tests for issue #17 (load_eval_config clobbering pre-set env vars).

config_loader/loader.py (the module actually imported by every benchmark
entrypoint via `sys.path.insert(0, project_root); from config_loader import
load_eval_config` — NOT benchmarks/helpers/config_loader.py, which had zero
real importers and was deleted) used to call load_dotenv(..., override=True),
which meant an env var the caller pre-set (e.g. DYNACONF_SERVER_PORTS__APIS_URL
before calling load_eval_config) got silently overwritten by whatever the
benchmark's own .env file hardcoded. These tests pin the correct behavior:
caller-set env vars always win, but a benchmark's own .env file still overrides
config/global.env's defaults when the caller hasn't set anything.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from config_loader import loader as config_loader

pytestmark = pytest.mark.sanity


def _fake_dotenv_values(path):
    """Stand in for dotenv_values(): global.env vs. any benchmark .env."""
    if path.name == "global.env":
        return {"SHARED_KEY": "from_global", "ONLY_IN_GLOBAL": "global_only"}
    return {"SHARED_KEY": "from_benchmark", "ONLY_IN_BENCHMARK": "benchmark_only"}


_MUTATED_KEYS = (
    "SHARED_KEY",
    "ONLY_IN_GLOBAL",
    "ONLY_IN_BENCHMARK",
    "EMPTY_KEY",
    # load_eval_config also unconditionally sets these as a side effect.
    "LOGURU_LEVEL",
    "CUGA_LOGGING_DIR",
)


@pytest.fixture(autouse=True)
def _fake_env_files(monkeypatch):
    """Make both .env files 'exist' and return controlled fake contents."""
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(config_loader, "dotenv_values", _fake_dotenv_values)
    for key in _MUTATED_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield
    # load_eval_config mutates os.environ directly via setdefault(), which
    # monkeypatch doesn't track/revert — clean up explicitly so these don't
    # leak into other tests in the same process.
    for key in _MUTATED_KEYS:
        os.environ.pop(key, None)


def test_preset_env_var_is_not_clobbered(monkeypatch):
    """A caller-set env var must survive both .env file loads."""
    monkeypatch.setenv("SHARED_KEY", "caller_preset")
    config_loader.load_eval_config("fake_benchmark")
    assert os.environ["SHARED_KEY"] == "caller_preset"


def test_benchmark_env_overrides_global_when_unset():
    """With nothing pre-set, the benchmark .env wins over global.env."""
    config_loader.load_eval_config("fake_benchmark")
    assert os.environ["SHARED_KEY"] == "from_benchmark"


def test_global_only_key_is_still_set():
    """A key only present in global.env is still applied."""
    config_loader.load_eval_config("fake_benchmark")
    assert os.environ["ONLY_IN_GLOBAL"] == "global_only"


def test_benchmark_only_key_is_set():
    """A key only present in the benchmark .env is still applied."""
    config_loader.load_eval_config("fake_benchmark")
    assert os.environ["ONLY_IN_BENCHMARK"] == "benchmark_only"


def test_none_value_from_dotenv_is_skipped(monkeypatch):
    """A bare `KEY` line (dotenv_values -> None) must not reach setdefault()."""

    def _fake_dotenv_with_none(path):
        if path.name == "global.env":
            return {}
        return {"EMPTY_KEY": None}

    monkeypatch.setattr(config_loader, "dotenv_values", _fake_dotenv_with_none)
    monkeypatch.delenv("EMPTY_KEY", raising=False)
    config_loader.load_eval_config("fake_benchmark")
    assert "EMPTY_KEY" not in os.environ
