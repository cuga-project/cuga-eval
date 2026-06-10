"""Regression test for issue #50.

GHSA-r7w7-9xr2-qq2r (a low-severity langchain-openai SSRF/DNS-rebinding
TOCTOU, fixed in 1.1.14) was ignored in pip-audit because langchain-openai
was pinned to 1.1.10 by cuga-agent's transitive constraints. uv.lock now
resolves langchain-openai to 1.2.2 (>= 1.1.14, with langchain-core 1.4.0 >=
the required 1.2.31): `uv run pip-audit --skip-editable --ignore-vuln
CVE-2026-47214` reports zero findings for langchain-openai, confirming the
ignore is stale. It has been removed from justfile and ci.yml.

This test guards against the stale ignore being silently re-added, and
against the unrelated CVE-2026-47214 (docling, issue #45) ignore being
dropped by mistake.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.sanity

ROOT = Path(__file__).resolve().parents[1]
STALE_IGNORE = "GHSA-r7w7-9xr2-qq2r"
DOCLING_IGNORE = "CVE-2026-47214"


def _pip_audit_command(text: str) -> str:
    match = re.search(r"uv run pip-audit[^\n]*", text)
    assert match, "expected a `uv run pip-audit` invocation"
    return match.group(0)


def test_justfile_security_recipe_drops_stale_ignore() -> None:
    cmd = _pip_audit_command((ROOT / "justfile").read_text())
    assert STALE_IGNORE not in cmd, f"stale ignore should be removed from justfile: {cmd}"
    assert DOCLING_IGNORE in cmd, f"unrelated docling ignore (#45) should remain: {cmd}"


def test_ci_pip_audit_step_drops_stale_ignore() -> None:
    cmd = _pip_audit_command((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    assert STALE_IGNORE not in cmd, f"stale ignore should be removed from ci.yml: {cmd}"
    assert DOCLING_IGNORE in cmd, f"unrelated docling ignore (#45) should remain: {cmd}"
