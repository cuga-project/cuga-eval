"""eval_m3 writes results and Vakra prediction files to M3_RESULTS_DIR when it is set."""

from pathlib import Path

import pytest

from benchmarks.m3 import eval_m3

pytestmark = pytest.mark.sanity


def test_results_dir_defaults_to_the_package_folder_and_honours_the_env(monkeypatch, tmp_path):
    monkeypatch.delenv("M3_RESULTS_DIR", raising=False)
    assert eval_m3._results_dir() == Path(eval_m3.__file__).parent / "results"
    monkeypatch.setenv("M3_RESULTS_DIR", str(tmp_path))
    assert eval_m3._results_dir() == tmp_path
    written = eval_m3.write_predictions_no_gt(
        [{"uuid": "u-1", "response": "42"}], eval_m3._results_dir(), "hockey"
    )
    assert written is not None and Path(written).is_relative_to(tmp_path)
