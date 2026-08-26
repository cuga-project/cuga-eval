# M3 Vakra Evaluator (bridge)

`evaluator.py` in this directory is a **bridge to vendor/vakra's evaluator**, not a
copy of it. It loads `vendor/vakra/evaluator/evaluator.py` directly (via
`importlib`) and layers a handful of monkeypatched overrides on top for the parts
that are genuinely different in this org's setup. See `evaluator.py`'s own
docstring for the full, current list of overrides and why each is still needed —
it's the source of truth, this file just orients you.

Everything else — the scoring pipeline (exact-match → correctness → groundedness),
the input/output JSON formats, the CLI, the file layout — is vendor's own and
documented in [`vendor/vakra/evaluator/README.md`](../../../vendor/vakra/evaluator/README.md)
once `./setup_m3.sh` has cloned it. Don't duplicate that documentation here; if it's
wrong or missing, that's an upstream fix.

## What's actually local

- **`evaluator.py`** — the bridge itself. Owns adding `vendor/vakra` to `sys.path`,
  raising a clear error if it's missing, and applying the overrides.
- **`policy_judge.py`** — the real `PolicyAdherenceJudge` implementation.
  **Untracked, never committed to this repo** — it's proprietary and can't be
  published to a public repo, same reason vendor's own repo ships the
  `policy_judge_path` plumbing but not an actual judge. When this file is present
  locally, `evaluator.py` auto-detects it and policy-adherence scoring runs
  end-to-end through the normal `eval.sh`/`compare.sh` pipeline with no flags
  needed. When it's absent, policy scoring is silently skipped — same as it is
  everywhere this file doesn't exist.
- **`domain_mapping.json`** — currently unreferenced by any code path in this repo
  (kept for now; not vendor-sourced either).

## Judge LLM backend

Defaults to this org's LiteLLM proxy (`JUDGE_BACKEND=litellm`, the bridge's own
default — vendor's own default is Groq, which is discontinued as a service).
Requires `OPENAI_BASE_URL` + `OPENAI_API_KEY` (same env the agent's `gpt4.1` model
profile uses). Override the model with `JUDGE_MODEL_NAME` (default `gpt-4.1`).
Vendor's own `groq`/`rits` backends are still selectable via `JUDGE_BACKEND=groq`
or `JUDGE_BACKEND=rits` if you have credentials for those.
