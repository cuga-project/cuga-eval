"""Regression test: eval.sh must surface a resume hint when the M3 docker
environment-failure exit code (3) is seen. See
docs/superpowers/specs/2026-07-13-m3-docker-env-health-check-design.md.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.sanity

ROOT = Path(__file__).resolve().parents[3]
EVAL_SH = ROOT / "benchmarks" / "m3" / "eval.sh"


def test_eval_sh_special_cases_exit_code_3():
    content = EVAL_SH.read_text()
    assert "elif [ $EVAL_EXIT -eq 3 ]; then" in content


def test_eval_sh_prints_resume_experiment_hint_on_exit_code_3():
    content = EVAL_SH.read_text()
    exit3_idx = content.index("elif [ $EVAL_EXIT -eq 3 ]; then")
    else_idx = content.index("else", exit3_idx)
    exit3_block = content[exit3_idx:else_idx]
    assert "--resume-experiment" in exit3_block
    assert "docker environment failure" in exit3_block
