"""Regression tests for issue #63 (``./eval.sh --verbose`` killing Python).

The shell entrypoints have always forwarded unknown args to the Python
evaluators. Before this PR, some evaluators (bpo, m3 single-turn, m3
react, m3 multiturn, appworld_eval, appworld_eval_react) declared
``--verbose`` themselves but none declared ``--quiet``; the SDK
entrypoints (eval_appworld_sdk, eval_bench_sdk, oak eval_bench_sdk)
declared neither, so any ``./eval.sh --verbose`` against them died with
``argparse: unrecognized arguments``.

These tests:
- Exercise the helper directly against a synthetic parser (fast, no IO).
- Walk every benchmark eval entrypoint's ``main()`` source and assert it
  imports the helper and calls ``apply_log_level``. Catches regressions
  if someone re-adds a manual ``--verbose`` declaration and forgets to
  also accept ``--quiet``.
"""

from __future__ import annotations

import argparse

import pytest

from benchmarks.helpers.logging_args import (
    add_log_level_args,
    apply_log_level,
    resolve_log_level,
)

pytestmark = pytest.mark.regression


def _parse(argv):
    parser = argparse.ArgumentParser()
    add_log_level_args(parser)
    return parser.parse_args(argv)


def test_verbose_flag_resolves_to_debug():
    assert resolve_log_level(_parse(["--verbose"])) == "DEBUG"
    assert resolve_log_level(_parse(["-v"])) == "DEBUG"


def test_quiet_flag_resolves_to_warning():
    assert resolve_log_level(_parse(["--quiet"])) == "WARNING"
    assert resolve_log_level(_parse(["-q"])) == "WARNING"


def test_no_flag_leaves_sink_unchanged():
    assert resolve_log_level(_parse([])) is None


def test_verbose_and_quiet_are_mutually_exclusive():
    parser = argparse.ArgumentParser()
    add_log_level_args(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(["--verbose", "--quiet"])


def test_apply_log_level_sets_loguru_env_var(monkeypatch):
    monkeypatch.delenv("LOGURU_LEVEL", raising=False)
    apply_log_level(_parse(["--verbose"]))
    import os

    assert os.environ.get("LOGURU_LEVEL") == "DEBUG"


def test_apply_log_level_noop_when_no_flag(monkeypatch):
    """No flag → don't touch LOGURU_LEVEL. Callers using the env var
    themselves shouldn't have it clobbered to None."""
    monkeypatch.setenv("LOGURU_LEVEL", "INFO")
    apply_log_level(_parse([]))
    import os

    # Untouched — apply returned None and left the env var alone.
    assert os.environ.get("LOGURU_LEVEL") == "INFO"


# --------------------------------------------------------------------------- #
# Integration guard: every eval entrypoint wires the helper.                  #
# --------------------------------------------------------------------------- #


_ENTRYPOINTS = [
    "benchmarks.appworld.eval_appworld_sdk",
    "benchmarks.appworld.appworld_eval",
    "benchmarks.appworld.appworld_eval_react",
    "benchmarks.bpo.eval_bench_sdk",
    "benchmarks.bpo.eval_bench_sdk_react",
    "benchmarks.oak_health_insurance.eval_bench_sdk",
    "benchmarks.oak_health_insurance.eval_bench",
    "benchmarks.m3.eval_m3",
    "benchmarks.m3.eval_m3_react",
    "benchmarks.m3.eval_m3_multiturn",
]


@pytest.mark.parametrize("module_name", _ENTRYPOINTS)
def test_entrypoint_wires_log_level_helper(module_name):
    """Every active eval entrypoint must wire ``add_log_level_args`` and
    ``apply_log_level``. Walks the AST of the source so commented-out
    calls don't fool the check (caught by sanity-testing this guard
    against a commented-out call on appworld/eval_appworld_sdk.py).

    AST-only — we don't import the modules. Importing eval_appworld_sdk
    pulls in cuga-agent which is expensive and depends on env config.
    """
    import ast
    import importlib.util

    spec = importlib.util.find_spec(module_name)
    assert spec is not None and spec.origin is not None, f"Cannot locate {module_name}"
    tree = ast.parse(open(spec.origin).read())  # noqa: SIM115

    calls = {getattr(getattr(n, "func", None), "id", None) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "add_log_level_args" in calls, (
        f"{module_name}: add_log_level_args(parser) call missing — issue #63"
    )
    assert "apply_log_level" in calls, f"{module_name}: apply_log_level(args) call missing — issue #63"


# --------------------------------------------------------------------------- #
# Shell guard: every eval.sh must forward --quiet (mirrors --verbose).        #
# --------------------------------------------------------------------------- #


_EVAL_SHELLS = [
    "benchmarks/appworld/eval.sh",
    "benchmarks/bpo/eval.sh",
    "benchmarks/oak_health_insurance/eval.sh",
    "benchmarks/m3/eval.sh",
]


@pytest.mark.parametrize("path", _EVAL_SHELLS)
def test_eval_sh_forwards_quiet_alongside_verbose(path):
    """The shell parsers were hand-rolled and originally only handled
    ``--verbose``. After this PR every parser also forwards ``--quiet``
    (and ``-q``) so the Python side actually receives it."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    text = (repo_root / path).read_text()
    assert "--quiet" in text or "--quiet|-q" in text, (
        f"{path}: --quiet not forwarded — ./eval.sh --quiet won't reach Python"
    )
