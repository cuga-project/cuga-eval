#!/usr/bin/env python3
"""Registry of the task sets (tuning and held-out) and of which agent model has already run their tasks.

  python3 benchmarks/policy_eval/sets/build_registry.py [--no-write]

Reads the set files (policy_eval_tasks*.json, automationbench/policy_types_*.json, the ITSM and AutomationBench pilots,
versioned_dev.json, the tau2 set files and official splits), scans the result folders, and writes registry.json next to
this file. It prints, per agent model, which held-out sets the model has not run.

Entry: id, benchmark, path, key, id_field, rule, seed, n, status (tuning | heldout), seen_by {model: [run prefixes]},
seen_n {model: how many of the set's tasks the model ran}. `path` is relative to the repo root, or starts with ~.
`key` is the dotted path to the task list inside the file (null: the file is the list); `id_field` names the id inside a
list of objects. A set with no file (HANDBOOK) holds `ids` itself.

seen_by: a model ran a task of the set. Matching is by benchmark and task id, never by run name. Every result file
counts, also an errored, smoke or discarded run, because the model has read the task. The model is the agent model of the
result: `model` (AutomationBench, ITSM), `agent_model` (tau2, and every result of the harness), `receipt.models` (HANDBOOK,
whose `model` is null). A result
whose model cannot be determined is recorded under `unknown`. Models of the policy layer (gate, tracker, detector) are not
agent models and are not counted. A run prefix is the result folder name without its trial suffix (ph_AF_t1 -> ph_AF; tau2
logging_test1_A_s0 -> test1_A).

Each set also has a `label` (`tuning`, `seen` or `held-out`; `set_label`): a held-out set that a model has run is `seen`, never
`held-out`.

A rebuild never takes a model or a run away from `seen_by`: the scan is merged with the registry file (`keep_seen`), and what
only the file holds is printed. A model that has read a task stays one that has read it when the result folder is moved, is on
another worktree, or is deleted: every label comes from `seen_by`, and a loss would turn `seen` into `held-out` with no word.

`policies`: for each policy that has a package, `"<package bench>/<package policy>"` -> `{tuning_sets, heldout_sets,
tuned_by_changes}` and, where the sets alone do not say what a policy was used for, a hand-kept `note` (`POLICY_NOTES`). The sets come from joining the task ids of each set to a policy (ITSM: `_policy_hash` of the task in
itsm_oracle.json; AutomationBench and HANDBOOK: the task id is the policy folder; tau2: the set's benchmark). `tuned_by_changes`
is kept by hand in `TUNED_BY_CHANGES`: a policy can be tuned on with no set that names it (change 131 fixed the pipeline on
`d5ab75ff0f`). `rule_audit.py` reads this section to say what kind of numbers an audit shows, and nothing else of the registry.

Consumers: `load_registry()`, `get_entry(set_id)`, `task_ids(entry)`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, NamedTuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BENCH = REPO / "benchmarks"
REGISTRY = HERE / "registry.json"
TAU2_ROOT = Path.home() / "dev/cuga-eval-tau2/benchmarks/tau2"
TAU2_SPLITS = "~/dev/cuga-eval-tau2/benchmarks/tau2/tau2-bench/data/tau2/domains/{domain}/split_tasks.json"
HB_SAMPLE_TASKS = (
    "~/dev/untrusted/handbook-sample/tasks"  # untrusted download, read-only: this script never opens it
)
HB_TASKS = [  # the 3 public HANDBOOK tasks (names of the folders under HB_SAMPLE_TASKS; also the names in the result files)
    "hr_crestwood_university_79786c46",
    "insurance_vanguard_shield_mutual_9b2f7a29",
    "medical_careig_specialty_pharmacy_f5947c33",
]

PE = "benchmarks/policy_eval/policy_eval_tasks"
AB = "benchmarks/automationbench"


def S(id, benchmark, path, key, id_field, status, rule, seed="file"):
    return dict(
        id=id, benchmark=benchmark, path=path, key=key, id_field=id_field, status=status, rule=rule, seed=seed
    )


TUNED_BY_CHANGES = {  # kept by hand: policies the pipeline was repaired on, whether or not a set names them (changes.md)
    "itsm/e2891a7b98": [105, 107, 112, 113, 114, 115, 116, 117, 118, 131],
    "itsm/d5ab75ff0f": [131],
}
POLICY_NOTES = {  # kept by hand: what a policy was used for, where the sets alone do not say it (changes.md)
    "tau2_airline/airline": (
        "the official test split (20 tasks) was run before this package existed: the headroom checks `a20_ds` and `a20_oss`, "
        "and the no-harm check of the SOP tracker `air1` (arms A and T, 5 trials, change 87). The runs and the agent writes "
        "were reviewed (change 87, `tau2/labels.md`). The result of `air1` (tracker 17/20 against 11/20) is the evidence "
        "for design decision 1 of the design spec (route by the shape of the policy source), and Task 5.3 (rule-list route) "
        "implements that decision and is checked on this package. The package was made from the policy text only and no "
        "rule, test or setting was changed from these runs, but the tasks, the runs and the failures are seen: numbers on "
        "this split are not a clean bar"
    ),
    "tau2_retail/retail": "no run has used this policy (no task set, no change)",
}
ITSM_ORACLE = BENCH / "enterpriseops_gym" / "tasks" / "itsm_oracle.json"

ITSM_POOL = (
    "ITSM oracle tasks whose prompt involves status changes, change requests, SLA or approvals (keyword rule), minus the 5 "
    "pilot tasks and the 2 tasks with broken verifiers (upstream issues 21, 22)"
)
AB_POOL = (
    "AutomationBench public tasks in the detector-probe pool with a record that Gemini labelled as a policy and at least one "
    "must-not check; minus the pilot and cross-reference tasks; at most 2 per domain"
)
SPECS = [
    # EnterpriseOps-Gym ITSM
    S(
        "itsm-pilot",
        "itsm",
        "benchmarks/enterpriseops_gym/tasks/pilot.json",
        "tasks",
        "task_id",
        "tuning",
        None,
    ),
    S(
        "itsm-xref",
        "itsm",
        f"{PE}.json",
        "itsm.xref",
        None,
        "tuning",
        "cross-reference study: one task on policy version cb2d4ee021 and one on c47f8ceef3 (seeded pick), kept out of the tuning and unseen sets",
    ),
    # EnterpriseOps-Gym CSM
    S(
        "csm-probe",
        "csm",
        "benchmarks/enterpriseops_gym/tasks/csm_sets.json",
        "probe",
        None,
        "tuning",
        "CSM oracle tasks without same-name verifiers (upstream issue 23); the 12 policy versions with the longest policy "
        "text; one task per version (seed 20261108); first look at the domain",
    ),
    S(
        "csm-tune2",
        "csm",
        "benchmarks/enterpriseops_gym/tasks/csm_sets.json",
        "tune2",
        None,
        "tuning",
        "CSM tasks without same-name verifiers, minus csm-probe; seed 20261109; 18 tuning tasks",
    ),
    S(
        "csm-heldout",
        "csm",
        "benchmarks/enterpriseops_gym/tasks/csm_sets.json",
        "heldout",
        None,
        "heldout",
        "CSM tasks without same-name verifiers, minus csm-probe and csm-tune2 (seed 20261109); run once, after freeze",
    ),
    S("itsm-tune", "itsm", f"{PE}.json", "itsm.tune", None, "tuning", f"{ITSM_POOL}; 10 tuning tasks"),
    S(
        "itsm-unseen",
        "itsm",
        f"{PE}.json",
        "itsm.unseen",
        None,
        "heldout",
        f"{ITSM_POOL}; 10 tasks, not the tuning tasks",
    ),
    S(
        "itsm-unseen2",
        "itsm",
        f"{PE}_unseen2.json",
        "itsm.unseen2",
        None,
        "heldout",
        "the remaining tasks of the ITSM pool minus tuning, unseen and cross-reference tasks; 10 tasks",
    ),
    S(
        "itsm-unseen3",
        "itsm",
        f"{PE}_unseen3.json",
        "itsm.unseen3",
        None,
        "heldout",
        "the remaining tasks of the ITSM pool minus tuning, unseen, unseen2 and cross-reference tasks; 10 tasks",
    ),
    # AutomationBench
    S("ab-pilot", "automationbench", f"{AB}/policy_pilot.json", "tasks", "task", "tuning", None),
    S(
        "ab-xref",
        "automationbench",
        f"{PE}.json",
        "automationbench.xref",
        None,
        "tuning",
        "the 5 cross-reference study tasks, kept out of the tuning and unseen sets",
    ),
    S(
        "ab-tune",
        "automationbench",
        f"{PE}.json",
        "automationbench.tune",
        None,
        "tuning",
        f"{AB_POOL}; tuning tasks from the probe's tune half; 10 tasks",
    ),
    S(
        "ab-unseen",
        "automationbench",
        f"{PE}.json",
        "automationbench.unseen",
        None,
        "heldout",
        f"{AB_POOL}; unseen tasks from the probe's test half; 10 tasks",
    ),
    S(
        "ab-unseen2",
        "automationbench",
        f"{PE}_unseen2.json",
        "automationbench.unseen2",
        None,
        "heldout",
        "policy tasks from the detector probe's test half with a must-not check, minus pilot, cross-reference, tuning and unseen tasks; at most 2 per domain; 10 tasks",
    ),
    S(
        "ab-unseen3",
        "automationbench",
        f"{PE}_unseen3.json",
        "automationbench.unseen3",
        None,
        "heldout",
        "policy tasks from the detector probe's test half with a must-not check, minus pilot, cross-reference, tuning, unseen and unseen2 tasks; at most 2 per domain; 10 tasks",
    ),
    S(
        "ab-versioned-dev",
        "automationbench",
        f"{AB}/versioned_dev.json",
        "dev",
        None,
        "tuning",
        "versioned-type tasks of the fresh pool not in policy_types_subset.json; 10 for development",
    ),
    S(
        "ab-versioned-holdout",
        "automationbench",
        f"{AB}/versioned_dev.json",
        "holdout",
        None,
        "heldout",
        "versioned-type tasks of the fresh pool not in policy_types_subset.json; the rest, held out",
    ),
    S(
        "ab-policy-types-subset",
        "automationbench",
        f"{AB}/policy_types_subset.json",
        "tasks",
        "task",
        "tuning",
        "file",
    ),
    S(
        "ab-policy-types-holdout",
        "automationbench",
        f"{AB}/policy_types_holdout.json",
        "tasks",
        "task",
        "heldout",
        "file",
    ),
    S(
        "ab-policy-types-holdout2",
        "automationbench",
        f"{AB}/policy_types_holdout2.json",
        "tasks",
        "task",
        "heldout",
        "file",
    ),
    S(  # tuning since 2026-11-07: its failures were traced after the one frozen run (Haiku 5.5 and gpt-oss, 3 trials)
        "ab-policy-types-fresh3",
        "automationbench",
        f"{AB}/policy_types_fresh3.json",
        "tasks",
        "task",
        "tuning",
        "file",
    ),
    # HANDBOOK
    dict(
        id="handbook-public3",
        benchmark="handbook",
        path=HB_SAMPLE_TASKS,
        key=None,
        id_field=None,
        status="tuning",
        seed=None,
        rule="the 3 public HANDBOOK tasks; every mechanism was tuned on them (in-sample, see best_profiles.json)",
        ids=HB_TASKS,
    ),
    # tau2
    S(
        "tau2-telecom-dev20",
        "tau2-telecom",
        "benchmarks/policy_eval/tau2/telecom_dev20.json",
        None,
        None,
        "tuning",
        "stratified 20-task subset of the official telecom train split (changes.md 76)",
        seed=7,
    ),
    S(
        "tau2-telecom-fresh40",
        "tau2-telecom",
        "benchmarks/policy_eval/tau2/telecom_fresh40.json",
        None,
        None,
        "heldout",
        "40 telecom tasks from the full set that are in none of the official train, test, small and base splits; the selection method is not recorded in the repo",
        seed=None,
    ),
    S(
        "tau2-telecom-test",
        "tau2-telecom",
        TAU2_SPLITS.format(domain="telecom"),
        "test",
        None,
        "heldout",
        "official telecom test split (40 tasks); run before the policy freeze, so not a clean bar any more",
        seed=None,
    ),
    S(
        "tau2-airline-test",
        "tau2-airline",
        TAU2_SPLITS.format(domain="airline"),
        "test",
        None,
        "heldout",
        "official airline test split (20 tasks); the no-harm check of the SOP tracker (rule-type policy)",
        seed=None,
    ),
]


# ── loading task ids ─────────────────────────────────────────────────────────


def resolve(path: str) -> Path:
    return Path(path).expanduser() if path.startswith("~") else REPO / path


def task_ids(entry: dict) -> list[str]:
    """The task ids of a registry entry, in file order."""
    if entry.get("ids"):
        return list(entry["ids"])
    data = json.loads(resolve(entry["path"]).read_text())
    for part in (entry.get("key") or "").split("."):
        if part:
            data = data[part]
    if entry.get("id_field"):
        data = [item[entry["id_field"]] for item in data]
    return [str(x) for x in data]


def load_registry(path: Path = REGISTRY) -> dict:
    return json.loads(path.read_text())


def get_entry(set_id: str, registry: dict | None = None) -> dict:
    for entry in (registry or load_registry())["sets"]:
        if entry["id"] == set_id:
            return entry
    raise KeyError(
        f"no task set {set_id!r}; known: {', '.join(e['id'] for e in (registry or load_registry())['sets'])}"
    )


def _one_line(text: str) -> str:
    return " ".join(text.split())


def build_entries() -> list[dict]:
    entries = []
    for spec in SPECS:
        entry = {k: v for k, v in spec.items()}
        file_data = {}
        if not entry.get("ids"):
            raw = json.loads(resolve(entry["path"]).read_text())
            file_data = raw if isinstance(raw, dict) else {}
        if entry["seed"] == "file":
            entry["seed"] = file_data.get("seed")
        if entry["rule"] in (None, "file"):  # the set file states its own rule
            rule = _one_line(file_data.get("rule") or file_data.get("rules") or "")
            if file_data.get("excluded"):
                rule += " Excluded: " + ", ".join(file_data["excluded"]) + "."
            entry["rule"] = rule
        ids = task_ids(entry)
        if len(set(ids)) != len(ids):
            raise ValueError(f"{entry['id']}: duplicate task ids")
        entry["n"] = len(ids)
        entries.append(entry)
    return entries


def set_label(entry: dict) -> str:
    """What kind of numbers a set gives: ``tuning``; ``seen`` for a held-out set that some agent model has run (any
    ``seen_n`` above 0: its tasks and failures are known, so it is no clean bar); ``held-out`` only for a held-out set that no
    model has run. ``status`` stays as it is: other tools read it."""
    if entry["status"] != "heldout":
        return entry["status"]
    return "seen" if any(n > 0 for n in entry["seen_n"].values()) else "held-out"


def policies_of(entries: list[dict]) -> dict:
    """``"<bench>/<policy>"`` -> the sets that have a task of that policy, and the changes that tuned on it by hand."""
    itsm = {t["task_id"]: t["_policy_hash"] for t in json.loads(ITSM_ORACLE.read_text())}
    out: dict = {}

    def slot(key: str) -> dict:
        return out.setdefault(key, {"tuning_sets": [], "heldout_sets": [], "tuned_by_changes": []})

    for e in entries:
        group = "tuning_sets" if e["status"] == "tuning" else "heldout_sets"
        if e["benchmark"].startswith("tau2-"):  # one policy per domain
            keys = {f"tau2_{e['benchmark'][5:]}/{e['benchmark'][5:]}"}
        elif e["benchmark"] == "itsm":
            keys = {f"itsm/{itsm[t]}" for t in task_ids(e) if t in itsm}
        else:  # the task id is the policy folder (AutomationBench, HANDBOOK)
            keys = {f"{e['benchmark']}/{t}" for t in task_ids(e)}
        for key in keys:
            if e["id"] not in slot(key)[group]:
                slot(key)[group].append(e["id"])
    for key, changes in TUNED_BY_CHANGES.items():
        slot(key)["tuned_by_changes"] = list(changes)
    for key, note in POLICY_NOTES.items():
        slot(key)["note"] = note
    return {
        k: v for k, v in sorted(out.items()) if (HERE.parent / "packages" / k).is_dir()
    }  # only policies with a package


# ── scanning results ─────────────────────────────────────────────────────────


class Record(NamedTuple):
    benchmark: str
    model: str
    task: str
    prefix: str


def run_prefix(folder: str) -> str:
    return re.sub(r"_t\d+(?:_.*)?$", "", folder)


def tau2_prefix(folder: str) -> str:
    return re.sub(r"_s\d+$", "", folder.removeprefix("logging_"))


def _bump(stats: dict, key: str) -> None:
    stats[key] = stats.get(key, 0) + 1


def _load(path: Path, stats: dict):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        _bump(stats, "unreadable")
        return None


def _hb_model(d: dict) -> str:
    if d.get("model"):
        return d["model"]
    models = (d.get("receipt") or {}).get("models") or []
    return models[0] if len(models) == 1 else "unknown"


def scan_results(
    bench: Path = BENCH,
    tau2_root: Path = TAU2_ROOT,
    stats: dict | None = None,
    harness: Path | None = None,
) -> Iterable[Record]:
    stats = stats if stats is not None else {}
    stats.setdefault("unreadable", 0)
    harness = harness if harness is not None else bench / "policy_eval" / "harness" / "results"
    if (
        harness.is_dir()
    ):  # one format for every benchmark; a task stopped by a wiring error never reached the agent
        for run_dir in sorted(p for p in harness.iterdir() if p.is_dir()):
            for f in sorted(run_dir.glob("*.json")):
                d = _load(f, stats)
                if not isinstance(d, dict) or "benchmark" not in d or "task" not in d:
                    continue
                if str(d.get("error") or "").startswith("wiring:"):
                    continue
                _bump(stats, d["benchmark"])
                yield Record(
                    d["benchmark"],
                    d.get("agent_model") or "unknown",
                    str(d["task"]),
                    run_prefix(run_dir.name),
                )
    for benchmark, folder, id_key in (
        ("automationbench", "automationbench", "task"),
        ("itsm", "enterpriseops_gym", "task_id"),
        ("handbook", "handbook", "task"),
    ):
        results = bench / folder / "results"
        if not results.is_dir():
            continue
        for run_dir in sorted(p for p in results.iterdir() if p.is_dir()):
            prefix = run_prefix(run_dir.name)
            for f in sorted(run_dir.glob("*.json")):
                d = _load(f, stats)
                if not isinstance(d, dict) or id_key not in d:
                    continue
                model = _hb_model(d) if benchmark == "handbook" else (d.get("model") or "unknown")
                _bump(stats, benchmark)
                yield Record(benchmark, model, str(d[id_key]), prefix)
    for run_dir in sorted(tau2_root.glob("logging_*")):
        prefix = tau2_prefix(run_dir.name)
        seen_files = sorted((run_dir / "results").glob("*.json")) + sorted(
            (run_dir / "results" / "partial").glob("*.json")
        )
        for f in seen_files:
            d = _load(f, stats)
            for item in (d.get("results") if isinstance(d, dict) and "results" in d else [d]) or []:
                if isinstance(item, dict) and "task_id" in item:
                    _bump(stats, "tau2")
                    yield Record(
                        f"tau2-{item.get('domain') or 'unknown'}",
                        item.get("agent_model") or "unknown",
                        str(item["task_id"]),
                        prefix,
                    )


def compute_seen(entries: list[dict], records: Iterable[Record]):
    """(seen_by, seen_n, counts): for each set id, {model: sorted run prefixes}, {model: tasks of the set it ran}, and how
    many results each model has. A record matches a set when benchmark and task id are both equal."""
    index: dict[tuple[str, str], list[str]] = defaultdict(list)
    for e in entries:
        for t in task_ids(e):
            index[(e["benchmark"], t)].append(e["id"])
    prefixes: dict[str, dict[str, set]] = {e["id"]: defaultdict(set) for e in entries}
    tasks: dict[str, dict[str, set]] = {e["id"]: defaultdict(set) for e in entries}
    counts: dict[str, int] = defaultdict(int)
    for r in records:
        counts[r.model] += 1
        for set_id in index.get((r.benchmark, r.task), ()):
            prefixes[set_id][r.model].add(r.prefix)
            tasks[set_id][r.model].add(r.task)
    seen_by = {i: {m: sorted(p) for m, p in sorted(d.items())} for i, d in prefixes.items()}
    seen_n = {i: {m: len(t) for m, t in sorted(d.items())} for i, d in tasks.items()}
    return seen_by, seen_n, dict(counts)


def keep_seen(entries: list[dict], seen_by: dict, seen_n: dict, existing: dict) -> list[str]:
    """Merge the scan with the registry as it was, in place: run prefixes are joined and ``seen_n`` keeps the larger count,
    since the scan cannot tell which tasks a folder that is gone held. One line for each model and set the scan alone would
    have less of."""
    kept = []
    old_sets = {e["id"]: e for e in existing.get("sets", [])}
    for e in entries:
        old = old_sets.get(e["id"], {})
        for model, prefixes in old.get("seen_by", {}).items():
            now = seen_by[e["id"]].get(model, [])
            gone = sorted(set(prefixes) - set(now))
            was_n, now_n = old.get("seen_n", {}).get(model, 0), seen_n[e["id"]].get(model, 0)
            if gone or was_n > now_n:
                kept.append(
                    f"  {e['id']}, {model}: {len(gone)} run(s) not found now ({', '.join(gone) or 'none'}); "
                    f"{now_n} of its tasks found, {max(was_n, now_n)} kept"
                )
            seen_by[e["id"]][model] = sorted(set(prefixes) | set(now))
            seen_n[e["id"]][model] = max(was_n, now_n)
        seen_by[e["id"]] = dict(sorted(seen_by[e["id"]].items()))
        seen_n[e["id"]] = dict(sorted(seen_n[e["id"]].items()))
    return kept


# ── report ───────────────────────────────────────────────────────────────────


def unseen_report(registry: dict, counts: dict[str, int]) -> str:
    heldout = [e for e in registry["sets"] if e["status"] == "heldout"]
    lines = [
        "Held-out sets per agent model (seen = the model ran at least one task of the set; matched by benchmark and task id)",
        "",
    ]
    for model in sorted(counts, key=lambda m: (m == "unknown", -counts[m], m)):
        unseen = [e["id"] for e in heldout if model not in e["seen_by"]]
        seen = [f"{e['id']} ({e['seen_n'][model]}/{e['n']})" for e in heldout if model in e["seen_by"]]
        lines += [
            f"{model}  ({counts[model]} results)",
            f"  unseen: {', '.join(unseen) or '-'}",
            f"  seen:   {', '.join(seen) or '-'}",
        ]
    if "unknown" in counts:
        lines.append(
            f"{counts['unknown']} results have no determinable model; they are listed under `unknown`."
        )
    return "\n".join(lines)


def overlaps(entries: list[dict]) -> list[str]:
    """Pairs of sets of one benchmark that share tasks (a held-out set that overlaps another set is not independent)."""
    ids = {e["id"]: set(task_ids(e)) for e in entries}
    lines = []
    for i, a in enumerate(entries):
        for b in entries[i + 1 :]:
            shared = ids[a["id"]] & ids[b["id"]] if a["benchmark"] == b["benchmark"] else set()
            if shared:
                lines.append(
                    f"  {a['id']} ({a['status']}) and {b['id']} ({b['status']}) share {len(shared)} tasks"
                )
    return lines


def build(write: bool = True, out=print) -> dict:
    entries = build_entries()
    stats: dict = {}
    seen_by, seen_n, counts = compute_seen(entries, scan_results(stats=stats))
    kept = keep_seen(entries, seen_by, seen_n, load_registry() if REGISTRY.exists() else {})
    for models in seen_by.values():
        for model in models:
            counts.setdefault(model, 0)  # a model known only from the registry is still listed
    for e in entries:
        e["seen_by"] = seen_by[e["id"]]
        e["seen_n"] = seen_n[e["id"]]
        e["label"] = set_label(e)
    registry = {
        "note": "Task sets and which agent model ran their tasks. Built by build_registry.py from the set files and the result folders; do not edit.",
        "scanned_results": dict(sorted(stats.items())),
        "sets": entries,
        "policies": policies_of(entries),
    }
    if write:
        REGISTRY.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
        out(
            f"wrote {REGISTRY.relative_to(REPO)}: {len(entries)} sets ({sum(1 for e in entries if e['status'] == 'heldout')} held-out)"
        )
    out("scanned results: " + ", ".join(f"{k} {v}" for k, v in sorted(stats.items())))
    if kept:
        out("Kept from the registry file, because the scan did not find them (a folder is missing):")
        for line in kept:
            out(line)
    out("")
    out(unseen_report(registry, counts))
    shared = overlaps(entries)
    out("")
    out("Sets that share tasks:" if shared else "No two sets of one benchmark share a task.")
    for line in shared:
        out(line)
    return registry


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--no-write", action="store_true", help="print the report without writing registry.json")
    args = ap.parse_args()
    build(write=not args.no_write)
    sys.exit(0)
