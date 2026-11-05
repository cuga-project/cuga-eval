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
