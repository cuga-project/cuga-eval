"""CUGA-specific glue for tau2-bench (kept separate so the bridge stays agnostic).

SKELETON (Phase 1). Real implementation lands in Phase 5 — see
TAU2_CUGA_EVAL_PLAN.md §5.4, §11.1.

  - build_cuga_agent(decoy_tools) -> CugaAgent(tools=decoy_tools)
  - run_cuga_loop(bridge): the multi-turn HYBRID — message decoy keeps CUGA in-loop
    when used; otherwise re-invoke on the SAME thread_id (memory preserved). Wrap in
    try/finally -> bridge.close(). Feed the domain policy via special_instructions=.
"""

# TODO(Phase 5): build_cuga_agent(decoy_tools) -> CugaAgent
# TODO(Phase 5): async def run_cuga_loop(bridge) -> None   (hybrid loop, §11.1)
