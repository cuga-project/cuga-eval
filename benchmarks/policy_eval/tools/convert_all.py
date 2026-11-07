"""Convert every policy artifact to a policy package and prove that each returns to its own format.

    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/convert_all.py

Writes benchmarks/policy_eval/packages/<bench>/<id>/<source>/package.json. ``<source>`` keeps legacy artifacts of one
policy apart: conversion does not merge them. Every package is read back from disk, written to the source format and
compared with the artifact. A package that already exists keeps its ``tests`` (decision tests written from the policy text;
no source artifact holds them). ``dropped fields`` counts the values of the artifact that did not come back; ``added`` and
``reordered`` are the other two ways the result can differ. Exit code 1 if any of them is not 0.

Only JSON artifacts: not ``cache/`` folders and not ``*_graph.py``.

Packages made with the skill (source ``skill_v1``, ``tools/import_skill_packages.py``) have no source artifact in this table:
they are made from policy text, not converted from a build, so this tool neither writes nor drops them. It checks that: the
files of every ``skill_v1`` folder are hashed before the conversion and after it, and a difference is a failure.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, NamedTuple, Tuple

from cuga.policy_layer.package import (
    from_build,
    from_store_graph,
    load_package,
    save_package,
    to_build,
    to_store_graph,
)

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "packages"
AS_BUILD = (from_build, to_build)
AS_GRAPH = (from_store_graph, to_store_graph)


def split_name(path: Path) -> Tuple[str, str]:
    """``e2891a7b98.v4A.json`` → (``e2891a7b98``, ``v4A``)."""
    stem, _, variant = path.name[: -len(".json")].partition(".")
    return stem, variant


class Artifacts(NamedTuple):
    pattern: str  # under benchmarks/policy_eval
    bench: str
    source: str  # a variant in the file name is added: builds_v4 + v4A = builds_v4_v4A
    convert: Tuple[Callable, Callable]
    id_of: Callable[[Path], str] = lambda p: split_name(p)[0]
    variant_of: Callable[[Path], str] = lambda p: split_name(p)[1]
    skip: Callable[[Path], bool] = lambda p: False  # a file the pattern matches that another entry converts


ARTIFACTS = [
    Artifacts("builds_v2/*.json", "itsm", "builds_v2", AS_BUILD),
    Artifacts("builds/*.before_filters.json", "itsm", "builds", AS_BUILD),
    # the builds that the IT service runner reads by default (after the tuning filters): source ``builds``
    Artifacts(
        "builds/*.json", "itsm", "builds", AS_BUILD, skip=lambda p: split_name(p)[1] == "before_filters"
    ),
    Artifacts("builds_v4/*.json", "itsm", "builds_v4", AS_BUILD),
    Artifacts(
        "builds_v5/*.json", "itsm", "builds_v5", AS_BUILD
    ),  # the pipeline with the repairs inside (change 131)
    Artifacts(
        "gold/*.build.json",
        "itsm",
        "gold",
        AS_BUILD,
        lambda p: p.name[: -len(".build.json")].removeprefix("itsm-"),
        lambda p: "",
    ),
    Artifacts("gold/ab/*/build.json", "automationbench", "gold", AS_BUILD, lambda p: p.parent.name),
    Artifacts("builds_handbook/v3/*.json", "handbook", "v3", AS_BUILD),
    Artifacts("builds_handbook/v4/*.json", "handbook", "v4", AS_BUILD),
    Artifacts("graphs_handbook/claude_v1/*.json", "handbook", "claude_v1", AS_GRAPH),
    Artifacts("tau2/builds/telecom.json", "tau2_telecom", "builds", AS_BUILD),
]


def paths_of(artifacts: Artifacts) -> List[Path]:
    """The artifact files of one entry: what the pattern matches, less what ``skip`` leaves to another entry."""
    return [p for p in sorted(HERE.glob(artifacts.pattern)) if not artifacts.skip(p)]


def target_of(artifacts: Artifacts, path: Path) -> Path:
    """The package file of one artifact."""
    variant = artifacts.variant_of(path)
    source = f"{artifacts.source}_{variant}" if variant else artifacts.source
    return OUT / artifacts.bench / artifacts.id_of(path) / source / "package.json"


def differences(a: Any, b: Any, path: str = "") -> Iterator[Tuple[str, str]]:
    """(kind, path) for every way ``b`` differs from ``a``: dropped, added or reordered."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k in b:
                yield from differences(a[k], b[k], f"{path}/{k}")
            else:
                yield from (("dropped", p) for p in leaves(a[k], f"{path}/{k}"))
        yield from (("added", f"{path}/{k}") for k in b if k not in a)
        if [k for k in a if k in b] != [k for k in b if k in a]:
            yield "reordered", path
    elif isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from differences(x, y, f"{path}/{i}")
        yield from (
            ("dropped", p) for i, x in enumerate(a[len(b) :], len(b)) for p in leaves(x, f"{path}/{i}")
        )
        yield from (("added", f"{path}/{i}") for i in range(len(a), len(b)))
    elif type(a) is not type(b) or a != b:
        yield "dropped", path


