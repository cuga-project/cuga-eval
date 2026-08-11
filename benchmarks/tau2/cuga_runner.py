"""CUGA-specific glue for tau2-bench (kept separate so the bridge stays agnostic).

- build_cuga_agent: hand the decoys to a CugaAgent.
- run_cuga_loop:    the CUGA-side driver — the multi-turn hybrid. Each turn is one
                    invoke(); when CUGA finishes a turn with a final answer, send it to
                    the user simulator via the bridge and re-invoke with the reply on the
                    SAME thread_id (memory preserved).
- _run_one_task:    run one tau2 task end-to-end: tau2 on a background thread (it drives),
                    CUGA on the main thread (it responds), read the reward.
"""

from __future__ import annotations

import asyncio
import gc
import threading
import uuid
from typing import Any, Optional

# Unique per process (i.e. per eval.sh invocation). Mixed into the Langfuse trace-id seed so
# repeated runs of the same task — e.g. compare.sh --runs N, which launches one eval.sh
# process per run — get DISTINCT trace ids instead of colliding on a deterministic seed.
_RUN_TOKEN = uuid.uuid4().hex[:8]


def _patch_tau2_nl_assertion_model(model: str, llm_args_user: Optional[dict]) -> Optional[str]:
    """Point τ²'s NL-assertion scoring LLM at a reachable model.

    τ² hardcodes `DEFAULT_LLM_NL_ASSERTIONS = "gpt-4.1-2025-04-14"` in tau2/config.py with no
    CLI/env override. Its evaluator judges NL assertions with that model AT SCORING TIME — so a
    task that has NL assertions (e.g. every retail task) dies with `reward=None` when the gateway
    can't serve that exact model id. Nothing to do with the agent/bridge; it's τ²'s own scorer.

    We repoint it at the same model + creds we already use for the user simulator (guaranteed
    reachable). The evaluator did `from tau2.config import DEFAULT_LLM_NL_ASSERTIONS`, which binds
    the name into ITS module — so we must patch that module's namespace too, not just tau2.config.
    Best-effort: if τ²'s internals move, we log and continue (scoring just reverts to the default).

    Returns the judge model actually in force (our `model` on success, τ²'s hardcoded default on
    failure) so the caller can RECORD it in the results — substituting the judge changes NL-assertion
    scoring, so our numbers are only comparable to others run against the SAME judge (not the
    official leaderboard, which uses τ²'s pinned gpt-4.1-2025-04-14).
    """
    args = {"temperature": 0.0, **(llm_args_user or {})}
    try:
        import tau2.config as tau2_config

        default_judge = getattr(tau2_config, "DEFAULT_LLM_NL_ASSERTIONS", None)
        tau2_config.DEFAULT_LLM_NL_ASSERTIONS = model
        tau2_config.DEFAULT_LLM_NL_ASSERTIONS_ARGS = args

        from tau2.evaluator import evaluator_nl_assertions as nl_eval

        nl_eval.DEFAULT_LLM_NL_ASSERTIONS = model
        nl_eval.DEFAULT_LLM_NL_ASSERTIONS_ARGS = args
        return model
    except Exception as e:  # noqa: BLE001 — never fail the run over this patch
        print(f"    (could not repoint τ² NL-assertion model: {e!r})")
        return locals().get("default_judge")


def _maybe_setup_langfuse(domain: str, task: Any, thread_id: str) -> tuple[Optional[dict], Optional[str], Any]:
    """Create one Langfuse trace for this task, if tracing is enabled and keys are present.

    Returns (lf_config, trace_id, langfuse_client). All None when tracing is off or the
    Langfuse client can't be built (missing keys) — the task then runs untraced. Never
    raises: observability must not break an eval run.
    """
    try:
        from benchmarks.helpers.sdk_eval_helpers import (
            build_langfuse_invoke_config,
            should_trace_langfuse_task,
        )

        if not should_trace_langfuse_task():
            return None, None, None
        from langfuse import get_client

        langfuse = get_client()
        trace_id = langfuse.create_trace_id(seed=f"tau2_{domain}_{task.id}_{_RUN_TOKEN}")
        lf_config = build_langfuse_invoke_config(trace_id, thread_id)
        if not lf_config:  # handler couldn't be built
            return None, None, None
        print(f"    📊 Langfuse trace: tau2_{domain}_{task.id} (ID: {trace_id})")
        return lf_config, trace_id, langfuse
    except Exception as e:  # noqa: BLE001 — tracing is best-effort
        print(f"    (langfuse tracing off: {e!r})")
        return None, None, None


