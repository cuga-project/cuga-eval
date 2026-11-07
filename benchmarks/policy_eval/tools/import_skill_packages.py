"""Import the packages that fresh agents made with the skill (Task 3.4) as source ``skill_v1``.

    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/import_skill_packages.py [--src /tmp/pkg34]

Each author folder holds ``set.json``, ``draft.json``, ``tools.json`` and ``package.json``. The package is made again with
``cli pack --tests`` from the draft and the set (the same command the author used, plus the decision tests of another
agent that wrote them from the policy text only). The result is written to
``benchmarks/policy_eval/packages/<bench>/<id>/skill_v1/package.json`` and the draft is kept beside it as ``draft.json``.

ITSM ``e2891a7b98`` has no new tests: its 347 stored blind tests (written from the text by a strong model, without the
rules) are copied into the package as they are. Their ``statement_id`` values come from an older split of the text, so
``pack`` would refuse them; they are stored directly and counted. The other 8 ITSM versions have no tests.

A package that exists is never replaced unless ``--replace`` is given. ``set.json`` is kept beside each package, so
``--check`` makes every package again from the folder alone (no ``/tmp`` input). Nothing else under ``packages/`` is touched.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cuga.policy_layer.cli import main as cli_main
from cuga.policy_layer.package import load_package

sys.path.insert(0, str(Path(__file__).resolve().parent))
HERE = Path(__file__).resolve().parent.parent
PACKAGES = HERE / "packages"
SOURCE = "skill_v1"
HANDBOOK = [
    "hr_crestwood_university_79786c46",
    "insurance_vanguard_shield_mutual_9b2f7a29",
    "medical_careig_specialty_pharmacy_f5947c33",
]
# (benchmark, policy id, author folder, tests file relative to --src or None)
ENTRIES: List[Tuple[str, str, str, Optional[str]]] = [
    ("handbook", HANDBOOK[0], "hb_" + HANDBOOK[0], "/tmp/skill_trial2_tests/tests.json"),  # noqa: S108
    ("handbook", HANDBOOK[1], "hb_" + HANDBOOK[1], "hb_" + HANDBOOK[1] + ".tests/tests.json"),
    ("handbook", HANDBOOK[2], "hb_" + HANDBOOK[2], "hb_" + HANDBOOK[2] + ".tests/tests.json"),
    ("itsm", "e2891a7b98", "itsm_base", None),  # the stored blind tests of the existing package
    ("tau2_telecom", "telecom", "tau2_telecom", "tau2_telecom.tests/tests.json"),
    ("tau2_airline", "airline", "tau2_airline", "tau2_airline.tests/tests.json"),
    ("tau2_retail", "retail", "tau2_retail", "tau2_retail.tests/tests.json"),
]
ITSM_STORED_TESTS = PACKAGES / "itsm" / "e2891a7b98" / "builds" / "package.json"


def statement_ids(package_or_set: Dict[str, Any]) -> set:
    return {
        st["id"]
        for doc in package_or_set.get("documents") or []
        for sec in doc.get("sections") or []
        for st in sec.get("statements") or []
    }


def tests_report(name: str, cases: List[Dict[str, Any]], ids: set) -> str:
    known = sum(1 for c in cases if c.get("statement_id") in ids)
    return f"{name}: {len(cases)} tests, {known} with a statement id that exists in the package"


def write_package(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def import_one(
    src: Path, bench: str, policy: str, folder: str, tests: Optional[str], replace: bool
) -> Tuple[Path, str]:
    target = PACKAGES / bench / policy / SOURCE / "package.json"
    if target.exists() and not replace:
        return target, "exists, left as it is (--replace to make it again)"
    author = src / folder
    if tests is not None:
        tests_path = Path(tests) if tests.startswith("/") else src / tests
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "package.json"
            args = [
                "pack",
                str(author / "set.json"),
                str(author / "draft.json"),
                "-o",
                str(out),
                "--harness",
                "claude-code",
                "--model",
                "claude-opus",
                "--tools",
                str(author / "tools.json"),
                "--tests",
                str(tests_path),
            ]
            if cli_main(args) != 0:
                raise SystemExit(f"pack failed for {folder}")
            data = json.loads(out.read_text(encoding="utf-8"))
    else:
        data = json.loads((author / "package.json").read_text(encoding="utf-8"))
        if bench == "itsm" and policy == "e2891a7b98":
            data["tests"] = json.loads(ITSM_STORED_TESTS.read_text(encoding="utf-8"))["tests"]
    write_package(target, data)
    shutil.copyfile(author / "draft.json", target.parent / "draft.json")
    shutil.copyfile(author / "set.json", target.parent / "set.json")
    return target, tests_report("tests", data.get("tests") or [], statement_ids(data))


def import_itsm_others(src: Path, replace: bool) -> List[Tuple[Path, str]]:
    done = []
    for folder in sorted((src / "itsm_others" / "out").iterdir()):
        if not (folder / "package.json").is_file():
            continue
        target = PACKAGES / "itsm" / folder.name / SOURCE / "package.json"
        if target.exists() and not replace:
            done.append((target, "exists, left as it is"))
            continue
        data = json.loads((folder / "package.json").read_text(encoding="utf-8"))
        write_package(target, data)
        shutil.copyfile(folder / "draft.json", target.parent / "draft.json")
        shutil.copyfile(folder / "set.json", target.parent / "set.json")
        done.append((target, "no tests"))
    return done


def repack(folder: Path) -> List[str]:
    """Make the package again from the files kept beside it (``set.json``, ``draft.json``, its own tests and the tool specs of
    the benchmark) and return the top-level keys that differ from ``package.json``. An empty list: the import repeats with
    nothing from outside this folder. Tests whose statement ids are not in the set (the stored ITSM tests) cannot go through
    ``pack``; they are put into the result the way the import put them."""
    from validate_all import specs_of

    bench, policy = folder.parts[-3], folder.parts[-2]
    kept = json.loads((folder / "package.json").read_text(encoding="utf-8"))
    ids = statement_ids(json.loads((folder / "set.json").read_text(encoding="utf-8")))
    tests = kept.get("tests") or []
    packable = all(c.get("statement_id") in ids for c in tests)
    with tempfile.TemporaryDirectory() as tmp:
        tools, tests_file, out = (
            Path(tmp) / "tools.json",
            Path(tmp) / "tests.json",
            Path(tmp) / "package.json",
        )
        tools.write_text(json.dumps(specs_of(bench, policy)), encoding="utf-8")
        tests_file.write_text(json.dumps(tests if packable else []), encoding="utf-8")
        args = ["pack", str(folder / "set.json"), str(folder / "draft.json"), "-o", str(out)]
        who = kept.get("generator") or {}  # the harness and model that wrote the draft, as the package says
        args += ["--harness", who.get("harness", ""), "--model", who.get("model", ""), "--tools", str(tools)]
        if tests and packable:
            args += ["--tests", str(tests_file)]
        if cli_main(args) != 0:
            return ["pack failed"]
        made = json.loads(out.read_text(encoding="utf-8"))
    if tests and not packable:
        made["tests"] = tests
    return [k for k in sorted(set(kept) | set(made)) if kept.get(k) != made.get(k)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/tmp/pkg34")  # noqa: S108
    ap.add_argument("--replace", action="store_true")
    ap.add_argument(
        "--check",
        action="store_true",
        help="do not import: make every skill_v1 package again from the files beside it and say which keys differ",
    )
    a = ap.parse_args()
    if a.check:
        bad = 0
        for path in sorted(PACKAGES.glob("*/*/skill_v1/package.json")):
            diff = repack(path.parent)
            bad += bool(diff)
            print(
                f"{path.relative_to(PACKAGES).parent!s:<48} {'same' if not diff else 'DIFFERS: ' + ', '.join(diff)}"
            )
        return 1 if bad else 0
    src = Path(a.src)
    done = [import_one(src, *e, a.replace) for e in ENTRIES] + import_itsm_others(src, a.replace)
    for target, note in done:
        pkg = load_package(target)
        print(f"{target.relative_to(PACKAGES).parent!s:<48} rules={len(pkg.rules):<3} {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
