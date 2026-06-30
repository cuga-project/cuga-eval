# OpenCode AppWorld eval — architecture

How the `--agent opencode` evaluation works, and why it is directly comparable to the existing
`cuga` / `codeact` / `react` agents on the AppWorld benchmark.

**The key idea:** OpenCode runs as its own subprocess with its own agent loop, but every action it
takes is routed — via an in-process **MCP bridge** — into the **same `world` object** the harness
owns. That is the same object the harness scores with `world.evaluate()`. So OpenCode is graded by
the identical evaluator as the other agents; only the *driver* differs. OpenCode makes its own LLM
calls directly to the configured endpoint, and the harness reads token/cost/llm_call metrics from
OpenCode's `--format json` output (no proxy). When `LANGFUSE_*` are configured (same `.env` as the
other agents), the harness also records a per-task Langfuse trace with the run's I/O + those metrics
— but OpenCode's individual LLM-call generations are not traced.

---

## 1. Component diagram (Mermaid)

```mermaid
flowchart TB
    subgraph HARNESS["HARNESS PROCESS — opencode/eval.py (one task at a time)"]
        W["world (AppWorld task_id, experiment_name)\nacts AND is evaluated"]
        BR["AppWorld MCP Bridge\nFastMCP + uvicorn thread\nhttp://127.0.0.1:P/mcp/\nrepl: execute_python(code)\napis: {app}__{api}(arguments)"]
        TR["ActivityTracker /\nExperimentManager\n(+ metrics from OpenCode JSON usage)"]
        BR -- "world.execute(code)" --> W
        TR -. "world.evaluate()" .-> W
    end

    OC["OPENCODE SUBPROCESS\nopencode run \"&lt;task&gt;\" --format json\nown agent loop; tools=appworld*\nbuiltin fs/bash/web DISABLED"]
    BK["LLM endpoint\nOPENAI_BASE_URL / LITE_LLM_URL\n(or real OpenAI)"]
    AW["AppWorld servers\nenv :8000 · apis :9111 · registry :8001"]

    OC -- "MCP tool calls (HTTP)" --> BR
    OC -- "LLM calls (HTTPS)" --> BK
    OC -. "stdout: --format json\n(tokens / cost / text)" .-> TR
    W  -- "drives" --> AW

    classDef proc fill:#1d3557,stroke:#457b9d,color:#fff;
    classDef ext fill:#2a9d8f,stroke:#264653,color:#fff;
    class W,BR,TR proc;
    class OC,BK,AW ext;
```

---

## 2. Component / process map (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│  HARNESS PROCESS  —  opencode/eval.py  (one task at a time)                        │
│                                                                                            │
│   ┌─────────────────────────────┐         owns          ┌──────────────────────────────┐  │
│   │  with AppWorld(task_id,     │◄─────────────────────►│  world  (the ONE object that  │  │
│   │       experiment_name) ...   │         uses          │  acts AND gets evaluated)     │  │
│   │   • start MCP bridge (thread)│                       └──────────────┬───────────────┘  │
│   │   • spawn opencode subprocess│                                      │ world.execute()  │
│   │   • world.evaluate() + report│                                      │ world.evaluate() │
│   │   • metrics ← opencode JSON  │                                      │                  │
│   └─────────────────────────────┘                                      │                  │
│   ┌──────────────────────────────────────────────────────┐            │                  │
│   │  AppWorld MCP BRIDGE  (FastMCP + uvicorn on a thread) │            │                  │
│   │  http://127.0.0.1:<P>/mcp/                            │────────────┘                  │
│   │   repl: execute_python(code)                          │  routes every tool call        │
│   │   apis: {app}__{api}(arguments)                       │  into world.execute(...)       │
│   └───────────────────────────▲──────────────────────────┘                                │
└─────────────────────────────────────│──────────────────────────────────────────│──────────┘
              MCP tool calls (HTTP)    │                          stdout JSON      │ (tokens/cost/text)
                                       │                          ────────────────►│  (parsed by harness)
┌──────────────────────────────────────┴───────┐                                            
│  OPENCODE SUBPROCESS                          │   LLM calls (HTTPS)     ┌────────────────────────┐
│  `opencode run "<task>" --format json`        │────────────────────────►│  LLM endpoint          │
│   • its own agent loop + tools(appworld*)     │   OPENAI_BASE_URL /      │  (gateway / OpenAI)    │
│   • built-in fs/bash/web tools DISABLED       │   LITE_LLM_URL           └────────────────────────┘
└───────────────────────────────────────────────┘

        world.execute(...) ultimately drives the AppWorld backend servers:
        ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────────┐
        │ environment :8000│   │ apis :9111       │   │ registry :8001       │
        │ (REPL/code exec) │   │ (app API impls)  │   │ (auth, /functions)   │
        └──────────────────┘   └──────────────────┘   └──────────────────────┘
```

---

## 3. Runtime data flows (numbered)

```
SETUP   harness starts the MCP bridge bound to `world`; writes opencode.json
        (model=llm/<MODEL_NAME>, provider baseURL=<LLM endpoint>, mcp=bridge, builtin tools off)

(A) SOLVE THE TASK  — the agentic loop
    OpenCode loop ──MCP──► bridge.execute_python(code) ──► world.execute(code)
                                                          ──► AppWorld :8000 / :9111  (state mutates)
    ◄── output text ◄──────────────────────────────────────┘   (variables persist across calls)
    … repeats until the agent calls apis.supervisor.complete_task(answer=…)

(B) THINK  — OpenCode's own reasoning
    OpenCode ──HTTPS──► LLM endpoint (OPENAI_BASE_URL / LITE_LLM_URL / OpenAI)

(C) SCORE  — after the subprocess exits
    harness ──► world.evaluate()  (reads the SAME task DB the loop mutated) ──► success / pass%

(D) METRICS  — from OpenCode's --format json stdout
    parse usage events ──► input/output tokens, llm_calls, cost
    (cost computed from tokens × MODEL_PRICES when the model isn't priced, e.g. Azure GPT-5.x)
    ──► TaskResult.total_tokens / total_llm_calls / total_cost

(E) PERSIST
    harness replays bridge.state.tool_calls ──► ActivityTracker steps
    ExperimentManager.update_task_result(...) ──► experiments/outputs/.../final_report.json
```

---

## 4. Two action surfaces (configurable via `--opencode-tools`)

| mode | tools exposed to OpenCode | mirrors | routing |
|------|---------------------------|---------|---------|
| `repl` (default) | one tool `execute_python(code)` | **codeact** (stateful Python REPL) | `world.execute("\n"+code+"\n")` |
| `apis` | one tool per API `{app}__{api}(arguments)` (schemas from `ApiDocCollection`) | **cuga** (discrete API calls) | `world.execute("apis.{app}.{api}(**arguments)")` |

Both route through the same `world`, so scoring is identical regardless of surface.

---

## 5. How to run

```bash
./benchmarks/appworld/eval.sh --agent opencode --task 82e2fac_1                 # repl mode (default)
./benchmarks/appworld/eval.sh --agent opencode --opencode-tools apis --task 82e2fac_1
./benchmarks/appworld/eval.sh --agent opencode --eval-key test_challenge_easy   # a task set
```

Requires the `opencode` CLI on `PATH` (npm/bun/brew) and an LLM endpoint via `OPENAI_BASE_URL` /
`LITE_LLM_URL` (defaults to real OpenAI).
```
```
