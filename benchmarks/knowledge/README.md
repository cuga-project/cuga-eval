# Knowledge retrieval benchmark

Measures CUGA knowledge (the built-in document RAG) offline, through the same `KnowledgeClient`
the SDK uses. It needs no LLM and no network once the embedding model is cached.

## Synthetic multi-hop suite

Ported from ProactiveInquirer's `synth` suite (Apache-2.0); the default build is identical to the
upstream corpus (a test pins its digest). Each of the 24 tasks chains 3 facets × 6 records: a
record is found by its own token and names the next record's token; 6 unrelated notes are mixed in.
The question names only the first token of each facet.

| Metric | What it tells you |
|---|---|
| `evidence_coverage` | Share of the 18 gold records one search with the question returns (ProactiveInquirer's metric). Capped at `coverage_ceiling` = k/18, because all records share wording. The single-shot baseline an iterative agent must beat. |
| `coverage_by_depth` | The same, per hop depth (0 = token stated in the question). |
| `next_hop_hit_at_1` / `_at_k` | For each record, search by its token and check it ranks first / within top-k. Isolates exact-identifier retrieval, which every hop of a chain depends on. |
| `mean_distractors_retrieved`, `p50_search_ms` | Noise in the top-k and search latency. |

## MuSiQue and 2Wiki suites

Real multi-hop questions over Wikipedia paragraphs, ported from ProactiveInquirer's builders
(`musique_build.py`, `wiki2_build.py`, Apache-2.0) with the same sources and SHA-256 pins. Each
question comes with its own paragraph pool (MuSiQue 20, 2Wiki 10), ingested with the paragraph
title on the first line; one search with the question is scored.

| Suite | Source (dev split) | Licence | Gold hops |
|---|---|---|---|
| `musique` | HF `dgslibisey/MuSiQue`, MuSiQue-Ans v1.0 | CC BY 4.0 | the human-written decomposition; "#N" in a step makes it depend on step N |
| `2wiki` | HF `xanhho/2WikiMultihopQA` | Apache-2.0 | evidence triples chained object -> subject; comparison questions are flat |

| Metric | What it tells you |
|---|---|
| `evidence_coverage` | Share of the gold paragraphs one search with the question returns |
| `coverage_by_depth` (C@d) | The same per hop depth, with the number of tasks that have that depth |
| `dwr` | Depth-weighted recall, `sum w_d C@d / sum w_d`, with ProactiveInquirer's preregistered weights (0.5, 1, 1.5, 2, ...) |
| `task_success` | Share of questions whose every gold paragraph came back |

Depth is the longest prerequisite path from the question. The files are downloaded once to
`~/.cache/cuga-eval/knowledge` (or `$CUGA_EVAL_CACHE`) and refused if the digest differs.
`--limit` samples round-robin across hop classes (MuSiQue) or question types (2Wiki), because
the MuSiQue file is sorted by hop count.

```bash
uv run python -m benchmarks.knowledge.eval_retrieval --suite musique --limit 200 --out musique.json
uv run python -m benchmarks.knowledge.eval_retrieval --suite 2wiki --limit 200 --out 2wiki.json
```

## Run

```bash
uv run python -m benchmarks.knowledge.eval_retrieval --profile standard --out results.json
uv run python -m benchmarks.knowledge.eval_retrieval --postgres-url "$POSTGRES_URL"   # pgvector
```

Options: `--profile` (speed, standard, balanced, max_quality), `--k` (default 10), `--tasks`
(default 24), `--pool` (`task`: one collection per task, the upstream setting; `open`: all 576
records in one collection, which makes top-k hits meaningful and tests a larger corpus).

The run uses a throwaway storage directory and never touches `.cuga/`. The CUGA commit under test
(`../cuga-agent`) is recorded in the output.
