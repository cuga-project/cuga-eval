# benchmarks/appworld/tests/test_leaderboard_integration.py
"""Merge → evaluate → pack → unpack with the real appworld package (no LLM).

A stub 'agent' completes each task through world.execute(); the point is the
plumbing: one experiment dir, task dirs recreated in place on retry, official
metrics computed, bundle verified byte-for-byte.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

appworld = pytest.importorskip("appworld", reason="AppWorld not installed; run ./setup_appworld.sh")
from appworld import AppWorld  # noqa: E402
from appworld.common.path_store import path_store  # noqa: E402
from appworld.task import load_task_ids  # noqa: E402

from benchmarks.appworld import leaderboard as lb  # noqa: E402

pytestmark = pytest.mark.regression

ROOT = lb.appworld_root()
if not (ROOT / "data" / "tasks").is_dir():
    pytest.skip("AppWorld data not downloaded", allow_module_level=True)

EXPERIMENT = "citest_train"


@pytest.fixture(scope="module")
def train_ids() -> list[str]:
    path_store.update_root(str(ROOT))
    ids = load_task_ids("train")
    bases: dict[str, list[str]] = {}
    for t in ids:
        bases.setdefault(lb.base_id(t), []).append(t)
    picked = [t for b in list(bases)[:2] for t in sorted(bases[b])]  # 2 bases x 3 scenarios
    assert len(picked) == 6
    return picked


@pytest.fixture(autouse=True, scope="module")
def clean_experiment():
    exp = lb.outputs_dir(ROOT) / EXPERIMENT
    shutil.rmtree(exp, ignore_errors=True)
    yield
    shutil.rmtree(exp, ignore_errors=True)


def run_stub(task_id: str, marker: str, succeed: bool = True) -> None:
    """Complete one task in-process the way the SDK evaluator finishes a task.

    AppWorld grades the resulting world state, not the status string an agent
    passes to ``complete_task``, so a bare
    ``apis.supervisor.complete_task(status="success")`` leaves every task at
    ``task_goal_completion == 0`` -- there is no free pass. To exercise real,
    non-zero TGC/SGC without an LLM, ``succeed=True`` replays the task's own
    ground-truth solution code, exactly as appworld's own regression check
    (``appworld.verify._verify_task``) does: load it with
    ``ground_truth_mode="full"`` and execute ``solution(apis, requester)``.
    """
    with AppWorld(task_id=task_id, experiment_name=EXPERIMENT, ground_truth_mode="full") as world:
        world.execute(f"print({marker!r})")
        if succeed:
            ground_truth = world.task.ground_truth
            assert ground_truth is not None
            code = ground_truth.compiled_solution_code + "\nsolution(apis, requester)"
            out = world.execute(code)
            assert "Execution failed" not in out, out
        else:
            world.execute("apis.supervisor.complete_task(status='fail')")
        world.evaluate()


def test_batches_and_retry_merge_into_one_experiment(train_ids):
    b1, b2 = train_ids[:3], train_ids[3:]
    for t in b1:
        run_stub(t, "first")
    for t in b2:
        run_stub(t, "first")
    run_stub(b1[0], "second")  # retry overwrites in place
    exp = lb.outputs_dir(ROOT) / EXPERIMENT
    rep = lb.validate_experiment(exp, train_ids, "test_normal")
    assert rep.missing_tasks == [] and rep.missing_files == {} and rep.incomplete_bases == []
    io_md = (exp / "tasks" / b1[0] / "logs" / "environment_io.md").read_text()
    assert "second" in io_md and "first" not in io_md
    assert lb.count_interactions(exp / "tasks" / b1[0] / "logs" / "environment_io.md") == 2


def test_official_evaluate_reports_tgc_and_sgc(train_ids):
    for t in train_ids:
        run_stub(t, "m")
    result = lb.evaluate_official(EXPERIMENT, root=ROOT, task_ids=train_ids)
    table = lb.official_table(result)
    agg = table["aggregate"]
    assert set(agg) == {"task_goal_completion", "scenario_goal_completion"}
    assert agg["scenario_goal_completion"] <= agg["task_goal_completion"]
    # break one scenario of base 1 → SGC for that base drops to 0, TGC by one task
    run_stub(train_ids[1], "m", succeed=False)
    table2 = lb.official_table(lb.evaluate_official(EXPERIMENT, root=ROOT, task_ids=train_ids))
    assert table2["aggregate"]["task_goal_completion"] < agg["task_goal_completion"]
    assert table2["aggregate"]["scenario_goal_completion"] < agg["scenario_goal_completion"]


def test_pack_roundtrip_with_real_appworld(train_ids):
    for t in train_ids:
        run_stub(t, "m")
    # pack_and_verify validates against a split; for the train subset we call the pieces directly
    import contextlib
    import io

    from appworld.leaderboard import pack_experiment

    path_store.update_root(str(ROOT))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pack_experiment(
            experiment_name=EXPERIMENT,
            dataset_name="train",
            method_name="ci",
            method_tooltip="",
            llm_name="stub",
            llm_tooltip="",
            url="https://example.invalid",
        )
    assert "WARNING: Missing file path" not in buf.getvalue()
    bundle = lb.outputs_dir(ROOT) / EXPERIMENT / "leaderboard.bundle"
    assert bundle.is_file()

    import filecmp
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        names = lb._appworld_unpacker(bundle, Path(tmp))
        # Real packer also includes optional per-task logs when present; require
        # every required file and allow extras rather than asserting a fixed count.
        task_files = [n for n in names if "/tasks/" in n.replace("\\", "/")]
        assert len(task_files) >= len(train_ids) * len(lb.REQUIRED_TASK_FILES)
        for t in train_ids:
            for rel in lb.REQUIRED_TASK_FILES:
                a = lb.outputs_dir(ROOT) / EXPERIMENT / "tasks" / t / rel
                b = Path(tmp) / EXPERIMENT / "tasks" / t / rel
                assert filecmp.cmp(a, b, shallow=False), rel


def test_rename_after_pack_is_detected(train_ids):
    for t in train_ids[:3]:
        run_stub(t, "m")
    import contextlib
    import io

    from appworld.leaderboard import pack_experiment, unpack_experiment

    path_store.update_root(str(ROOT))
    with contextlib.redirect_stdout(io.StringIO()):
        pack_experiment(
            experiment_name=EXPERIMENT,
            dataset_name="train",
            method_name="ci",
            method_tooltip="",
            llm_name="stub",
            llm_tooltip="",
            url="https://example.invalid",
        )
    exp = lb.outputs_dir(ROOT) / EXPERIMENT
    renamed = exp.with_name("renamed_train")
    shutil.move(exp, renamed)
    try:
        with pytest.raises(Exception, match="renamed the bundled experiment"):
            unpack_experiment("renamed_train")
    finally:
        shutil.rmtree(renamed, ignore_errors=True)
