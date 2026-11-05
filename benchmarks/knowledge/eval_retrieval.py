"""Retrieval-only evidence coverage for CUGA knowledge on the synthetic multi-hop suite.

For each task: ingest its records into a fresh agent collection, then measure two things. No
LLM and no network after the embedding model is cached, so the run is offline and deterministic.

1. Single-shot evidence coverage (ProactiveInquirer's metric): search once with the task question
   and score which gold records came back, overall and per hop depth. All records share
   wording, so a top-k search is capped at k/|gold| (reported as ``coverage_ceiling``); this is
   the baseline an iterative knowledge agent must beat.
2. Next-hop lookup: for every gold record, search by its token (what an agent following the
   chain would ask) and check the record comes back at rank 1 and within top-k. This isolates
   exact-identifier retrieval, which every hop of the chain depends on.

    uv run python -m benchmarks.knowledge.eval_retrieval --profile standard --out results.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import tempfile
import time
from pathlib import Path

from benchmarks.helpers.bundle import collect_cuga_info
from benchmarks.knowledge.metrics import coverage_by_depth, evidence_coverage
from benchmarks.knowledge.synth import build


def _configure_cuga(workdir: Path, profile: str, postgres_url: str) -> None:
    """Point CUGA storage at a throwaway location before cuga.config is imported."""
    os.environ["DYNACONF_KNOWLEDGE__ENABLED"] = "true"
    os.environ["DYNACONF_KNOWLEDGE__PERSIST_DIR"] = str(workdir / "knowledge")
    os.environ["DYNACONF_KNOWLEDGE__SEARCH__RAG_PROFILE"] = profile
    if postgres_url:
        os.environ["DYNACONF_STORAGE__MODE"] = "prod"
        os.environ["DYNACONF_STORAGE__POSTGRES_URL"] = postgres_url
    else:
        os.environ["DYNACONF_STORAGE__MODE"] = "local"
        os.environ["DYNACONF_STORAGE__LOCAL_DB_PATH"] = str(workdir / "cuga.db")


async def _wait(engine, task_id: str, timeout_s: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        task = await engine.get_task(task_id)
        if task and task["status"] in ("completed", "failed", "cancelled"):
            if task["status"] != "completed":
                raise RuntimeError(f"ingest task {task_id} ended {task['status']}: {task}")
            return
        await asyncio.sleep(0.05)
    raise TimeoutError(f"ingest task {task_id} did not finish in {timeout_s}s")


async def _ingest(engine, client, docs, docs_dir: Path) -> dict[str, str]:
    """Ingest each doc as its own text file; return filename -> doc_id."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    filename_to_doc = {}
    for doc in docs:
        path = docs_dir / f"{doc.doc_id.replace(':', '_')}.txt"
        path.write_text(doc.text)
        filename_to_doc[path.name] = doc.doc_id
        await _wait(engine, (await client.ingest(str(path)))["task_id"])
    return filename_to_doc