def _reward_info_summary(reward_info: Any) -> Optional[dict]:
    """Extract τ²'s per-check breakdown so a non-1.0 reward is explainable.

    τ² scores by running a set of checks (DB state, required actions, NL assertions,
    communication) and combining them per `reward_basis`. `reward_breakdown` +  the
    individual `*_check` fields say exactly which check failed — that's the "why" the
    plain reward number can't give. Best-effort: returns None if the model can't dump.
    """
    try:
        d = reward_info.model_dump(mode="json")
    except Exception:  # noqa: BLE001 — never fail a task over diagnostics
        return None
    keep = (
        "reward",
        "reward_basis",
        "reward_breakdown",
        "db_check",
        "env_assertions",
        "action_checks",
        "nl_assertions",
        "communicate_checks",
        "info",
    )
    return {k: d[k] for k in keep if d.get(k) is not None}


def _messages_summary(sim: Any) -> Optional[list]:
    """Compact transcript of τ²'s conversation (role + content + tool call/result).

    τ²'s SimulationRun.messages is the authoritative dialogue: the user simulator's turns,
    CUGA's replies, and the tool calls + results in between. We keep the essentials so a
    reviewer can read the whole exchange from the results file. Best-effort; None on failure.
    """
    msgs = getattr(sim, "messages", None)
    if not msgs:
        return None
    out: list = []
    for m in msgs:
        try:
            d = m.model_dump(mode="json")
        except Exception:  # noqa: BLE001, S112 — skip an un-dumpable message; transcript is best-effort
            continue
        entry = {"role": d.get("role")}
        if d.get("content") is not None:
            entry["content"] = d["content"]
        for k in ("tool_calls", "tool_call_id", "name", "requestor", "cost"):
            if d.get(k) is not None:
                entry[k] = d[k]
        out.append(entry)
    return out


def _maybe_score_and_flush(
    trace_id: Optional[str], langfuse: Any, domain: str, task: Any, reward: Optional[float]
) -> None:
    """Attach the τ² reward as a numeric score on the task's trace, then flush. Best-effort."""
    if trace_id is None or langfuse is None:
        return
    try:
        from benchmarks.helpers.sdk_eval_helpers import flush_langfuse, langfuse_score_on_trace

        if reward is not None:
            langfuse_score_on_trace(
                langfuse,
                trace_id,
                name="reward",
                value=reward,
                data_type="NUMERIC",
                comment=f"τ² {domain} env-state reward (task {task.id})",
            )
        flush_langfuse()
    except Exception as e:  # noqa: BLE001 — never fail a task on scoring/flush
        print(f"    (langfuse scoring skipped: {e!r})")


def build_cuga_agent(decoy_tools: list, special_instructions: Optional[str] = None) -> Any:
    """Hand the decoy tools to a CugaAgent.

    cuga is imported lazily, INSIDE the function, so merely importing this module does not
    pull cuga in before load_eval_config() has run (config-load-before-cuga-import). The
    decoys are the only tools CUGA gets; `special_instructions` injects the domain policy.
    """
    from cuga.sdk import CugaAgent

    return CugaAgent(tools=decoy_tools, special_instructions=special_instructions)


