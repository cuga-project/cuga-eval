"""Retrieval methods on saved acting calls (``tools/retrieval_eval.py``), with no model call.

The code is in the gate repo, so the tool runs with the gate repo's Python. With ``EVAL_NO_SKIP=1`` a missing input is a
failure, not a skip.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

POLICY_EVAL = Path(__file__).resolve().parents[1]
GATE_PYTHON = os.environ.get("POLICY_GATE_PYTHON") or str(
    Path.home() / "dev/cuga-agent-gate/.venv/bin/python"
)
TOOL = POLICY_EVAL / "tools" / "retrieval_eval.py"
LABELS = POLICY_EVAL / "sop_retrieval" / "result.json"
PACKAGES = str(POLICY_EVAL / "packages" / "handbook" / "{task}" / "claude_v1" / "package.json")


def missing_input(reason):
    if os.environ.get("EVAL_NO_SKIP"):
        pytest.fail(f"EVAL_NO_SKIP is set: {reason}")
    pytest.skip(reason)


def run(*args, runs=LABELS):
    if not Path(GATE_PYTHON).is_file():
        missing_input(f"the gate repo's Python is missing: {GATE_PYTHON}")
    if not Path(runs).is_file() or not (POLICY_EVAL / "packages" / "handbook").exists():
        missing_input("the saved labels or the HANDBOOK packages are missing")
    return subprocess.run(
        [GATE_PYTHON, "-I", str(TOOL), "--package", PACKAGES, "--runs", str(runs), *args],
        capture_output=True,
        text=True,
        timeout=600,
    )


def measures(*args, tmp_path, runs=LABELS):
    out = tmp_path / "measures.json"
    done = run(*args, "--json", str(out), runs=runs)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-3000:]
    return json.loads(out.read_text()), done.stdout


def test_bm25_on_the_saved_labels_gives_the_known_numbers_with_no_model_call(tmp_path):
    summary, out = measures("--router", "bm25", "--expand", "next_links", tmp_path=tmp_path)
    assert (summary["procedure_recall@1"], summary["procedure_recall@3"]) == (69.2, 80.0)
    assert summary["procedure_in_scope"] == 86.2  # at the default of a profile, top_k 3; 89.2 at 5 ids
    assert (summary["with_label"], summary["no_procedure"], summary["queries"]) == (65, 55, 120)
    assert summary["tokens_per_query"] == 0
    # the router gives, for every saved call, the ranking that was saved when the number was first measured
    assert summary["saved_ranking_matches"] == "65 of 65"
    assert "agreement" in out and "not truth" in out  # the labels are a judge model's picks


def test_a_metric_with_no_labels_says_so_and_is_not_filled_in(tmp_path):
    summary, out = measures("--router", "bm25", tmp_path=tmp_path)
    assert summary["must_not_recall@5"] == "no labels" and summary["exception_recall"] == "no labels"
    assert "must-not recall@5   no labels" in out and "exception recall    no labels" in out


def test_must_not_and_exception_recall_are_computed_from_labels_the_file_has(tmp_path):
    saved = json.loads(LABELS.read_text())
    row = next(r for r in saved["rows"] if r["label"] and r["task"].startswith("hr_crestwood"))
    pkg = json.loads(Path(PACKAGES.replace("{task}", row["task"])).read_text())
    first = next(p for p in pkg["procedures"] if p["id"] == row["label"][0])
    other = next(p for p in pkg["procedures"] if p["id"] != row["label"][0] and p.get("must_not"))
    labelled = {
        **row,
        "must_not": [
            first["must_not"][0] if first.get("must_not") else other["must_not"][0],
            "a rule nobody wrote",
        ],
        "exceptions": [row["label"][0], "no such procedure"],
    }
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"rows": [labelled]}))
    summary, _ = measures("--router", "bm25", "--top-k", "5", runs=path, tmp_path=tmp_path)
    assert summary["must_not_labels"] == 2 and summary["exception_labels"] == 2
    assert summary["exception_recall"] == 50.0  # the label procedure is in scope, the made-up one is not
    assert summary["must_not_recall@5"] in (
        0.0,
        50.0,
    )  # the made-up rule is never found; the real one only if its procedure ranks


def test_agent_opened_reads_the_procedures_the_saved_runs_opened(tmp_path):
    summary, out = measures("--router", "agent_opened", "--expand", "next_links", tmp_path=tmp_path)
    assert summary["with_label"] == 3 and summary["procedure_in_scope"] == 100.0
    assert "a set, not a ranking" in out


def test_k_hops_is_measured_by_the_same_command_and_takes_no_model(tmp_path):
    summary, _ = measures("--router", "bm25", "--expand", "k_hops", "--hops", "1", tmp_path=tmp_path)
    plain, _ = measures("--router", "bm25", "--expand", "next_links", tmp_path=tmp_path)
    assert summary["procedure_recall@1"] == plain["procedure_recall@1"] == 69.2
    assert summary["procedure_in_scope"] >= plain["procedure_in_scope"]  # a walk only adds procedures
    # the hand-built graphs have no link to walk: the output says so for each task, so a "no gain" is not misread
    assert len(summary["expander_changes_nothing_on"]) == 3 and plain["expander_changes_nothing_on"] == []


@pytest.mark.parametrize("router, flag", [("llm_cards", "--model"), ("bm25_kev", "--ask")])
def test_a_router_that_needs_a_model_stops_before_any_call_when_none_is_named(router, flag):
    done = run("--router", router)
    assert (
        done.returncode != 0 and flag in (done.stderr + done.stdout) and "paid" in (done.stderr + done.stdout)
    )


def test_an_unknown_method_name_is_an_error_that_names_it_and_the_names_there_are():
    done = run("--router", "pagerank")
    assert done.returncode != 0
    text = done.stderr
    assert "pagerank" in text and all(n in text for n in ("agent_opened", "bm25", "bm25_kev", "llm_cards"))
    done = run("--expand", "walk")
    assert "walk" in done.stderr and "k_hops" in done.stderr and "next_links" in done.stderr


def test_a_flag_the_chosen_methods_do_not_read_is_an_error():
    assert "--top-k is set" in run("--router", "agent_opened", "--top-k", "3").stderr
    assert "--hops is set" in run("--router", "bm25", "--expand", "next_links", "--hops", "2").stderr
    assert run("--router", "bm25", "--expand", "k_hops", "--hops", "2", "--top-k", "2").returncode == 0


def test_must_not_and_exception_labels_on_a_call_that_governs_no_procedure_are_scored_and_counted(tmp_path):
    saved = json.loads(LABELS.read_text())
    row = next(r for r in saved["rows"] if r["label"] == [] and r["task"].startswith("hr_crestwood"))
    pkg = json.loads(Path(PACKAGES.replace("{task}", row["task"])).read_text())
    rule = next(p for p in pkg["procedures"] if p.get("must_not"))["must_not"][0]
    esc = (pkg["global"].get("escalation") or {}).get("must_not") or []
    labelled = {**row, "must_not": [rule] + esc[:1], "exceptions": ["no such procedure"]}
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"rows": [labelled]}))
    summary, out = measures("--router", "bm25", runs=path, tmp_path=tmp_path)
    assert summary["with_label"] == 0 and summary["scored_calls"] == 1  # no procedure label, and still scored
    assert summary["must_not_labels"] == 1 + len(esc[:1]) and summary["exception_labels"] == 1
    assert summary["must_not_recall@5"] != "no labels" and summary["exception_recall"] == 0.0
    if esc:
        assert summary["must_not_recall@5"] >= 100 * len(esc[:1]) / (
            1 + len(esc[:1])
        )  # the escalation rule is always in scope
    assert "1 calls scored" in out


def test_llm_cards_asks_the_prompt_of_the_measured_router_byte_for_byte(tmp_path):
    """The prompt of ``llm_cards`` for a saved call is the one the 87.7% router was asked (``sop_retrieval_eval.py`` at
    ``684e0ca2^``: its template, its cards from the hand-built graph, the call's tool and args and the data it had read)."""
    if not Path(GATE_PYTHON).is_file():
        missing_input("the gate repo's Python is missing")
    saved = json.loads(LABELS.read_text())
    rows = [r for r in saved["rows"] if r["label"]][::7][:8] + [r for r in saved["rows"] if not r["context"]][
        :1
    ]
    script = """
import json, sys
from cuga.policy_layer.package import load_package
from cuga.policy_layer.router import LlmCards, Query
rows, template = json.loads(sys.argv[1]), sys.argv[2]
out = []
for r in rows:
    seen = []
    model = lambda system, user: seen.append((system, user)) or '{"procedures": []}'
    LlmCards(model).select(Query("ignored", (), f"{r['tool']}({r['args']})", r["context"]), load_package(template.replace("{task}", r["task"])))
    out.append(seen[0])
print(json.dumps(out))
"""
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", script, json.dumps(rows), PACKAGES],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    got = json.loads(done.stdout)
    system = "You map an agent's action to the SOP procedure that governs it. Output JSON only."
    user = (
        "SOP procedures (id | name | applies when):\n{cards}\n\nRecent data the agent read:\n<<<\n{context}\n>>>\n\n"
        "The agent's action:\n{tool}({args})\n\nWhich procedures govern this action (the procedure whose steps this action "
        "carries out, or whose rules it must\nfollow)? Most relevant first, at most 3. If no procedure governs it (e.g. a "
        'scratch computation), return [].\nReturn {{"procedures": ["<id>", ...]}}'
    )
    for r, (got_system, got_user) in zip(rows, got):
        graph = json.loads((POLICY_EVAL / "graphs_handbook" / "claude_v1" / f"{r['task']}.json").read_text())
        cards = "\n".join(
            f"{p['id']} | {p['name']} | {str(p.get('applies_when') or '')[:300]}" for p in graph["procedures"]
        )
        want = user.format(cards=cards, context=r["context"] or "(none)", tool=r["tool"], args=r["args"])
        assert got_system == system
        assert got_user == want
