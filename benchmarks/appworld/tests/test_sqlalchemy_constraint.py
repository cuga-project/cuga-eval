"""Regression test for issue #213.

AppWorld is not in the committed lock, so a local re-resolve takes the newest
release of everything it needs. Two of those releases break it:

- SQLAlchemy 2.1 percent-encodes ``:`` in rendered URLs, which AppWorld parses
  to derive its in-memory database name. Every run aborts with ``/initialize``
  returning 500 and ``Found: :memory:file%3Atask_output-<task_id>`` in the log.
- sqlmodel 0.0.45 made ``datetime`` fields UTC-aware and rejects AppWorld's
  naive ``DateTime.now()`` values. Writes of datetime columns (seen on
  ``POST /amazon/orders``) return 500 after the parent row is committed, so
  tasks score partially instead of failing.

CI does not install AppWorld, so this guards the constraints rather than the
behavior.
"""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _constraints() -> list[str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return pyproject["tool"]["uv"].get("constraint-dependencies", [])


@pytest.mark.sanity
def test_sqlalchemy_is_constrained_below_2_1() -> None:
    assert "sqlalchemy<2.1" in _constraints(), (
        "AppWorld's /initialize returns 500 on SQLAlchemy 2.1+; drop this constraint "
        "only once AppWorld stops parsing the rendered URL (see #213)"
    )


@pytest.mark.sanity
def test_sqlmodel_is_constrained_below_0_0_45() -> None:
    assert "sqlmodel<0.0.45" in _constraints(), (
        "AppWorld's datetime writes return 500 on sqlmodel 0.0.45+; drop this "
        "constraint only once AppWorld opts its datetime fields into naive storage "
        "(see #213)"
    )