async def run_cuga_loop(
    bridge: Any,
    thread_id: str = "tau2-task",
    max_turns: int = 200,
    agent: Any = None,
    lf_config: Optional[dict] = None,
) -> None:
    """Drive CUGA on the main thread's event loop against the bridge.

    Builds the decoys + agent, reads the opening customer message, then loops:
    invoke() -> take CUGA's final answer -> send it to the user sim (bridge.register_message)
    and await the reply -> re-invoke on the same thread_id. The message decoy (if CUGA uses
    it mid-turn) round-trips inside invoke() on its own. Ends when tau2 closes the bridge
    (the conversation ended on tau2's side) — which cancels the awaited Future.

    `agent` lets a test inject a fake CugaAgent (no LLM); production leaves it None so we
    build the real agent from the bridge's decoys.

    `lf_config` is the per-task Langfuse invoke config (from build_langfuse_invoke_config).
    Passing the SAME config to every turn's invoke() nests all turns under one trace. None
    (no keys / tracing off) means invoke() runs untraced.
    """
    loop = asyncio.get_running_loop()
    bridge.bind_loop(loop)
    if agent is None:
        from benchmarks.tau2.tau2_bridge import make_decoy_tools

        decoys = make_decoy_tools(bridge.tau2_tools, bridge)
        agent = build_cuga_agent(decoys, special_instructions=bridge.domain_policy)

    try:
        # Opening customer message. first_observation() is a blocking queue.get, so run it
        # off the loop to stay responsive if tau2 is slow to produce it.
        prompt = await loop.run_in_executor(None, bridge.first_observation)
        if prompt is None:  # bridge closed before it began
            return

        for _ in range(max_turns):
            invoke_kwargs: dict = {"thread_id": thread_id, "track_tool_calls": True}
            if lf_config:  # attach the trace-scoped Langfuse handler for this turn
                invoke_kwargs["config"] = lf_config
            result = await agent.invoke(prompt, **invoke_kwargs)
            answer = getattr(result, "answer", None)
            if not answer:  # nothing to say (or an error) — let tau2 end the task
                break
            try:
                # CUGA finished a turn -> its answer is the message to the customer.
                # register_message routes it to the user sim and awaits the reply.
                prompt = await bridge.register_message(answer)
            except asyncio.CancelledError:
                break  # tau2 closed the bridge — the conversation is over
            if prompt is None:
                break
    finally:
        bridge.close()


_shared_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_event_loop() -> asyncio.AbstractEventLoop:
    """One persistent event loop reused across tasks.

    asyncio.run() creates AND closes a fresh loop per call. When an async HTTP client
    (litellm/cuga) created during one task outlives it and is garbage-collected during the
    next, its cleanup runs on the previous (now-closed) loop -> "Event loop is closed".
    A single long-lived loop for the whole process avoids that.
    """
    global _shared_loop
    if _shared_loop is None or _shared_loop.is_closed():
        _shared_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_shared_loop)
    return _shared_loop


