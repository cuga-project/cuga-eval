"""Regression tests for issue #61.

`./benchmarks/m3/eval.sh --m3-data` (no path) previously errored out:

    Error: --m3-data requires a path (zip file or directory)

even though `config/m3_registry_m3_data.yaml` already documented a
`./benchmarks/m3/eval.sh --m3-data  # default zip` invocation. There was no
default dataset bundled with the repo — `benchmarks/m3/data/*.zip` was
blanket-gitignored as "proprietary — do not commit".

`benchmarks/m3/data/small_train.zip` (a 200-task subset of VAKRA, IBM
Research, CC BY-NC-SA 4.0 — see benchmarks/m3/data/NOTICE) is now committed
and used as the default `--m3-data` source when no path is given.

These tests guard:
- small_train.zip is tracked in git (the .gitignore carve-out isn't dropped).
- the zip is free of macOS metadata (__MACOSX/, .DS_Store).
- eval.sh defaults `--m3-data` (no path) to data/small_train.zip, still
  accepts an explicit path, and documents the default in --help.
- M3DataLoader can load the bundled zip and its capabilities/domains match
  config/m3_registry_m3_data.yaml.
- the CC BY-NC-SA 4.0 license carve-out (root LICENSE, benchmarks/m3/data/
  LICENSE and NOTICE) is present, since this data is NOT covered by the
  repo's Apache 2.0 license.
"""

import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

from benchmarks.m3.m3_data_loader import M3DataLoader

pytestmark = pytest.mark.sanity

ROOT = Path(__file__).resolve().parents[3]
EVAL_SH = ROOT / "benchmarks" / "m3" / "eval.sh"
DATA_DIR = ROOT / "benchmarks" / "m3" / "data"
SMALL_TRAIN_ZIP = DATA_DIR / "small_train.zip"
REGISTRY_YAML = ROOT / "benchmarks" / "m3" / "config" / "m3_registry_m3_data.yaml"


def test_small_train_zip_is_tracked_in_git() -> None:
    result = subprocess.run(  # noqa: S603 — fixed args, no shell, no untrusted input
        ["git", "ls-files", "--error-unmatch", "benchmarks/m3/data/small_train.zip"],  # noqa: S607 — git resolved from PATH
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"small_train.zip must be tracked in git (not gitignored): {result.stderr}"


def test_small_train_zip_has_no_macos_cruft() -> None:
    with zipfile.ZipFile(SMALL_TRAIN_ZIP) as zf:
        names = zf.namelist()
    assert not any(n.startswith("__MACOSX") for n in names), names
    assert not any(n.endswith(".DS_Store") for n in names), names


def test_eval_sh_m3_data_defaults_to_bundled_zip_when_path_omitted() -> None:
    content = EVAL_SH.read_text()
    assert 'M3_DATA_PATH="$SCRIPT_DIR/data/small_train.zip"' in content


def test_eval_sh_m3_data_still_accepts_explicit_path() -> None:
    content = EVAL_SH.read_text()
    assert 'M3_DATA_PATH="$2"' in content


def test_eval_sh_help_documents_default_m3_data() -> None:
    result = subprocess.run(  # noqa: S603
        ["bash", str(EVAL_SH), "--help"],  # noqa: S607 — bash resolved from PATH
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "small_train.zip" in result.stdout
    assert "default" in result.stdout.lower()


def test_m3_data_loader_loads_bundled_default_matching_registry() -> None:
    loader = M3DataLoader(str(SMALL_TRAIN_ZIP))
    assert loader.available_capabilities() == [2, 3]

    registry = yaml.safe_load(REGISTRY_YAML.read_text())
    expected = {}
    for svc in registry["services"]:
        (config,) = svc.values()
        expected[config["metadata"]["task_id"]] = set(config["metadata"]["domains"])

    for task_id, domains in expected.items():
        assert set(loader.available_domains(task_id)) == domains, f"capability {task_id}"


def test_gitignore_carves_out_small_train_zip() -> None:
    gitignore = (ROOT / ".gitignore").read_text()
    assert "!benchmarks/m3/data/small_train.zip" in gitignore


def test_license_carve_out_documented() -> None:
    root_license = (ROOT / "LICENSE").read_text()
    assert "CC BY-NC-SA" in root_license
    assert "small_train.zip" in root_license

    data_license = (DATA_DIR / "LICENSE").read_text()
    assert "Attribution-NonCommercial-ShareAlike 4.0" in data_license

    notice = (DATA_DIR / "NOTICE").read_text()
    assert "CC BY-NC-SA" in notice
    assert "VAKRA" in notice
