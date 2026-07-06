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
import threading
from typing import Any, Optional


def build_cuga_agent(decoy_tools: list, special_instructions: Optional[str] = None) -> Any:
    """Hand the decoy tools to a CugaAgent.

    cuga is imported lazily, INSIDE the function, so merely importing this module does not
    pull cuga in before load_eval_config() has run (config-load-before-cuga-import). The
    decoys are the only tools CUGA gets; `special_instructions` injects the domain policy.
    """
    from cuga.sdk import CugaAgent

    return CugaAgent(tools=decoy_tools, special_instructions=special_instructions)


async def run_cuga_loop(
    bridge: Any, thread_id: str = "tau2-task", max_turns: int = 200, agent: Any = None
) -> None:
    """Drive CUGA on the main thread's event loop against the bridge.

    Builds the decoys + agent, reads the opening customer message, then loops:
    invoke() -> take CUGA's final answer -> send it to the user sim (bridge.register_message)
    and await the reply -> re-invoke on the same thread_id. The message decoy (if CUGA uses
    it mid-turn) round-trips inside invoke() on its own. Ends when tau2 closes the bridge
    (the conversation ended on tau2's side) — which cancels the awaited Future.

    `agent` lets a test inject a fake CugaAgent (no LLM); production leaves it None so we
    build the real agent from the bridge's decoys.
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
            result = await agent.invoke(prompt, thread_id=thread_id, track_tool_calls=True)
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
    llm_args_user: Optional[dict] = None,
    agent_model_placeholder: str = "gpt-4.1",
    max_steps: int = 100,
    thread_id: str = "tau2-task",
    join_timeout: float = 120.0,
) -> Optional[float]:
    """Run one tau2 task end-to-end through CUGA + the bridge; return the reward in [0,1].

    tau2's run_single_task drives the conversation (background thread); run_cuga_loop
    responds (main thread). When tau2 finishes, the thread closes the bridge to unblock
    the CUGA loop.
    """
    from tau2.data_model.simulation import TextRunConfig
    from tau2.registry import registry
    from tau2.runner.batch import run_single_task

    from benchmarks.tau2.tau2_bridge import ConversationBridge
    from benchmarks.tau2.tau2_proxy import make_cuga_factory, set_current_bridge

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
    try:
        loop.run_until_complete(run_cuga_loop(bridge, thread_id=thread_id, max_turns=max_steps + 20))
    finally:
        t.join(timeout=join_timeout)
        set_current_bridge(None)

    if "error" in result:
        raise result["error"]
    sim = result.get("sim")
    return sim.reward_info.reward if (sim and sim.reward_info) else None
