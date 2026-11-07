import json
import math

import pytest

from benchmarks.knowledge import multihop
from benchmarks.knowledge.metrics import depth_weighted_recall

pytestmark = pytest.mark.sanity


def _musique_record(tid="3hop1__1_2_3"):
    return {
        "id": tid,
        "question": "Where was the founder of the company that makes the Widget born?",
        "answer": "Haifa",
        "answerable": True,
        "paragraphs": [
            {"idx": i, "title": f"T{i}", "paragraph_text": f"text {i}", "is_supporting": i in (1, 4, 7)}
            for i in range(8)
        ],
        "question_decomposition": [
            {"question": "Widget >> manufacturer", "answer": "Acme", "paragraph_support_idx": 4},
            {"question": "#1 >> founded by", "answer": "Dana", "paragraph_support_idx": 1},
            {"question": "Where was #2 born?", "answer": "Haifa", "paragraph_support_idx": 7},
        ],
    }


def test_musique_depths_follow_the_decomposition():
    task = multihop.musique_task(_musique_record())
    assert task.gold_depth == {"3hop1__1_2_3:4": 0, "3hop1__1_2_3:1": 1, "3hop1__1_2_3:7": 2}
    assert len(task.docs) == 8
    assert not any("is_supporting" in d.text for d in task.docs)


def test_longest_path_not_shortest():
    # node 3 needs 1 (depth 0) and 2 (depth 1): it cannot be answered before 2, so depth 2
    assert multihop.longest_path_depths(4, {2: {1}, 3: {1, 2}}) == {0: 0, 1: 0, 2: 1, 3: 2}


def _wiki2_record(qtype="compositional"):
    return {
        "_id": "w1",
        "question": "Who is the mother of the director of Polish-Russian War?",
        "answer": "Malgorzata Braunek",
        "type": qtype,
        "context": [
            ["Polish-Russian War (film)", ["A 2009 film.", "Directed by Xawery Zulawski."]],
            ["Xawery Zulawski", ["A Polish director.", "Son of Malgorzata Braunek."]],
            ["Unrelated", ["Noise."]],
        ],
        "supporting_facts": [["Polish-Russian War (film)", 1], ["Xawery Zulawski", 1]],
        "evidences": [
            ["Polish-Russian War", "director", "Xawery Zulawski"],
            ["Xawery Zulawski", "mother", "Malgorzata Braunek"],
        ],
    }


def test_wiki2_chains_compositional_questions_and_matches_disambiguated_titles():
    task = multihop.wiki2_task(_wiki2_record())
    assert task.gold_depth == {"w1:0": 0, "w1:1": 1}
    assert task.docs[0].text == "A 2009 film. Directed by Xawery Zulawski."


def test_wiki2_comparison_is_flat():
    task = multihop.wiki2_task(_wiki2_record("comparison"))
    assert set(task.gold_depth.values()) == {0}


def test_wiki2_reads_parquet(tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    rec = _wiki2_record()
    row = {
        k: json.dumps(v) if k in ("context", "supporting_facts", "evidences") else v for k, v in rec.items()
    }
    pq.write_table(pa.Table.from_pylist([row]), tmp_path / "dev.parquet")
    (task,) = multihop.wiki2(path=tmp_path / "dev.parquet")
    assert task.gold_depth == {"w1:0": 0, "w1:1": 1}


def test_stratified_sample_is_balanced_at_every_prefix(tmp_path):
    lines = [_musique_record(f"2hop__{i}") for i in range(5)] + [
        _musique_record(f"4hop1__{i}") for i in range(2)
    ]
    path = tmp_path / "dev.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in lines))
    ids = [t.task_id for t in multihop.musique(limit=4, path=path)]
    assert ids == ["2hop__0", "4hop1__0", "2hop__1", "4hop1__1"]


def test_depth_weighted_recall():
    assert depth_weighted_recall({0: 1.0, 1: 0.0}) == pytest.approx(0.5 / 1.5)
    assert depth_weighted_recall({0: 1.0, 2: 1.0}) == 1.0
    assert math.isnan(depth_weighted_recall({}))


def test_fetch_refuses_a_wrong_digest(tmp_path):
    (tmp_path / "x.jsonl").write_text("tampered")
    with pytest.raises(ValueError, match="sha256"):
        multihop.fetch("https://example.invalid/x.jsonl", "0" * 64, cache=tmp_path)
