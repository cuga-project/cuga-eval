"""Phase 1 sanity: load_eval_config("tau2") sets up the env correctly and is
the first thing the entrypoint does (config-before-cuga-import contract).

No cuga / tau2 imports here — keep it fast and LLM-free.
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.sanity


def test_load_eval_config_sets_logging_dir():
    from config_loader import load_eval_config

    load_eval_config("tau2")

    logging_dir = os.environ.get("CUGA_LOGGING_DIR")
    assert logging_dir, "CUGA_LOGGING_DIR must be set after load_eval_config('tau2')"

    p = Path(logging_dir)
    assert p.is_absolute(), f"CUGA_LOGGING_DIR should be absolute, got: {logging_dir}"
    assert p.parts[-2:] == ("tau2", "logging"), f"unexpected logging dir: {logging_dir}"


def test_safety_pins_loaded():
    from config_loader import load_eval_config

    load_eval_config("tau2")

    # SAFETY PIN 1: e2b off so the in-process bridge works.
    assert os.environ.get("DYNACONF_ADVANCED_FEATURES__E2B_SANDBOX") == "false"
    # SAFETY PIN 2: tau2.env explicitly sets REGISTRY=false (tau2 uses decoy tools, not
    # the MCP registry). global.env stopped defaulting it to false in #126.
    assert os.environ.get("DYNACONF_ADVANCED_FEATURES__REGISTRY") == "false"


def test_entrypoint_imports_without_cuga():
    # Importing the entrypoint runs load_eval_config at import time and must NOT
    # pull in cuga as a side effect (the config load must come first).
    import sys

    import benchmarks.tau2.eval_tau2_sdk  # noqa: F401

    assert "cuga" not in sys.modules, "entrypoint import must not import cuga before the driver runs"
