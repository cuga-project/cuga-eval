"""Regression test for issue #110.

`just` recipes run `uv run --frozen` (or, for scripts already using
`--no-sync`, that flag) so a drifted sibling `../cuga-agent` editable
checkout never causes a routine dev-loop command to silently rewrite
`uv.lock`. `sync` is the sole exception — it's the deliberate, explicit way
to update the lockfile.

`justfile`'s `test-smoke-e2e` recipe doesn't call `uv run` itself; it shells
out to scripts/smoke_benchmarks.sh, which in turn shells out to per-benchmark
eval.sh scripts. A grep over the justfile alone misses `uv run` calls in that
transitive chain (caught in review on PR #111 by offerakrabi).

Following review feedback that the fix isn't restricted to any one
benchmark, every benchmark's eval.sh/compare.sh/run_app.sh (and the shared
run_registry.sh) is checked here too, whether or not it's reachable from a
`just` recipe today — the whole point is that any of these can be run
directly by a contributor with a drifted `cuga-agent` sibling checked out.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.sanity

ROOT = Path(__file__).resolve().parents[1]

UV_RUN_RE = re.compile(r"uv run(\s+\S+)?")

# Executable scripts that invoke `uv run` as part of running/comparing/
# visualizing a benchmark. Excludes docs, docstrings, and config comments
# (which reference `uv run ...` as usage examples, not real invocations) and
# the vendored benchmarks/appworld/appworld/ checkout (a separate upstream
# project with its own CI, not part of cuga-eval).
BENCHMARK_SCRIPTS = [
    "scripts/smoke_benchmarks.sh",
    "scripts/analyze.sh",
    "scripts/viz.sh",
    "benchmarks/appworld/eval.sh",
    "benchmarks/appworld/compare.sh",
    "benchmarks/appworld/run_app.sh",
    "benchmarks/bpo/eval.sh",
    "benchmarks/bpo/compare.sh",
    "benchmarks/bpo/run_app.sh",
    "benchmarks/m3/eval.sh",
    "benchmarks/m3/compare.sh",
    "benchmarks/m3/run_with_container.sh",
    "benchmarks/oak_health_insurance/eval.sh",
    "benchmarks/oak_health_insurance/compare.sh",
    "benchmarks/oak_health_insurance/run_app.sh",
    "benchmarks/helpers/run_registry.sh",
]


def _unprotected_uv_run_calls(text: str) -> list[str]:
    unprotected = []
    for match in UV_RUN_RE.finditer(text):
        first_flag = (match.group(1) or "").strip()
        if first_flag not in ("--frozen", "--no-sync"):
            line = text[: match.start()].count("\n") + 1
            unprotected.append(f"line {line}: {match.group(0)}")
    return unprotected


def test_justfile_recipes_use_frozen() -> None:
    justfile = (ROOT / "justfile").read_text()
    # Only `sync` may touch uv.lock; every other recipe's `uv run` line must
    # be --frozen. Slice `sync`'s body (up to the next blank line) out first.
    sync_body = re.search(r"^sync:\n(?:    .+\n)+", justfile, re.MULTILINE)
    assert sync_body, "expected a `sync:` recipe in justfile"
    rest = justfile.replace(sync_body.group(0), "")

    unprotected = [call for call in _unprotected_uv_run_calls(rest) if "--frozen" not in call]
    assert not unprotected, f"justfile `uv run` calls missing --frozen: {unprotected}"


@pytest.mark.parametrize("relative_path", BENCHMARK_SCRIPTS)
def test_benchmark_script_has_no_unprotected_uv_run(relative_path: str) -> None:
    """Every uv run in a benchmark driver script must be --frozen or --no-sync."""
    text = (ROOT / relative_path).read_text()
    unprotected = _unprotected_uv_run_calls(text)
    assert not unprotected, f"{relative_path} has unprotected `uv run` calls: {unprotected}"
