# The subprocesses invoke fixed local test fixtures, never user-provided commands.
# ruff: noqa: S603, S607

import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_setup_tau3_without_optional_env_file(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    integration = workspace / "benchmarks" / "tau3" / "integration"
    integration.mkdir(parents=True)
    shutil.copy2(project_root / "setup_tau3.sh", workspace / "setup_tau3.sh")
    for name in ("cuga_bridge_server.py", "cuga_remote_agent.py"):
        (integration / name).write_text(f"# {name}\n")

    upstream = tmp_path / "upstream"
    agent_dir = upstream / "src" / "tau2" / "agent"
    agent_dir.mkdir(parents=True)
    (upstream / "pyproject.toml").write_text("[project]\nname = 'tau-fixture'\nversion = '0.1.0'\n")
    (upstream / "src" / "tau2" / "registry.py").write_text(
        "from tau2.agent.llm_agent import create_llm_agent\n"
        "\n"
        "def register(registry):\n"
        '    registry.register_agent_factory(create_llm_agent, "llm_agent")\n'
    )
    subprocess.run(["git", "init", "-q", str(upstream)], check=True)
    subprocess.run(["git", "-C", str(upstream), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(upstream),
            "-c",
            "user.name=Tau Test",
            "-c",
            "user.email=tau-test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    revision = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_stub = bin_dir / "uv"
    uv_stub.write_text("#!/bin/sh\nexit 0\n")
    uv_stub.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "TAU_GIT_URL": str(upstream),
        "TAU_REF": revision,
        "PYTHON_BIN": sys.executable,
    }

    for _ in range(2):
        subprocess.run(["bash", str(workspace / "setup_tau3.sh")], env=env, check=True, capture_output=True)

    checkout = workspace / "benchmarks" / "tau3" / "tau2-bench"
    assert not (checkout / ".env").exists()
    assert (checkout / "src" / "tau2" / "agent" / "cuga_bridge_server.py").exists()
    assert (checkout / "src" / "tau2" / "agent" / "cuga_remote_agent.py").exists()
    registry = (checkout / "src" / "tau2" / "registry.py").read_text()
    assert registry.count('registry.register_agent_factory(create_cuga_remote_agent, "cuga_remote")') == 1
