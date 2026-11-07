#!/usr/bin/env python3
"""Save one HANDBOOK task's MCP tool schemas (for offline intake): start its container, list tools, stop it.

~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/handbook/dump_tools.py <task>
"""

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hb_env as rh  # noqa: E402


async def main(task: str) -> None:
    name = f"hb_tools_{task[-8:]}"
    try:
        port = rh.start_container(task, name)
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(
            {"handbook": {"url": f"http://127.0.0.1:{port}/mcp", "transport": "streamable_http"}}
        )
        specs = rh.specs_of(await client.get_tools())
        (HERE / "tools" / f"{task}.json").write_text(json.dumps(specs, indent=1))
        print(len(specs), "tools saved")
    finally:
        rh.sh(["docker", "rm", "-f", name], check=False)


asyncio.run(main(sys.argv[1]))
