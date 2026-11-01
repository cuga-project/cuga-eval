"""Regression test for issue #213.

Symptom: every AppWorld run aborts with ``/initialize`` returning 500 and
``Found: :memory:file%3Atask_output-<task_id>`` in the server log.

Root cause: SQLAlchemy 2.1 percent-encodes ``:`` in rendered URLs, and AppWorld
derives its in-memory database name from the rendered URL. AppWorld is not in
the committed lock, so a local re-resolve takes the newest SQLAlchemy unless the
constraint in pyproject.toml holds it back. CI does not install AppWorld, so
this guards the constraint rather than the behavior.
"""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.sanity
def test_sqlalchemy_is_constrained_below_2_1() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    constraints = pyproject["tool"]["uv"].get("constraint-dependencies", [])
    assert "sqlalchemy<2.1" in constraints, (
        "AppWorld's /initialize returns 500 on SQLAlchemy 2.1+; drop this constraint "
        "only once AppWorld stops parsing the rendered URL (see #213)"
    )
