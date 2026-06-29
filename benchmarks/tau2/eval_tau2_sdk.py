"""tau2-bench (τ²) evaluation entrypoint for cuga-eval.

SKELETON (Phase 1). The driver logic (task loop, ActivityTracker, results JSON,
Langfuse) lands in Phase 6 — see TAU2_CUGA_EVAL_PLAN.md §5.2 / §11.

CRITICAL ordering rule (cuga-eval): load_eval_config("tau2") MUST run before any
`cuga` (or tau2) import, because it sets CUGA_LOGGING_DIR and other env vars that
cuga reads at import time. Keep the config load as the first import-time action.
"""

# CRITICAL: Load environment variables FIRST, before ANY other imports.
import sys
from pathlib import Path

# Add project root to path so `from config_loader import ...` resolves when this
# file is run as a script (e.g. `uv run python benchmarks/tau2/eval_tau2_sdk.py`).
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from config_loader import load_eval_config

load_eval_config("tau2")

# Verify env vars are set before importing cuga modules.
import os

cuga_logging_dir = os.getenv("CUGA_LOGGING_DIR")
if not cuga_logging_dir:
    raise RuntimeError("CUGA_LOGGING_DIR not set after load_eval_config! Check config files.")

# NOTE: cuga / tau2 / bridge imports go BELOW this line (Phase 3+), never above.


def main() -> None:
    raise NotImplementedError(
        "tau2 driver not implemented yet (Phase 6). "
        "This module currently only validates the config-load-before-cuga-import contract."
    )


if __name__ == "__main__":
    main()