def _run_one_task(
    domain: str,
    task: Any,
    user_sim_model: str,
    *,
    agent: str = "cuga",
    agent_model: Optional[str] = None,
    agent_llm_args: Optional[dict] = None,
    llm_args_user: Optional[dict] = None,
    agent_model_placeholder: str = "gpt-4.1",
    max_steps: int = 100,
    thread_id: Optional[str] = None,
    join_timeout: float = 120.0,
    out: Optional[dict] = None,
) -> Optional[float]:
    """Run one tau2 task end-to-end; return the reward in [0,1].

    `agent` selects HOW the task is solved:
      - "cuga" (default): CUGA drives via the bridge — tau2's run_single_task runs the
        conversation on a background thread while run_cuga_loop responds on the main thread;
        when tau2 finishes, the thread closes the bridge to unblock the CUGA loop.
      - anything else (e.g. "llm_agent"): τ²'s own native agent solves the task in-process,
        with NO bridge/proxy/thread — see _run_one_task_native. `agent_model` / `agent_llm_args`
        give that agent its model + gateway creds.

    `out`, if given, is populated with side outputs the caller needs in the results JSON
    (`trace_id`, `nl_judge_model`, `reward_info`, `messages`). Kept as an out-param so the
    return value stays the plain reward.
    """
    # τ² native agents need no bridge — dispatch to the in-process path and return early.
    if agent != "cuga":
        return _run_one_task_native(
            domain,
            task,
            agent=agent,
            agent_model=agent_model,
            agent_llm_args=agent_llm_args,
            user_sim_model=user_sim_model,
            llm_args_user=llm_args_user,
            max_steps=max_steps,
            thread_id=thread_id,
            out=out,
        )

    # Unique CUGA thread_id per task so its conversation memory never leaks between tasks.
    if thread_id is None:
        thread_id = f"tau2-{domain}-{task.id}"

    from tau2.data_model.simulation import TextRunConfig
    from tau2.registry import registry
    from tau2.runner.batch import run_single_task

    from benchmarks.tau2.tau2_bridge import ConversationBridge
    from benchmarks.tau2.tau2_proxy import make_cuga_factory, set_current_bridge

    # Repoint τ²'s hardcoded NL-assertion scoring model (gpt-4.1-2025-04-14) at the reachable
    # user-sim model, so tasks with NL assertions (all retail) can be scored instead of erroring.
    # Record the judge actually used — swapping it changes NL scoring, so comparability depends
    # on the judge (see _patch_tau2_nl_assertion_model / the results-schema note).
    nl_judge_model = _patch_tau2_nl_assertion_model(user_sim_model, llm_args_user)
    if out is not None:
        out["nl_judge_model"] = nl_judge_model

    # 1. Build a throwaway env just to read the tool schemas + policy for the decoys.
    #    (tau2 builds its own scored env inside run_single_task.)
    env = registry.get_env_constructor(domain)()
    tools, policy = env.get_tools(), env.get_policy()

    # 2. Bridge carries the schemas + policy the CUGA side reads.
    bridge = ConversationBridge(tau2_tools=tools, domain_policy=policy)
    set_current_bridge(bridge)

    # 3. Register the proxy factory once (process-global; reads the current bridge each task).
    if "cuga_proxy" not in registry.get_agents():
        registry.register_agent_factory(make_cuga_factory(), "cuga_proxy")

    cfg = TextRunConfig(
        domain=domain,
        agent="cuga_proxy",
        user="user_simulator",
        llm_agent=agent_model_placeholder,  # ignored by our proxy (it runs no LLM)
        llm_user=user_sim_model,
        llm_args_user=llm_args_user or {},
        max_steps=max_steps,
    )

    # 4. Optional Langfuse: one trace per task; CUGA's LLM calls nest under it, and the
    #    τ² env-state reward is pushed as a score after the run. Best-effort — if tracing
    #    is off or keys are missing, this stays None and the task runs untraced.
    lf_config, trace_id, langfuse = _maybe_setup_langfuse(domain, task, thread_id)
    if out is not None:
        out["trace_id"] = trace_id  # so the entrypoint can record it for --fetch-langfuse

    result: dict = {}

    def _tau2_thread() -> None:
        try:
            result["sim"] = run_single_task(cfg, task)
        except Exception as e:  # noqa: BLE001 — surface it, then still unblock CUGA
            result["error"] = e
        finally:
            bridge.close()  # unblock the CUGA loop when tau2 ends (or errors)

    t = threading.Thread(target=_tau2_thread, name="tau2-run", daemon=True)
    t.start()
    loop = _get_event_loop()
    cuga_error: Optional[BaseException] = None
    try:
        loop.run_until_complete(
            run_cuga_loop(bridge, thread_id=thread_id, max_turns=max_steps + 20, lf_config=lf_config)
        )
    except (Exception, asyncio.CancelledError) as e:  # noqa: BLE001 — see the raise decision below
        # CUGA's loop is commonly cancelled when τ² ends the conversation mid-tool-call
        # (max_steps reached, or the customer said STOP/TRANSFER): closing the bridge cancels
        # the awaited tool Future -> NodeCancelledError. That's benign — τ² has already scored
        # the task. Hold the error; decide whether it matters after the τ² thread joins.
        cuga_error = e
    finally:
        t.join(timeout=join_timeout)
        # A daemon thread that outlives the join keeps running in the background: don't read
        # its half-written `result` as if the task finished. Flag it so we surface an explicit
        # error below instead of silently recording reward=None.
        thread_timed_out = t.is_alive()
        if thread_timed_out:
            print(f"    WARNING: τ² run thread did not finish within {join_timeout}s — abandoning it.")
        set_current_bridge(None)
        # Proactively clean up this task's async resources (LLM HTTP clients, etc.) on the
        # still-open shared loop, so they don't accumulate across a long multi-task run. GC
        # may schedule async close callbacks; pump the loop once so they actually run.
        gc.collect()
        loop.run_until_complete(asyncio.sleep(0))

    sim = result.get("sim")
    # A join timeout with no scored result is a real failure, not a None score: record it as
    # the task's error so it's surfaced (and takes precedence over a benign CUGA cancellation).
    if thread_timed_out and sim is None and "error" not in result:
        result["error"] = TimeoutError(f"τ² run thread did not complete within {join_timeout}s")
    # If CUGA's loop raised but τ² still produced a scored result, the raise was just the
    # end-of-conversation cancellation — fall through and use τ²'s reward (fixes tasks that
    # hit max_steps mid-tool-call getting recorded as None instead of their real score). Only
    # surface CUGA's error when τ² produced neither a score nor its own error to report.
    if cuga_error is not None and sim is None and "error" not in result:
        raise cuga_error

    reward = _sim_reward(sim)
    _populate_sim_outputs(sim, out)

    # Push the τ² env-state reward onto the task's trace, then flush (short-lived process).
    _maybe_score_and_flush(trace_id, langfuse, domain, task, reward)

    if "error" in result:
        raise result["error"]
    return reward


