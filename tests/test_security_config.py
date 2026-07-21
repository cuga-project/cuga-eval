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

This test guards against any of the stale ignores being silently re-added,
and against the unrelated CVE-2026-47214 (docling, issue #45) ignore being
dropped by mistake.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.sanity

ROOT = Path(__file__).resolve().parents[1]
STALE_IGNORES = (
    "GHSA-r7w7-9xr2-qq2r",  # langchain-openai, issue #50
    "CVE-2025-3000",  # torch, issue #130
    "PYSEC-2026-3447",  # setuptools, issue #130
)
DOCLING_IGNORE = "CVE-2026-47214"


def _pip_audit_command(text: str) -> str:
    match = re.search(r"uv run(?: --\S+)* pip-audit[^\n]*", text)
    assert match, "expected a `uv run pip-audit` invocation"
    return match.group(0)


def test_justfile_security_recipe_drops_stale_ignores() -> None:
    cmd = _pip_audit_command((ROOT / "justfile").read_text())
    for stale in STALE_IGNORES:
        assert stale not in cmd, f"stale ignore {stale} should be removed from justfile: {cmd}"
    assert DOCLING_IGNORE in cmd, f"unrelated docling ignore (#45) should remain: {cmd}"


def test_ci_pip_audit_step_drops_stale_ignores() -> None:
    cmd = _pip_audit_command((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    for stale in STALE_IGNORES:
        assert stale not in cmd, f"stale ignore {stale} should be removed from ci.yml: {cmd}"
    assert DOCLING_IGNORE in cmd, f"unrelated docling ignore (#45) should remain: {cmd}"
