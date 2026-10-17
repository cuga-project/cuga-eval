# VAKRA Adapter — configured CUGA for the M3 benchmark

The adapter layers the benchmark-validated VAKRA behaviors on an **unmodified
`CugaAgent`** — "configured CUGA, never bare main". No `cuga-agent` code is
changed; everything goes through public SDK surfaces:

| SDK surface | What the adapter uses it for |
|---|---|
| `configurable["special_instructions"]` | per-task instruction blocks (policy passthrough, discipline, answer contract, cap1 handle protocol, cap2 verbatim rule, retriever-scope grounding rule) |
| `CugaAgent(final_answer=...)` | deterministic answer function: harmony-token strip + judge-shape canonicalization |
| `CugaAgent(shortlister=Shortlister(...))` | the exact validated shortlisting: MiniLM embedding, top-k bounded, retriever pinning (custom strategy by dotted path) |
| `configurable["mcp_few_shot_examples"]` | k similar solved train examples as chat pairs (prose demos) |
| `configurable["cuga_lite_execution_mode"]` (+ bind_tools mode/cap) | native function-calling execution mode for caps 1-3 (cuga-agent#777; see [Execution mode](#execution-mode-function-calling)) |
| a `ToolProviderInterface` wrapper | tool-call recording (evidence for the guards), runaway cap, cap4 policy tool scoping. Sits *inside* CUGA's ToolGuard decorator (ToolGuard stays outermost: positional-arg normalization, policy storage), accepts exactly what the raw tools accept, and keeps the `tool.func` metadata (`_response_schemas`, `_param_constraints`) so the rendered tool docs match a plain run |

Default preset **`off`** builds a plain `CugaAgent` with exactly today's
kwargs — current behavior, byte-identical (asserted by
`tests/test_adapter_agent_factory.py`).

## Usage

```bash
# capability 2/3 through the standard eval (eval.sh forwards unknown flags)
bash benchmarks/m3/eval.sh --m3-data <data> --capability m3_task_2 --domain hockey \
     --adapter-preset cap2

# capability 1 (standalone runner)
uv run python benchmarks/m3/eval_m3_task_1_enterprise_style.py \
     --container capability_1_bi_apis --domain movie --adapter-preset cap1

# capability 4 (multiturn runner)
uv run python -m benchmarks.m3.eval_m3_multiturn --adapter-preset cap4
```

Or set `M3_ADAPTER_PRESET=<preset>` in the environment — `benchmarks/m3/config/m3.env`
(`eval.sh` loads it through `benchmarks/helpers/load_env.sh`) or the shell.
Precedence: CLI flag > `M3_ADAPTER_PRESET` > `off`.

Presets with few-shot demos (cap1-3) read their corpus from `--demo-data` /
`M3_ADAPTER_DEMO_DATA` (default: the bundled `data/small_train.zip`) — see
[Demos](#demos).

## Defaults

`cap1`–`cap4` are the defaults: the campaign's submitted config per capability, plus only the
changes that won paired A/Bs on two disjoint 30-task train slices each. The parity kit
(`benchmarks/m3/parity/`) ran them with the official judge at temperature 1.0, against the
campaign's own recorded answers re-scored in the same session. The campaign's configs stay
available for parity runs as `cap2_campaign`, `cap3_campaign` and `cap4_v3wx`; `cap1` is unchanged.

| preset | = campaign config + | evidence (train slices, pass rate) |
|---|---|---|
| `cap1` | — | 60.0% vs campaign answers 56.7% |
| `cap2` | `tool_pick`, `require_tool_rounds=2` + `retry_unattempted_refusal`, `empty_result_hint` + `param_value_examples=6` | est2_ref30 66.7 → 76.7 (pick + retry); est2_fresh30 48.3 → 69.0 (campaign answers 70.0 / 65.5) |
| `cap3` | `fact_check="verify_and_retry"` | est3_ref30 50.0 → 60.0; est3_fresh30 43.3 → 56.7 (campaign 53.6 / 56.7) |
| `cap4` | soft2 (`evidence_gate`, `support_check`, `self_verify` off; `require_tool_rounds=2`) + `fact_check="verify_and_retry"` | est4_ref30 66.7 vs V3WX answers 46.7 |

Tried and not adopted: `fact_check` on cap1 and cap2 (neutral); `cap2_verbatim` (no gain); for
cap4, the campaign's per-turn top-40 (`prefilter_top_k=40`: 56.7 vs 66.7 with every tool) and the
conversation-aware `tool_pick` (63.3); a tool-set pick for cap3 (offline: no better than the agent).

## Presets

Each field maps 1:1 to a flag from the validated VAKRA submission runs
(provenance: vakra-main `cuga_runs/cap_estimate.sh` / `fc_canon_test.sh` for
capabilities 1-3, the cap4 "V3WX" run config for capability 4).

| field | cap1 | cap2 | cap3 | cap4_v3wx | originating flag |
|---|---|---|---|---|---|
| `gates` (+2 retry rounds, same thread) | ✅ | ✅ | ✅ | — | `VAKRA_CUGA_GATES` |
| `answer_contract` | ✅ | ✅ | ✅ | — | `VAKRA_CUGA_CONTRACT` |
| `normalize` | ✅ | ✅ | ✅ | — | `VAKRA_CUGA_NORMALIZE` |
| `bluff_map` | ✅ | ✅ | ✅ | — | `VAKRA_CUGA_BLUFF_MAP` |
| `canonicalize` (in the final_answer fn) | ✅ | ✅ | ✅ | — | `FINAL_ANSWER_CANONICALIZE` |
| `demos` (prose, `demos_k=2`) | ✅ | ✅ | ✅ | — | `VAKRA_CUGA_DEMOS(_MODE=prose)` |
| `cap1_protocol` (handle/`data_label`) | ✅ | — | — | — | `VAKRA_CUGA_CAP1_PROTOCOL` |
| `relist_after_switch` | ✅ | — | — | — | `VAKRA_RELIST_AFTER_SWITCH` |
| `cap2_verbatim` (rule + extraction) | — | — | — | — | `VAKRA_CUGA_CAP2_VERBATIM` (not in fc_canon) |
| `discipline` | — | — | — | ✅ | `VAKRA_V2_DISCIPLINE` |
| `scope` (policy tool scoping) | — | — | — | ✅ | `VAKRA_V2_SCOPE` |
| `verbatim_on_retriever_scope` | — | — | — | ✅ | `VAKRA_V2_VERBATIM` |
| `evidence_gate` | — | — | — | ✅ | `VAKRA_V2_EVIDENCE_GATE` |
| `support_check` | — | — | — | ✅ | `VAKRA_V2_SUPPORT_CHECK` |
| `self_verify` | — | — | — | ✅ | `VAKRA_V2_SELF_VERIFY` |
| `refusal_norm` | — | — | — | ✅ | `VAKRA_CUGA_REFUSAL_NORM` |
| `tool_cap` | — | — | — | 16 | `VAKRA_CUGA_TOOL_CAP` |
| `shortlist_top_k` | 128 | 128 | 128 | 40 | `--top-k-tools` |
| `shortlist_pin_retrievers` | — | — | — | ✅ | `sdk` strategy only (the `campaign` strategy always pins `query_*`) |
| `execution_mode` | function_calling | function_calling | function_calling | codeact | `VAKRA_CUGA_FC` |
| `use_policy_system` | ❌ | ❌ | ❌ | ❌ | campaign: `DYNACONF_POLICY__ENABLED=false` (policy DB cleared) |

### Campaign runtime

The `VAKRA_*` flags were not the whole configuration: the campaign ran CUGA main
@cc8f9197 plus private function-calling code, and its runner fixed several runtime
values. These fields reproduce that runtime on CUGA main, as configuration only.
`tests/test_adapter_config.py::CAMPAIGN_PRESETS` asserts every value below.

| field | caps 1-3 | cap4_v3wx | campaign source |
|---|---|---|---|
| `fc_step_discipline` | `one_tool_per_step` | — | FC preamble "exactly ONE tool call at a time" → configurable `cuga_lite_step_discipline` |
| `fc_prompt_fragments` | `evidence_first` | — | FC preamble "MUST call at least one tool… never guess" → configurable `cuga_lite_fc_prompt_fragments` |
| `fc_answer_format` | ✅ | — | FC preamble answer-format line, which cuga-agent#777 does not ship (adapter text, FC mode only) |
| `harness_instructions` | ❌ | ❌ | the campaign never had eval_m3.py's CodeAct / "Never refuse" / "Evidence: … Answer: …" riders |
| `expose_all_tools` | ✅ | ✅ | `shortlisting_tool_threshold = shortlisted + 1` per invoke (no find_tools step) |
| `max_steps` | 70 | 70 | CUGA's default (`VAKRA_CUGA_MAX_STEPS=40` was never read by cuga_v2); m3.env sets 35 |
| `llm_http_timeout` | 150 | 600 | `LITELLM_REQUEST_TIMEOUT_SECONDS=150`; cap4 set none (LiteLLM's 600) |
| `agent_timeout` | 220 | 300 | `AGENT_TIMEOUT_SECONDS=220`; cap4 set none (benchmark_runner's 300) |
| `tool_cap` | 100 | 16 | `RUNAWAY_TOOL_CAP` default; cap4 `VAKRA_CUGA_TOOL_CAP=16` |
| `model_temperature` | 1.0 | 1.0 | `--temperature 1.0`; pinned on every CUGA model block, whatever models TOML is loaded |
| `bare_tool_names` | ✅ | ✅ | tools bound under their MCP names (the registry's `<domain>_` prefix removed) |
| `shortlist_strategy` | `campaign` | `campaign` | `agents/components/tool_shortlister.py`: `"name: description"`, plain MiniLM cosine, `query_*` pinned |
| `use_policy_system` | ❌ | ❌ | `DYNACONF_POLICY__ENABLED=false`: the eval clears the policy DB and loads nothing |
| `demo_bound_names` | ✅ | — | demo chains name tools as bound (a no-op with bare names) |
| `cuga_settings` | autonomy, reflection, NL auto-continue off | same + `sandbox_execution_timeout=30` | CUGA settings.toml defaults the campaign ran with; m3.env changes them |

`cuga_settings` is a comma-separated `section.key=value` list pinned in-process
before the agent is built (booleans and integers coerced). The parity kit's
`variants/pre_parity.env` turns every field above back off (the adapter as it ran
on 2026-10-12); `variants/stage1.env` keeps the first round (FC preamble through
`cuga_settings`) and reverts the second (bare names, campaign shortlister, tool
cap, temperature pin, policy clearing).

Known remaining differences: the campaign's LLM client retried 5 times (CUGA's
OpenAI client: 2, no setting) and sent no `max_tokens` (CUGA: 16000 from the
models TOML). It rebuilt CUGA per question with the shortlisted subset, where the
SDK shortlister reduces the tools at bind time (same ranking, different
mechanism). Tool descriptions come from the registry rather than the MCP wrapper.
`cuga_mode` (`accurate` in m3.env, `balanced` in the campaign) selects mode keys
the lite/FC path never reads.

Override any field with `M3_ADAPTER_<FIELD>` (upper-cased field name), e.g.
`M3_ADAPTER_SELF_VERIFY=off`, `M3_ADAPTER_TOOL_CAP=32`,
`M3_ADAPTER_DEMOS_K=3`. Booleans accept `1/on/true/yes` and `0/off/false/no`.
Optional integer knobs (`tool_cap`, `shortlist_top_k`, `capability`, `max_steps`,
`llm_http_timeout`, `agent_timeout`) and `model_temperature` accept
`none`/`null`/empty to reset — `M3_ADAPTER_TOOL_CAP=none` removes the cap,
whereas `0` blocks every tool call; negative integers are rejected.

## Answer pipeline (exact validated order)

```
CugaAgent.invoke
  └─ in-graph final_answer fn: strip harmony tokens → canonicalize (if enabled)
adapter post-invoke:
  1. gates retry            empty/hedged draft → correction, SAME thread, ≤2 rounds
  2. refusal_norm           give-up phrasing → "I can not answer."
  3. evidence_gate          factual answer with 0 successful tool calls → refusal
  4. support_check          (retriever scope) answer tokens ⊄ evidence → refusal
  5. self_verify            (retriever scope) quote-or-refuse LLM check
  6. cap2 value extraction  {"count": 0} → 0
  7. normalize              markdown/float/IMPOSSIBLE cleanup
  8. bluff_map              failure-looking AND unsupported → refusal
```

## Shortlisting

`Shortlister(strategy="embedding", embedding_model="sentence-transformers/all-MiniLM-L6-v2",
top_k=K, threshold=K, min_score=0.0, query_weight=1.0)` — the exact validated
model and semantics (engage only above K candidates; below K the catalog passes
through untouched). The cap4 preset uses the dotted-path strategy
`benchmarks.m3.adapter.shortlist.MiniLMPinnedStrategy`, which delegates ranking
to the SDK embedding strategy and pins `query_*` retriever tools into the top-k
(vakra fidelity).

## Execution mode (function calling)

`execution_mode` maps `VAKRA_CUGA_FC`: the validated caps 1-3 runs used CUGA's
native function-calling execution mode, cap4 (V3WX) ran CodeAct. With
`function_calling` the adapter sets, per invoke, `cuga_lite_execution_mode="function_calling"`
and `cuga_lite_bind_tools_mode="all"` (bind the whole scoped / shortlisted toolset
as tools). With `codeact` it sets nothing, so that arm of an A/B is exactly the
validated CodeAct run. Override per run with
`M3_ADAPTER_EXECUTION_MODE=codeact|function_calling`.

The provider-safe bind cap is a *settings* knob, not a configurable one:
`advanced_features.cuga_lite_bind_tools_max_count`, default 128. **Leave it at the
default.** When a domain has more tools than that (M3 domains have 106–283), cuga's
bind-time shortlister — which reads the adapter's `Shortlister` config at the
`bind_cap` seam, i.e. MiniLM cosine — reduces the bound set to the top 128. That is
what the validated runs bound (their own MiniLM shortlister kept the top 128 per
utterance). Setting the cap to 0 binds whole domains: never validated, and
OpenAI-class providers reject more than 128 tools per request; the adapter logs a
warning when the cap is disabled or raised.
FC refuses to start when an enabled *tool-approval* policy exists (M3 loads
playbooks, tool guides and an output formatter only, so this does not apply) or
when the policy system cannot be queried — a run that stops with
"Function-calling mode could not verify whether a tool-approval policy exists"
means the policy system was not initialised for that agent.

Native FC lands in cuga-agent with cuga-agent#777. The key names above were
verified on that branch and must be re-checked once it merges
(`tests/test_adapter_cuga_integration.py` does so automatically when the cuga
checkout has native FC); on a cuga main without it the keys are ignored and the
run stays CodeAct.

## Demos

`demos` (caps 1-3) injects `demos_k` solved examples per query through
`configurable["mcp_few_shot_examples"]`. The corpus is loaded from an **explicit
demo source** — `--demo-data PATH` / `M3_ADAPTER_DEMO_DATA` (a `.zip` or
`capability_<id>_*` directory in the M3 data layout), default the bundled
`data/small_train.zip` — for the run's own task and domain. It is never taken
from the samples being evaluated: those carry gold tool chains and answers, and
showing them as few-shots for sibling items of a test split is label leakage.
If the demo source resolves to the same path as `--m3-data`, the run logs a
warning (fine for train-split smoke runs; do not report test scores from it).
The bundled train zip has no capability-1 split, so cap1 runs without demos
unless `--demo-data` points at one. Any load failure degrades to "no demos".

## capability specifics

- **cap1** (`eval_m3_task_1_enterprise_style.py`): after each per-item
  `get_data` universe switch the runner hands the agent the data handle + peek
  (`set_task_context`) so the handle/`data_label` protocol block can name the
  real handle and columns; with `relist_after_switch` it also re-lists the MCP
  tools the switch swapped in and rebinds them (`refresh_tools`).
- **cap4** (`eval_m3_multiturn.py` / `eval_m3.py` multiturn path): the runner
  passes each sample's `additional_instructions` (the policy string) to the
  agent before the turns run — verbatim passthrough into
  `special_instructions`, plus deterministic tool scoping (`scope`): absolute
  retriever-only/no-retriever rules prune the toolset directly; conditional
  rules topic-classify the query first (one cheap LLM call). Like every
  preset, `cap4_v3wx` runs with CUGA's policy DB cleared (`use_policy_system=False`);
  policy handling comes from the instructions/scoping instead.

## Not ported (and why)

- **Function calling** (`VAKRA_CUGA_FC`) is mapped (see
  [Execution mode](#execution-mode-function-calling)) but only takes effect once
  cuga-agent#777 is merged.
- **`stepwise_struct`**: relied on a module that only existed in a vendored
  CUGA tree.
- Experimental flags never in a submitted config: `TOOLFINDER`,
  `REQUIRE_TOOL`/`SUPPRESS_GIVEUP`, `STEPWISE*`, `CAP1_TEMPLATE/ANSWER`,
  `DROP_GETDATA`, `FULL_PEEK`, `DEDUP`, `TOOL_GROUNDED`, `DEMOS_MSGS/CODE`,
  `TOOL_BUDGET/THRESHOLD`, `CUGA_POLICY`, `ITEM_SLEEP`, `TOOL_RETURNS`.
- Dead flags (present in run scripts but no-ops on the submitted code path):
  `VAKRA_CUGA_MAX_STEPS` (use
  `DYNACONF_ADVANCED_FEATURES__CUGA_LITE_MAX_STEPS`, already in `m3.env`) and
  `VAKRA_CUGA_SUPPRESS_GIVEUP`.

## Data & licensing

The adapter adds **no data files**. Demos are read at runtime from the demo
source above (default: the bundled `data/small_train.zip`), which stays under
VAKRA's CC BY-NC-SA terms (see `benchmarks/m3/data/NOTICE`).
