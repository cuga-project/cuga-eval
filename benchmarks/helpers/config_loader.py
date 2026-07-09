"""Configuration loader for evaluation benchmarks.

This module provides functions to load environment variables from config files
without importing heavy dependencies like cuga agent.
"""

import os
from pathlib import Path

from dotenv import dotenv_values


def load_eval_config(benchmark_name: str):
    """Load environment variables from config files.

    This function loads configuration in the following order, with later
    sources overriding earlier ones:
    1. config/global.env (shared settings)
    2. benchmarks/{benchmark_name}/config/{benchmark_name}.env (benchmark-specific settings)

    Env vars already present in os.environ when this is called (e.g. set by the
    caller's shell, or by eval.sh before invoking Python) always win over both
    files — the files only fill in values that aren't already set. This mirrors
    the bash-side convention in load_env.sh, and is required so callers can
    override values like DYNACONF_SERVER_PORTS__APIS_URL before load_eval_config
    runs instead of only after.

    Args:
        benchmark_name: Name of the benchmark (e.g., "m3", "oak_health_insurance")
    """
    # Get project root (assuming this file is in benchmarks/helpers/)
    current_file = Path(__file__)
    project_root = current_file.parent.parent.parent
    config_dir = project_root / "config"

    merged_values = {}

    global_env = config_dir / "global.env"
    if global_env.exists():
        merged_values.update(dotenv_values(global_env))

    benchmark_env = project_root / "benchmarks" / benchmark_name / "config" / f"{benchmark_name}.env"
    if benchmark_env.exists():
        merged_values.update(dotenv_values(benchmark_env))

    for key, value in merged_values.items():
        if value is not None:
            os.environ.setdefault(key, value)
