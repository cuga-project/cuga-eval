#!/usr/bin/env python3
"""Compile a directory of policy markdown files into a single policies.json.

Each policy markdown must start with a YAML frontmatter block delimited by
`---` lines. The frontmatter carries the structured policy metadata
(type, id, name, triggers, etc.); the markdown body becomes the policy's
content field — `format_config` for output_formatter, `markdown_content`
for playbook, `guide_content` for tool_guide.

Usage:
    uv run python scripts/policies_md_to_json.py \
        --policies-dir benchmarks/m3/policies \
        --output benchmarks/m3/policies/policies.json

Files named `README.md` or `POLICIES.md` (case-insensitive) are skipped —
those are human-readable indices, not policies.

The output JSON matches the shape benchmarks/bpo/policies/policies.json
uses, which is what CUGA's
`cuga.backend.cuga_graph.policy.models.{OutputFormatter,Playbook,ToolGuide}`
expect via `.model_validate(...)`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

# Markdown filenames that are docs, not policies.
SKIP_FILENAMES = {"readme.md", "policies.md"}

# Map policy type -> body-content field name in the JSON.
BODY_FIELD_BY_TYPE = {
    "output_formatter": "format_config",
    "playbook": "markdown_content",
    "tool_guide": "guide_content",
}

REQUIRED_FRONTMATTER_KEYS = {"id", "type", "name"}


def parse_frontmatter(text: str, src: Path) -> tuple[dict[str, Any], str]:
    """Split a markdown file into (frontmatter_dict, body_text).

    The file must start with `---\\n`, then YAML, then a closing `---\\n`.
    """
    if not text.startswith("---"):
        raise ValueError(f"{src}: file must begin with a YAML frontmatter block delimited by '---'")
    # Find the closing '---' (must be on its own line, after the opening one)
    lines = text.splitlines(keepends=True)
    if lines[0].rstrip("\n") != "---":
        raise ValueError(f"{src}: opening '---' must be on its own line")
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\n") == "---":
            end_idx = i
            break
    if end_idx is None:
        raise ValueError(f"{src}: missing closing '---' for frontmatter block")
    fm_text = "".join(lines[1:end_idx])
    body = "".join(lines[end_idx + 1 :]).lstrip("\n")
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{src}: YAML parse error in frontmatter: {exc}") from exc
    if not isinstance(fm, dict):
        raise ValueError(f"{src}: frontmatter must be a YAML mapping, got {type(fm).__name__}")
    return fm, body


def build_policy(fm: dict[str, Any], body: str, src: Path) -> dict[str, Any]:
    """Merge frontmatter + body into a single policy dict ready for JSON."""
    missing = REQUIRED_FRONTMATTER_KEYS - set(fm)
    if missing:
        raise ValueError(f"{src}: missing required frontmatter keys: {sorted(missing)}")
    ptype = fm["type"]
    if ptype not in BODY_FIELD_BY_TYPE:
        raise ValueError(f"{src}: unknown policy type '{ptype}'; supported: {sorted(BODY_FIELD_BY_TYPE)}")
    body_field = BODY_FIELD_BY_TYPE[ptype]
    if body_field in fm:
        raise ValueError(f"{src}: '{body_field}' is provided both via frontmatter and via body — pick one")
    policy: dict[str, Any] = dict(fm)
    policy[body_field] = body
    return policy


def collect_policies(policies_dir: Path) -> list[dict[str, Any]]:
    if not policies_dir.is_dir():
        raise SystemExit(f"policies-dir does not exist or is not a directory: {policies_dir}")
    md_files = sorted(f for f in policies_dir.glob("*.md") if f.name.lower() not in SKIP_FILENAMES)
    if not md_files:
        raise SystemExit(f"no policy .md files found in {policies_dir}")
    policies: list[dict[str, Any]] = []
    seen_ids: dict[str, Path] = {}
    for md in md_files:
        fm, body = parse_frontmatter(md.read_text(), md)
        policy = build_policy(fm, body, md)
        if policy["id"] in seen_ids:
            raise SystemExit(f"duplicate policy id '{policy['id']}' in {md} and {seen_ids[policy['id']]}")
        seen_ids[policy["id"]] = md
        policies.append(policy)
    return policies


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--policies-dir",
        required=True,
        type=Path,
        help="Directory containing one .md per policy",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path (default: <policies-dir>/policies.json)",
    )
    args = parser.parse_args(argv)

    output_path = args.output or (args.policies_dir / "policies.json")
    policies = collect_policies(args.policies_dir)
    output_path.write_text(json.dumps(policies, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(policies)} policy/policies to {output_path}", file=sys.stderr)
    for p in policies:
        print(f"  - {p['type']:18s} {p['id']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
