"""Regression test for issue #50.

GHSA-r7w7-9xr2-qq2r (a low-severity langchain-openai SSRF/DNS-rebinding
TOCTOU, fixed in 1.1.14) was ignored in pip-audit because langchain-openai
was pinned to 1.1.10 by cuga-agent's transitive constraints. uv.lock now
resolves langchain-openai to 1.2.2 (>= 1.1.14, with langchain-core 1.4.0 >=
the required 1.2.31): `uv run pip-audit --skip-editable --ignore-vuln
CVE-2026-47214` reports zero findings for langchain-openai, confirming the
ignore is stale. It has been removed from justfile and ci.yml.

CVE-2025-3000 (torch, not affected as of 2.13.0) and PYSEC-2026-3447
(setuptools, fixed in 83.0.0 once torch 2.13 relaxed its setuptools<82 pin)
were removed the same way for issue #130.

CVE-2026-47214 (docling, issues #45/#49) was the last one to go. It was ignored
while docling was pinned to <2.92, on the belief that the 2.92 slim split broke
langchain-docling's `from docling.chunking import ...`. It did not: 2.92 moved
that module into docling-slim and made `docling` depend on it unconditionally,
so docling could go to >=2.94 where the CVE is fixed. The pin and the ignore
were both dropped together.

Dropping that ignore is only safe *while* the >=2.94 floor holds, so the floor
is guarded here too (caught in review on PR #159 by Sergey-Zeltyn) — otherwise a
later re-pin below 2.94, or a dependency sweep that rewrites the constraint,
breaks CI's pip-audit with nothing in the suite explaining the connection. The
`<3` upper bound is guarded alongside it: CI syncs unlocked, so uv.lock does not
backstop the floor against a future docling repackaging.

These tests guard against any of the stale ignores being silently re-added, and
against the docling constraint that justifies the last one drifting.
"""

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.sanity

ROOT = Path(__file__).resolve().parents[1]
STALE_IGNORES = (
    "GHSA-r7w7-9xr2-qq2r",  # langchain-openai, issue #50
    "CVE-2025-3000",  # torch, issue #130
    "PYSEC-2026-3447",  # setuptools, issue #130
    "CVE-2026-47214",  # docling, issues #45 / #49
)

# The docling release that fixes CVE-2026-47214.
DOCLING_CVE_FIX_FLOOR = (2, 94)


def _pip_audit_command(text: str) -> str:
    match = re.search(r"uv run(?: --\S+)* pip-audit[^\n]*", text)
    assert match, "expected a `uv run pip-audit` invocation"
    return match.group(0)


def test_justfile_security_recipe_drops_stale_ignores() -> None:
    cmd = _pip_audit_command((ROOT / "justfile").read_text())
    for stale in STALE_IGNORES:
        assert stale not in cmd, f"stale ignore {stale} should be removed from justfile: {cmd}"


def test_ci_pip_audit_step_drops_stale_ignores() -> None:
    cmd = _pip_audit_command((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    for stale in STALE_IGNORES:
        assert stale not in cmd, f"stale ignore {stale} should be removed from ci.yml: {cmd}"


def _dependency_specifier(name: str) -> str:
    """Return the version specifier declared for `name` in project.dependencies.

    Parsed rather than grepped so the assertions below survive a floor bump past
    2.99 — a literal pattern like `docling>=2.9[4-9]` would fail on 2.100, i.e.
    reject a change that is strictly safer than the one it was written to catch.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    for requirement in pyproject["project"]["dependencies"]:
        # Anchor on the distribution name so `docling` can't match docling-core.
        match = re.match(r"\s*([A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*(.*)", requirement)
        assert match, f"unparseable requirement: {requirement!r}"
        if match.group(1).lower().replace("_", "-") == name:
            return match.group(2)
    raise AssertionError(f"{name} is not declared in project.dependencies")


def test_docling_floor_keeps_cve_fix() -> None:
    """CVE-2026-47214 is fixed in docling 2.94.0, and its pip-audit ignore was
    dropped on that basis, so the floor must not regress below it."""
    specifier = _dependency_specifier("docling")
    floors = re.findall(r">=\s*([\d.]+)", specifier)
    assert len(floors) == 1, f"expected exactly one `>=` floor for docling, got {specifier!r}"
    floor = tuple(int(part) for part in floors[0].split("."))
    assert floor >= DOCLING_CVE_FIX_FLOOR, (
        f"docling floor {floors[0]} is below 2.94, where CVE-2026-47214 is fixed — "
        "lowering it means restoring `--ignore-vuln CVE-2026-47214` in justfile and ci.yml"
    )


def test_docling_is_bounded_above() -> None:
    """CI runs `uv sync --group dev` (not `--locked`) against cuga-agent @ main, so
    any sibling metadata change re-resolves and uv.lock does not backstop the floor.
    An upper bound is what stops the next docling repackaging landing unreviewed."""
    specifier = _dependency_specifier("docling")
    assert re.search(r"<\s*[\d.]+", specifier), (
        f"docling needs an upper bound, got {specifier!r} — see the note in pyproject.toml"
    )
