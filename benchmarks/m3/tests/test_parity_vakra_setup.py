"""Rebuilding the kit's VAKRA side from public sources (parity/setup_vakra.sh): pin files and scripts, no network."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.sanity

PARITY = Path(__file__).resolve().parents[1] / "parity"
PINS = PARITY / "vakra"
BASH = shutil.which("bash") or "/bin/bash"


@pytest.mark.parametrize("script", ["setup_vakra.sh", "setup_pinned_cuga.sh", "lsf_arm.sh"])
def test_setup_scripts_parse(script):
    subprocess.run([BASH, "-n", str(PARITY / script)], check=True)  # noqa: S603  (fixed, trusted args)


def test_help_lists_the_steps_without_touching_the_network():
    out = subprocess.run(  # noqa: S603  (fixed, trusted args)
        [BASH, str(PARITY / "setup_vakra.sh"), "--help"], capture_output=True, text=True, check=True
    ).stdout
    for step in ("code", "evaluator", "data", "universes", "image", "link"):
        assert re.search(rf"^#\s+{step}\s", out, re.M), step


def test_pins_are_full_commit_and_revision_ids():
    text = (PARITY / "setup_vakra.sh").read_text()
    for var in ("VAKRA_REF", "VAKRA_EVALUATOR_REF", "VAKRA_DATA_REV"):
        m = re.search(rf'{var}="\$\{{{var}:-([0-9a-f]+)\}}"', text)
        assert m and len(m.group(1)) == 40, var


@pytest.mark.parametrize(
    "path",
    [
        PINS / "benchmark_environ.constraints.txt",
        PINS / "evaluator.requirements.txt",
        PARITY / "venv_overrides.cuga-main-88fd3549.txt",
    ],
)
def test_version_files_hold_one_exact_pin_per_package(path):
    lines = [ln for ln in path.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    assert lines
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+==[^\s;@]+", ln) for ln in lines)
    names = [re.sub(r"[-_.]+", "-", ln.split("==")[0]).lower() for ln in lines]
    assert len(names) == len(set(names))


def test_patches_touch_only_the_files_setup_resets():
    touched = set()
    for patch in sorted((PINS / "patches").glob("*.patch")):
        text = patch.read_text()
        assert re.search(r"^@@ ", text, re.M), patch.name
        touched |= set(re.findall(r"^\+\+\+ b/(\S+)", text, re.M))
    # setup_vakra.sh's code step only resets these paths (and the tool-universe mapping) before re-applying
    assert touched == {"evaluator/judge.py", "benchmark/mcp_client.py"}


def test_notice_names_the_license_of_the_patches():
    notice = (PINS / "NOTICE").read_text()
    assert "CC BY-NC-SA 4.0" in notice
    for patch in (PINS / "patches").glob("*.patch"):
        assert patch.name in notice
