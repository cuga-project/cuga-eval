"""Regression test for the sequential per-domain registry "0 tools" bug.

In `--no-ground-truth --m3-data` mode, `run_config_mode` narrows each
service to exactly one domain before calling `evaluate_single_task`:
`rewrite_config_with_loader_domains` rewrites `metadata.domains` from the
loader's data, then `expand_registry_config` expands each service down to a
single-domain entry (`eval_m3.py:2357-2361`). Sequential mode starts a
fresh, single-domain-scoped registry per service and calls
`evaluate_single_task` once per domain.

A previous version of `evaluate_single_task` re-derived `domains` from
`m3_data_loader.available_domains(task_id)` and unconditionally overwrote
the caller's (correctly narrowed) value with the *full* domain list for the
task. The first call (e.g. for domain "address") would then try to walk
every domain for the task, but only the registry for "address" was ever
started -- so every domain after the first had zero tools registered
(observed: `cap3-guard-test` completed "address" fine, then "airline"
failed with "Application 'airline' not found in registry" / "Loaded 0
tools for 'airline'").
"""

import inspect

import pytest

from benchmarks.m3 import eval_m3

pytestmark = pytest.mark.regression


def test_evaluate_single_task_does_not_override_domains_from_loader():
    """Guards against reintroducing the address->airline '0 tools' bug."""
    source = inspect.getsource(eval_m3.evaluate_single_task)
    assert "available_domains" not in source, (
        "evaluate_single_task must not re-derive `domains` from "
        "m3_data_loader.available_domains() -- that discards the single-domain "
        "narrowing the sequential per-service registry loop relies on and "
        "reproduces the address->airline '0 tools' bug"
    )


def test_no_gt_mode_flag_still_computed():
    """The override is gone, but no_gt_mode itself must survive -- it still
    gates the write_predictions_no_gt vs. vakra_score_results_async branch
    later in the same function."""
    source = inspect.getsource(eval_m3.evaluate_single_task)
    assert "no_gt_mode = bool(m3_data_loader" in source
    assert source.count("if no_gt_mode:") >= 1