def _sim_reward(sim: Any) -> Optional[float]:
    """The scalar reward from a τ² SimulationRun, or None if it never scored."""
    return sim.reward_info.reward if sim and sim.reward_info else None


def _populate_sim_outputs(sim: Any, out: Optional[dict]) -> None:
    """Copy τ²'s per-check breakdown + full transcript into `out` (best-effort, shared by
    both the CUGA and native-agent paths so the results JSON has the same shape either way).

    - reward_info: τ²'s per-check breakdown — the authoritative "why" behind the score.
    - messages: the full customer ↔ agent ↔ tool dialogue as τ² saw it (the transcript that
      Langfuse/trajectory don't capture on τ²'s side).
    """
    if out is None or not sim or not sim.reward_info:
        return
    out["reward_info"] = _reward_info_summary(sim.reward_info)
    out["messages"] = _messages_summary(sim)


def _run_one_task_native(
    domain: str,
    task: Any,
    *,
    agent: str,
    agent_model: Optional[str],
    agent_llm_args: Optional[dict],
    user_sim_model: str,
    llm_args_user: Optional[dict],
    max_steps: int,
    thread_id: Optional[str],
    out: Optional[dict],
) -> Optional[float]:
    """Run one task with a τ²-NATIVE agent (e.g. "llm_agent"), in-process, no bridge.

    This is the baseline path: τ²'s own agent already lives in τ²'s registry, and
    run_single_task dispatches `cfg.agent` to it and runs the whole conversation itself — so
    unlike the CUGA path there is no bridge, no decoys, no proxy thread. We only build the
    run config, hand τ² the agent's model + gateway creds, and read the reward back.

    Notes:
    - The NL-assertion judge patch still applies: it's about SCORING reachability (τ²'s
      hardcoded judge model), independent of which agent produced the transcript.
    - Langfuse: we still mint a trace id and push the reward score onto it (so the bundle's
      --fetch-langfuse has an id + score). Per-LLM spans do NOT nest here — τ²'s native agent
      calls the model through its own `generate()`, not through the langchain handler CUGA
      uses — so the trace is score-only for this path. That's expected for the baseline.
    """
    if thread_id is None:
        thread_id = f"tau2-{domain}-{task.id}"

    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.batch import run_single_task

    # Scoring reachability — same reason as the CUGA path (see _patch_tau2_nl_assertion_model).
    nl_judge_model = _patch_tau2_nl_assertion_model(user_sim_model, llm_args_user)
    if out is not None:
        out["nl_judge_model"] = nl_judge_model

    lf_config, trace_id, langfuse = _maybe_setup_langfuse(domain, task, thread_id)
    if out is not None:
        out["trace_id"] = trace_id

    cfg = TextRunConfig(
        domain=domain,
        agent=agent,  # τ²-native agent name (registered by τ²'s own registry, e.g. "llm_agent")
        user="user_simulator",
        llm_agent=agent_model,
        llm_args_agent=agent_llm_args or {},
        llm_user=user_sim_model,
        llm_args_user=llm_args_user or {},
        max_steps=max_steps,
    )

    # τ² runs its own agent + user sim + env end-to-end on this thread and scores the result.
    result: dict = {}
    try:
        sim = run_single_task(cfg, task)
    except Exception as e:  # noqa: BLE001 — record the failure the same way the caller expects
        result["error"] = e
        sim = None

    reward = _sim_reward(sim)
    _populate_sim_outputs(sim, out)
    _maybe_score_and_flush(trace_id, langfuse, domain, task, reward)

    if "error" in result:
        raise result["error"]
    return reward
