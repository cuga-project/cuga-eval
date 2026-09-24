"""Temperature variant of a cuga models TOML.

Campaign-parity runs use temperature 1.0 (OpenAI's guidance for gpt-oss and what
the other stack passes with ``--temperature 1.0``); the cuga default
``settings.openai.toml`` says 0.1 on every ``[agent.*.model]`` block. ``env.sh``
writes the variant next to the run artifacts and points ``AGENT_SETTING_CONFIG``
at its absolute path (cuga joins that with its models dir, and ``os.path.join``
keeps an absolute path as-is).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_MODEL_BLOCK = re.compile(r"^\[agent\.[A-Za-z0-9_]+\.model\]\s*$")
_TEMPERATURE = re.compile(r"^(\s*)temperature\s*=\s*[^#\n]*?\s*(#.*)?$")


def write_temperature_variant(src: Path, dst: Path, temperature: float) -> int:
    """Copy ``src`` to ``dst`` with every ``[agent.*.model]`` temperature set to ``temperature``.

    Returns the number of rewritten lines; 0 means ``src`` carries no model temperature
    at all, which callers must treat as an error (the run would silently keep 0.1).
    """
    in_model_block, rewritten, out = False, 0, []
    for line in Path(src).read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_model_block = bool(_MODEL_BLOCK.match(stripped))
        match = _TEMPERATURE.match(line) if in_model_block else None
        if match:
            comment = f"  {match.group(2)}" if match.group(2) else ""
            line = f"{match.group(1)}temperature = {temperature}{comment}"
            rewritten += 1
        out.append(line)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(out) + "\n")
    return rewritten


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", required=True, type=Path, help="cuga models TOML to derive from")
    parser.add_argument("--dst", required=True, type=Path, help="where to write the variant")
    parser.add_argument("--temperature", required=True, type=float)
    args = parser.parse_args(argv)
    n = write_temperature_variant(args.src, args.dst, args.temperature)
    if n == 0:
        print(f"no [agent.*.model] temperature found in {args.src}", file=sys.stderr)
        return 2
    print(f"{args.dst}: {n} model block(s) at temperature={args.temperature}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
