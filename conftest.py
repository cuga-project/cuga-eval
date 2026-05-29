"""Pytest root conftest: reload benchmark env before tests import cuga.

Eval shells source *.env via bash, which used to leave inline comments in
values (e.g. ``accurate # Overall CUGA...``). Reload committed config with
dotenv so ``just ci`` stays green even after a local eval run.
"""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent


def _reload_benchmark_env() -> None:
    from dotenv import load_dotenv

    global_env = _PROJECT_ROOT / "config" / "global.env"
    if global_env.exists():
        load_dotenv(global_env, override=True)
    for env_file in sorted((_PROJECT_ROOT / "benchmarks").glob("*/config/*.env")):
        load_dotenv(env_file, override=True)


_reload_benchmark_env()
