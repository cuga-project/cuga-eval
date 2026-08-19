"""Timestamp conventions for evaluation bundles.

Two rules, easy to regress in opposite directions:

1. Bundle *directory names* are local wall-clock time, matching the ``RUN_ID``
   from ``eval.sh`` and the results JSON filename. A UTC name made one run look
   like two runs an offset apart.
2. ``metadata.json``'s ``created_at`` is UTC and valid ISO-8601. It used to be
   built as ``isoformat() + "Z"``, yielding ``...+00:00Z`` — which
   ``datetime.fromisoformat`` rejects, silently breaking the ``--since`` bundle
   filter in ``analytics/trace_comparison_rules/pipeline.py``.

The TZ is pinned to a non-UTC zone (and ``time.tzset()`` called) so a UTC CI
runner cannot make a local-vs-UTC mix-up pass by coincidence.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone

import pytest

from analytics.trace_comparison_rules.pipeline import _parse_created_at
from benchmarks.helpers import bundle

# UTC+5:45 — a half/quarter-hour offset, so a wrong-clock stamp cannot coincide
# with the right one at any minute of the day.
_TZ = "Asia/Kathmandu"
_OFFSET = timedelta(hours=5, minutes=45)


@pytest.fixture
def non_utc_tz(monkeypatch):
    monkeypatch.setenv("TZ", _TZ)
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.mark.sanity
def test_bundle_timestamp_is_local_not_utc(non_utc_tz):
    stamp = bundle._bundle_timestamp()
    assert re.fullmatch(r"\d{8}_\d{6}", stamp)

    parsed = datetime.strptime(stamp, "%Y%m%d_%H%M%S")
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    # Local (UTC+5:45) must be ~the offset ahead of UTC, not equal to it.
    assert abs((parsed - (now_utc + _OFFSET)).total_seconds()) < 60
    assert abs((parsed - now_utc).total_seconds()) > 60


@pytest.mark.sanity
def test_created_at_is_utc_and_round_trips(non_utc_tz):
    raw = bundle._utc_now_iso()

    # The bug this guards: a second zone designator on an offset-bearing string.
    assert not raw.endswith("Z")

    parsed = datetime.fromisoformat(raw)  # must not raise
    assert parsed.utcoffset() == timedelta(0)
    assert abs((parsed - datetime.now(timezone.utc)).total_seconds()) < 60


@pytest.mark.sanity
def test_workspace_metadata_created_at_parses(non_utc_tz, tmp_path):
    bd = tmp_path / "exp"
    bundle.create_workspace_bundle(bd, "m3", experiment_name="exp")

    created_at = json.loads((bd / "metadata.json").read_text())["created_at"]
    parsed = datetime.fromisoformat(created_at)
    assert parsed.utcoffset() == timedelta(0)


@pytest.mark.sanity
def test_run_env_header_has_single_zone_designator(non_utc_tz, tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "openai/gpt-oss-120b")
    bd = tmp_path / "b"
    bd.mkdir()
    bundle._write_run_env(bd)

    header = next(
        line
        for line in (bd / "config" / "run.env").read_text().splitlines()
        if line.startswith("# Generated:")
    )
    stamp = header.split("# Generated:", 1)[1].strip()
    assert datetime.fromisoformat(stamp).utcoffset() == timedelta(0)


@pytest.mark.sanity
@pytest.mark.parametrize(
    "raw,expected_utc_hour",
    [
        ("2026-03-12T19:02:30+00:00", 19),  # current form
        ("2026-03-12T19:02:30+00:00Z", 19),  # legacy malformed form
        ("2026-03-12T19:02:30Z", 19),  # bare Z designator
        ("2026-03-12T19:02:30+05:45", 13),  # offset-bearing, non-UTC
        ("2026-03-12T19:02:30+05:45Z", 13),  # legacy malformed, non-UTC offset
    ],
)
def test_parse_created_at_handles_legacy_and_current_forms(raw, expected_utc_hour):
    parsed = _parse_created_at(raw)
    assert parsed.astimezone(timezone.utc).hour == expected_utc_hour


@pytest.mark.sanity
def test_parse_created_at_rejects_naive_timestamp():
    """A naive value must raise ValueError, not return a naive datetime.

    ``discover_bundles`` compares the result against a UTC-aware cutoff, so
    returning a naive datetime raises TypeError there and aborts the entire
    run. ValueError routes it into the existing warn-and-include branch.
    """
    with pytest.raises(ValueError):
        _parse_created_at("2026-03-12T19:02:30")


@pytest.mark.sanity
def test_discover_bundles_survives_bad_created_at(tmp_path, monkeypatch, capsys):
    """A bundle with an unusable created_at is warned about and included."""
    from analytics.trace_comparison_rules import pipeline

    monkeypatch.setattr(pipeline, "_project_root", tmp_path)
    root = tmp_path / "benchmarks" / "m3" / "evaluation_bundles"

    stamps = {
        "naive": "2026-03-12T19:02:30",  # would TypeError without the guard
        "legacy": "2026-03-12T19:02:30+00:00Z",
        "current": "2026-03-12T19:02:30+00:00",
        "garbage": "not-a-timestamp",
    }
    for name, stamp in stamps.items():
        d = root / name
        d.mkdir(parents=True)
        (d / "metadata.json").write_text(json.dumps({"created_at": stamp}))

    found = pipeline.discover_bundles("m3", ["all"], since="2026-01-01")

    assert {d.name for d in found} == set(stamps)
    assert "naive" in capsys.readouterr().out
