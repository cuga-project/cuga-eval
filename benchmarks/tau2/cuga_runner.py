"""CUGA-specific glue for tau2-bench (kept separate so the bridge stays agnostic).

Phase 3 adds build_cuga_agent. run_cuga_loop (the multi-turn hybrid) lands in
Phase 5 — see TAU2_CUGA_EVAL_PLAN.md §5.4, §11.1.
"""

from typing import Any, Optional


def build_cuga_agent(decoy_tools: list, special_instructions: Optional[str] = None) -> Any:
    """Hand the decoy tools to a CugaAgent.

    cuga is imported lazily, INSIDE the function, so merely importing this module
    does not pull cuga in before load_eval_config() has set CUGA_LOGGING_DIR etc.
    (the config-load-before-cuga-import rule). The decoys are the only tools CUGA
    gets; `special_instructions` is where the domain policy is injected (§5.4).
    """
    from cuga.sdk import CugaAgent

    return CugaAgent(tools=decoy_tools, special_instructions=special_instructions)


# TODO(Phase 5): async def run_cuga_loop(bridge) -> None   (hybrid loop, §11.1)
