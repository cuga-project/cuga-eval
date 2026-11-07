"""Run IBM ToolGuard step 1 (policy text + tools -> per-tool policies with exact references and examples) on the
ITSM policy, with our LiteLLM gateway and a token-counting client (cost goes to the pilot ledger).

ToolGuard (github.com/IBM/tool_guard, Apache-2.0) is cloned read-only under ~/dev/untrusted; its src path is an
argument, this script lives outside it.

    ~/dev/cuga-agent-gate/.venv/bin/python -I policy_eval/toolguard_step1.py \
        --toolguard-src ~/dev/untrusted/tool_guard_src/tool_guard/src --model aws/gpt-oss-120b
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import threading
from pathlib import Path
from typing import Dict, List

HERE = Path(sys.argv[0]).resolve().parent
BENCH = HERE.parent
EVAL = BENCH.parent
sys.path.insert(0, str(BENCH))
VERSION = "e2891a7b98"
READ = re.compile(r"^(get|list|find|count|average|total|retrieve)_")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--toolguard-src", required=True)
    ap.add_argument("--model", default="aws/gpt-oss-120b")
    ap.add_argument("--out", default=str(HERE / "toolguard" / VERSION))
    ap.add_argument(
        "--short", action="store_true", help="ToolGuard's minimal step 1 (create + examples only)"
    )
    ap.add_argument("--concurrency", type=int, default=12)
    ap.add_argument("--tools", nargs="*", help="only these write tools")
    ap.add_argument(
        "--policies-only",
        action="store_true",
        help="ToolGuard's policy stages only (create, add x3, split, merge, review, references, reference "
        "check); no examples (those are for step 2 code generation and cost one call per policy)",
    )
    a = ap.parse_args()
    sys.path.insert(0, a.toolguard_src)
    import types  # register the package without running its __init__ (it imports step 2, which needs mellea)

    pkg = types.ModuleType("toolguard")
    pkg.__path__ = [str(Path(a.toolguard_src) / "toolguard")]
    sys.modules["toolguard"] = pkg
    import markdown
    import policy_pilot_costs as costs
    from dotenv import dotenv_values
    from openai import OpenAI
    from toolguard.llm.tg_litellm import LitellmModel
    from toolguard.llm.tg_llm import TG_LLM
    from toolguard.stages_tptd.text_tool_policy_generator import TextToolPolicyGenerator, ToolInfo, step1_main

    secrets = dotenv_values(EVAL / ".env")
    client = OpenAI(
        base_url=secrets["OPENAI_BASE_URL"], api_key=secrets["OPENAI_API_KEY"], timeout=300, max_retries=3
    )
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "model": a.model}
    lock = threading.Lock()
    sem = asyncio.Semaphore(a.concurrency)

    class GatewayLLM(TG_LLM):
        async def generate(self, messages: List[Dict]) -> str:
            async with sem:
                kw = {"max_tokens": 16000} if "gpt-oss" in a.model else {}
                r = await asyncio.to_thread(
                    client.chat.completions.create, model=a.model, messages=messages, **kw
                )
            with lock:
                usage["calls"] += 1
                usage["input_tokens"] += r.usage.prompt_tokens or 0
                usage["output_tokens"] += r.usage.completion_tokens or 0
            return r.choices[0].message.content or ""

        async def chat_json(self, messages: List[Dict], max_retries: int = 5) -> Dict:
            for _ in range(max_retries):
                res = LitellmModel.extract_json_from_string(None, await self.generate(messages))
                if res is not None:
                    return res
            raise RuntimeError("no JSON after retries")

    tasks = json.loads((BENCH / "enterpriseops_gym/tasks/itsm_oracle.json").read_text())
    policy_md = next(t["system_prompt"] for t in tasks if t["_policy_hash"] == VERSION)
    specs = json.loads((BENCH / "enterpriseops_gym/tasks/itsm_tools.json").read_text())
    tools = [
        ToolInfo(
            name=t["name"],
            description=t.get("description") or "",
            parameters=t.get("input_schema") or t.get("inputSchema") or {},
        )
        for t in specs
    ]
    writes = [t["name"] for t in specs if not READ.match(t["name"])]
    writes = [w for w in writes if not a.tools or w in a.tools]
    Path(a.out).mkdir(parents=True, exist_ok=True)
    print(len(writes), "write tools")

    async def policies_only(policy_text: str) -> None:
        proc = Path(a.out) / "process"
        proc.mkdir(parents=True, exist_ok=True)
        g = TextToolPolicyGenerator(GatewayLLM(), policy_text, tools, str(proc))

        async def one(name: str) -> None:
            try:
                t = await g.create_policy(name)
                for i in range(3):
                    t = await g.add_policies(name, t, i)
                for step in (g.split, g.merge, g.review_policy, g.add_references, g.reference_correctness):
                    t = await step(name, t)
            except Exception as exc:  # noqa: BLE001 - one tool failing must not stop the others
                t = {"error": str(exc)[:300]}
            (Path(a.out) / f"{name}.json").write_text(json.dumps(t, indent=2))

        await asyncio.gather(*(one(w) for w in writes))

    try:
        if a.policies_only:
            asyncio.run(policies_only(markdown.markdown(policy_md)))
        else:
            asyncio.run(step1_main(markdown.markdown(policy_md), tools, a.out, GatewayLLM(), writes, a.short))
    finally:
        c = costs.record("toolguard_step1", f"itsm:{VERSION}:{a.model}", policy=usage)
        print(json.dumps(usage), f"${c:.2f}")


if __name__ == "__main__":
    main()