def leaves(value: Any, path: str) -> Iterator[str]:
    if isinstance(value, dict) and value:
        for k, v in value.items():
            yield from leaves(v, f"{path}/{k}")
    elif isinstance(value, list) and value:
        for i, v in enumerate(value):
            yield from leaves(v, f"{path}/{i}")
    else:
        yield path


def skill_files() -> Dict[str, str]:
    """Hash of every file under a ``skill_v1`` folder (the package, its draft, its audit)."""
    return {
        str(p.relative_to(OUT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(OUT.glob("*/*/skill_v1/*"))
        if p.is_file()
    }


def main() -> int:
    skill_before = skill_files()
    rows: List[Dict[str, Any]] = []
    seen: Dict[Path, Path] = {}
    for artifacts in ARTIFACTS:
        read, write = artifacts.convert
        paths = paths_of(artifacts)
        if not paths:
            print(f"NOT FOUND {artifacts.pattern}")
            return 1
        for path in paths:
            target = target_of(artifacts, path)
            if target in seen:
                print(f"SAME TARGET {target} for {seen[target]} and {path}")
                return 1
            seen[target] = path
            original = json.loads(path.read_text(encoding="utf-8"))
            package = read(original)
            if target.exists():  # decision tests belong to the package and no source artifact holds them
                package.tests = load_package(target).tests
            save_package(package, target)
            package = load_package(target)
            found = list(differences(original, write(package)))
            count = {k: sum(kind == k for kind, _ in found) for k in ("dropped", "added", "reordered")}
            rows.append({"target": target, "size": target.stat().st_size, "count": count})
            print(
                f"{str(target.relative_to(OUT).parent):<72} rules={len(package.rules):<4}"
                f" procedures={len(package.procedures):<3} documents={len(package.documents)} tests kept={len(package.tests):<3}"
                f" {target.stat().st_size / 1024:8.1f} KB  dropped fields: {count['dropped']}"
                + (f"  added: {count['added']}  reordered: {count['reordered']}" if found else "")
            )
            for kind, where in found[:5]:
                print(f"    {kind} {where}")
    skill_after = skill_files()
    changed = sorted(
        k for k in set(skill_before) | set(skill_after) if skill_before.get(k) != skill_after.get(k)
    )
    print(f"\nskill_v1 files: {len(skill_before)} before and after, {len(changed)} changed")
    for name in changed[:5]:
        print(f"    changed {name}")
    total = sum(r["size"] for r in rows)
    wrong = {k: sum(r["count"][k] for r in rows) for k in ("dropped", "added", "reordered")}
    print(
        f"\n{len(rows)} artifacts, {total / 1024 / 1024:.1f} MB of packages."
        f" dropped fields: {wrong['dropped']}, added: {wrong['added']}, reordered: {wrong['reordered']}"
    )
    return 1 if any(wrong.values()) or changed else 0


if __name__ == "__main__":
    sys.exit(main())
