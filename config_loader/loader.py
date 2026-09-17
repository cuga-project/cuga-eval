"""Configuration loader for evaluation benchmarks.

This module provides functions to load environment variables from config files
without importing heavy dependencies like cuga agent.
"""

import os
import sys
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
    the bash-side convention in benchmarks/helpers/load_env.sh, and is required
    so callers can override values like DYNACONF_SERVER_PORTS__APIS_URL before
    load_eval_config runs instead of only after (issue #17).

    Args:
        benchmark_name: Name of the benchmark (e.g., "m3", "oak_health_insurance")
    """
    # Get project root (assuming this file is in config_loader/)
    current_file = Path(__file__)
    project_root = current_file.parent.parent
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

    # Default LOGURU_LEVEL to WARNING to reduce cuga library noise.
    # The --verbose flag in eval scripts sets this to DEBUG before we get here.
    if not os.environ.get("LOGURU_LEVEL"):
        os.environ["LOGURU_LEVEL"] = "WARNING"

    # Convert CUGA_LOGGING_DIR to absolute path if it's relative
    # This must be done BEFORE any cuga modules are imported
    # CRITICAL: cuga.config reads this at module import time (line 21), so it must be set now
    # cuga.config does: LOGGING_DIR = os.environ.get("CUGA_LOGGING_DIR", ...)
    # So we MUST set os.environ["CUGA_LOGGING_DIR"] before cuga.config is imported
    cuga_logging_dir = os.getenv("CUGA_LOGGING_DIR")
    if cuga_logging_dir:
        # Remove quotes if present (from env file)
        cuga_logging_dir = str(cuga_logging_dir).strip('"').strip("'")
        logging_path = Path(cuga_logging_dir)

        if not logging_path.is_absolute():
            # Join with project root to make it absolute
            absolute_logging_dir = (project_root / logging_path).resolve()
        else:
            # Already absolute, but resolve it to ensure it's normalized
            absolute_logging_dir = logging_path.resolve()

        # CRITICAL: Set it in os.environ so cuga.config can read it
        os.environ["CUGA_LOGGING_DIR"] = str(absolute_logging_dir)
    else:
        # Force set it even if not in env file (use default location)
        default_logging_dir = (project_root / "benchmarks" / benchmark_name / "logging").resolve()
        os.environ["CUGA_LOGGING_DIR"] = str(default_logging_dir)

    # Verify the env var is set (for debugging)
    final_logging_dir = os.getenv("CUGA_LOGGING_DIR")
    if final_logging_dir:
        # Use print instead of logger to avoid importing loguru
        print(f"[config_loader] CUGA_LOGGING_DIR set to: {final_logging_dir}", file=sys.stderr)
    else:
        print("[config_loader] WARNING: CUGA_LOGGING_DIR not set!", file=sys.stderr)

    # Convert MCP_SERVERS_FILE to absolute path if it's relative
    mcp_servers_file = os.getenv("MCP_SERVERS_FILE")
    if mcp_servers_file:
        mcp_servers_file = str(mcp_servers_file).strip('"').strip("'")
        mcp_path = Path(mcp_servers_file)
        if not mcp_path.is_absolute():
            os.environ["MCP_SERVERS_FILE"] = str((project_root / mcp_path).resolve())

    # Convert APPWORLD_ROOT to absolute path if it's relative
    appworld_root = os.getenv("APPWORLD_ROOT")
    if appworld_root:
        appworld_root = str(appworld_root).strip('"').strip("'")
        appworld_path = Path(appworld_root)

        if not appworld_path.is_absolute():
            absolute_appworld_root = (project_root / appworld_path).resolve()
        else:
            absolute_appworld_root = appworld_path.resolve()

        os.environ["APPWORLD_ROOT"] = str(absolute_appworld_root)
        print(f"[config_loader] APPWORLD_ROOT set to: {absolute_appworld_root}", file=sys.stderr)