async def run(profile: str, k: int, n_tasks: int, postgres_url: str, pool: str = "task") -> dict:
    tasks = build(n_tasks=n_tasks)
    cuga_info = collect_cuga_info()  # once, before the run (see its docstring)
    with tempfile.TemporaryDirectory(prefix="cuga-kb-eval-") as tmp:
        workdir = Path(tmp)
        _configure_cuga(workdir, profile, postgres_url)
        from cuga.backend.knowledge.client import KnowledgeClient
        from cuga.backend.knowledge.config import KnowledgeConfig
        from cuga.backend.knowledge.engine import KnowledgeEngine
        from cuga.config import settings

        engine = KnowledgeEngine(KnowledgeConfig.from_settings(settings))
        await engine.warmup()
        per_task = []
        try:
            if pool == "open":  # every task's records in one collection
                client = KnowledgeClient(engine, default_agent_id="synth_open")
                all_docs = [d for t in tasks for d in t.docs]
                filename_to_doc = await _ingest(engine, client, all_docs, workdir / "docs" / "open")
            for task in tasks:
                if pool == "task":  # a fresh collection per task, as in ProactiveInquirer
                    client = KnowledgeClient(engine, default_agent_id=f"synth_{task.task_id}")
                    filename_to_doc = await _ingest(
                        engine, client, task.docs, workdir / "docs" / task.task_id
                    )
                started = time.monotonic()
                results = await client.search(task.question, limit=k)
                latency_ms = (time.monotonic() - started) * 1000
                retrieved = {
                    filename_to_doc[r["filename"]] for r in results if r["filename"] in filename_to_doc
                }
                hops = []
                for doc in task.docs:
                    if doc.doc_id not in task.gold_depth:
                        continue
                    token = doc.title.removeprefix("Record ")
                    ranked = [filename_to_doc.get(r["filename"]) for r in await client.search(token, limit=k)]
                    hops.append({"hit_at_1": ranked[:1] == [doc.doc_id], "hit_at_k": doc.doc_id in ranked})
                per_task.append(
                    {
                        "task_id": task.task_id,
                        "coverage": evidence_coverage(retrieved, set(task.gold_depth)),
                        "coverage_by_depth": coverage_by_depth(retrieved, task.gold_depth),
                        "distractors_retrieved": sum(":dist:" in d for d in retrieved),
                        "next_hop_hit_at_1": statistics.mean(h["hit_at_1"] for h in hops),
                        "next_hop_hit_at_k": statistics.mean(h["hit_at_k"] for h in hops),
                        "search_ms": round(latency_ms, 1),
                    }
                )
        finally:
            await engine.aclose()
            engine.shutdown()

    depths = sorted({d for t in per_task for d in t["coverage_by_depth"]})
    return {
        "benchmark": "knowledge_synth_retrieval",
        "cuga": cuga_info,
        "backend": "pgvector" if postgres_url else "sqlite",
        "profile": profile,
        "pool": pool,
        "k": k,
        "n_tasks": len(per_task),
        "summary": {
            "evidence_coverage": statistics.mean(t["coverage"] for t in per_task),
            "coverage_ceiling": min(1.0, k / len(tasks[0].gold_depth)),
            "next_hop_hit_at_1": statistics.mean(t["next_hop_hit_at_1"] for t in per_task),
            "next_hop_hit_at_k": statistics.mean(t["next_hop_hit_at_k"] for t in per_task),
            "coverage_by_depth": {
                d: statistics.mean(t["coverage_by_depth"][d] for t in per_task) for d in depths
            },
            "task_success": statistics.mean(t["coverage"] == 1.0 for t in per_task),
            "mean_distractors_retrieved": statistics.mean(t["distractors_retrieved"] for t in per_task),
            "p50_search_ms": statistics.median(t["search_ms"] for t in per_task),
        },
        "tasks": per_task,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="standard", help="CUGA knowledge profile")
    parser.add_argument("--k", type=int, default=10, help="results per search")
    parser.add_argument(
        "--tasks", type=int, default=24, help="number of synth tasks (max 24 matches upstream)"
    )
    parser.add_argument(
        "--postgres-url",
        default="",
        help="run on pgvector instead of SQLite: a postgresql:// connection URL",
    )
    parser.add_argument(
        "--pool",
        choices=("task", "open"),
        default="task",
        help="task: a collection per task (upstream setting); open: all 576 records in one collection",
    )
    parser.add_argument("--out", type=Path, help="write the full result JSON here")
    args = parser.parse_args()

    result = asyncio.run(run(args.profile, args.k, args.tasks, args.postgres_url, args.pool))
    s = result["summary"]
    print(
        f"{result['backend']} / {result['profile']} / pool={result['pool']} / k={result['k']} / cuga {result['cuga'].get('git_commit')}"
    )
    print(
        f"  evidence coverage   {s['evidence_coverage']:.3f} (ceiling {s['coverage_ceiling']:.3f})"
        f"   task success {s['task_success']:.3f}"
    )
    print(f"  next-hop lookup     hit@1 {s['next_hop_hit_at_1']:.3f}   hit@k {s['next_hop_hit_at_k']:.3f}")
    print("  coverage by depth   " + "  ".join(f"d{d}={v:.2f}" for d, v in s["coverage_by_depth"].items()))
    print(
        f"  distractors/top-k   {s['mean_distractors_retrieved']:.2f}   p50 search {s['p50_search_ms']:.0f} ms"
    )
    if args.out:
        args.out.write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
