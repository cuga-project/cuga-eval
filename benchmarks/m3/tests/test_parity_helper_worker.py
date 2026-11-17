"""Helper worker (run_cuga_eval_arm.sh PARITY_HELPER=1): domain order, the main worker's position, the stop rule."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.sanity

SCRIPT = Path(__file__).resolve().parents[1] / "parity" / "run_cuga_eval_arm.sh"


def _helper_functions() -> str:
    text = SCRIPT.read_text()
    m = re.search(r'^HELPER="\$\{PARITY_HELPER:-0\}"\n.*?^main_pos\(\) \{.*?^\}\n', text, re.S | re.M)
    assert m, "helper block not found in run_cuga_eval_arm.sh"
    return m.group(0)


def _run(tmp_path, body: str) -> str:
    out = tmp_path / "out"
    (out / "prediction").mkdir(parents=True, exist_ok=True)
    script = (
        'ARM=cuga_eval_cap1_fc; DOMS="a b c d e f g"; OUT="$1"; PARITY_HELPER=1\n'
        + _helper_functions()
        + body
    )
    bash = shutil.which("bash") or "/bin/bash"
    proc = subprocess.run(  # noqa: S603 — this repo's script text, run by bash
        [bash, "-c", script, "bash", str(out)], capture_output=True, text=True, check=True
    )
    return proc.stdout


def test_helper_walks_the_domains_from_the_end(tmp_path):
    assert _run(tmp_path, 'echo "$DOM_LIST"\n').split() == list("gfedcba")


def test_main_position_is_the_latest_started_domain(tmp_path):
    body = (
        'echo "[$ARM] start 2026-10-21 14:12:16 domains: $DOMS" > "$OUT/console.log"\n'
        'main_pos\n'
        'printf "[%s] a start 14:12:20\\n[%s] a done rc=0 in 5s\\n[%s] b start 14:13:00\\n" $ARM $ARM $ARM'
        ' >> "$OUT/console.log"\n'
        'main_pos\n'
        'dom_pos e; dom_pos zz\n'
    )
    assert _run(tmp_path, body).split() == ["-1", "1", "4", "-1"]  # "start" with no domain is not a domain
