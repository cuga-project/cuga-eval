"""Load merged input/output M3 samples from a zip file or directory.

Expected layout (the same for both a zip archive and a plain directory):

    <root>/
        <capability_prefix>_<task_id>_<label>/
            input/<domain>.json
            output/<domain>.json

The top-level capability directories may be named with any prefix, as long as
they contain `_<task_id>_` followed by a label (e.g. `small_capability_2_dashboard_apis`,
`capability_3_multihop_reasoning`). This loader discovers them by matching the
task_id segment.

Input files hold dialogue turns. Output files hold ground-truth `gold_sequence`
of tool calls. This loader merges the two by uuid and emits samples shaped like
multi-turn evaluation data with an added `expected_output.gold_sequence` list
(one entry per turn) for tool-call scoring.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Matches directory names like `small_capability_2_dashboard_apis`,
# `capability_3_multihop_reasoning`, etc. We extract the numeric task_id.
_CAPABILITY_DIR_RE = re.compile(r"^(?:[A-Za-z0-9]+_)*capability_(\d+)_[A-Za-z0-9_]+$")


def _resolve_data_root(path: Path) -> Path:
    """If `path` is itself a capability dir (has input/), walk up one level so
    discovery sees a `<root>/<capability>/input` layout. Walking up is cheaper
    than teaching the discovery code to handle two layouts.
    """
    if (path / "input").is_dir() and _CAPABILITY_DIR_RE.match(path.name):
        return path.parent
    return path


class _ZipSource:
    """Filesystem-like access to entries inside a zip."""

    def __init__(self, zip_path: Path):
        self.path = zip_path
        with zipfile.ZipFile(self.path, "r") as zf:
            self._names = [n for n in zf.namelist() if not n.startswith("__MACOSX")]

    def list_top_dirs(self) -> List[str]:
        tops: List[str] = []
        seen = set()
        for name in self._names:
            top = name.split("/", 1)[0]
            if top and top not in seen:
                seen.add(top)
                tops.append(top)
        return tops

    def list_files(self, subdir: str) -> List[str]:
        """Return basenames (without extension) of .json files in `<top>/<subdir>/`."""
        results: List[str] = []
        for n in self._names:
            parts = n.split("/")
            if len(parts) == 3 and f"{parts[0]}/{parts[1]}" == subdir and parts[2].endswith(".json"):
                results.append(parts[2][: -len(".json")])
        return results

    def read_json(self, member: str) -> Any:
        with zipfile.ZipFile(self.path, "r") as zf:
            with zf.open(member) as fh:
                return json.loads(fh.read().decode("utf-8"))

    def has(self, member: str) -> bool:
        return member in self._names


class _DirSource:
    """Filesystem access rooted at a directory."""

    def __init__(self, dir_path: Path):
        self.path = dir_path

    def list_top_dirs(self) -> List[str]:
        return sorted(p.name for p in self.path.iterdir() if p.is_dir() and not p.name.startswith("__MACOSX"))

    def list_files(self, subdir: str) -> List[str]:
        d = self.path / subdir
        if not d.is_dir():
            return []
        return sorted(p.stem for p in d.glob("*.json"))

    def read_json(self, member: str) -> Any:
        p = self.path / member
        return json.loads(p.read_text(encoding="utf-8"))

    def has(self, member: str) -> bool:
        return (self.path / member).exists()


class M3DataLoader:
    """Reads merged input/output samples from an M3 data path (zip or directory).

    When ``allow_missing_output`` is True, domains that have an ``input/<domain>.json``
    but no matching ``output/<domain>.json`` are still loadable. Their samples come
    out with empty ``gold_sequence`` / ``answer_per_turn`` arrays — useful for
    "prediction-only" runs against unlabeled data.
    """

    def __init__(self, data_path: str | Path, allow_missing_output: bool = False):
        self.data_path = Path(data_path)
        self.allow_missing_output = allow_missing_output
        if not self.data_path.exists():
            raise FileNotFoundError(f"M3 data path not found: {self.data_path}")

        # If the user points at a parent that contains a single capability subdir
        # with input/, walk down to it. This makes commands like
        # `--m3-data /path/to/test/capability_2_dashboard_apis` and
        # `--m3-data /path/to/test` both work.
        if self.data_path.is_dir():
            self.data_path = _resolve_data_root(self.data_path)

        if self.data_path.is_file() and self.data_path.suffix.lower() == ".zip":
            self._src: _ZipSource | _DirSource = _ZipSource(self.data_path)
        elif self.data_path.is_dir():
            self._src = _DirSource(self.data_path)
        else:
            raise ValueError(f"M3 data path must be a .zip file or a directory: {self.data_path}")

        self._cap_dirs: Dict[int, str] = self._discover_capability_dirs()

    def _discover_capability_dirs(self) -> Dict[int, str]:
        """Map task_id → capability directory name."""
        found: Dict[int, str] = {}
        for top in self._src.list_top_dirs():
            m = _CAPABILITY_DIR_RE.match(top)
            if m:
                task_id = int(m.group(1))
                found.setdefault(task_id, top)
        return found

    def available_capabilities(self) -> List[int]:
        return sorted(self._cap_dirs.keys())

    def available_domains(self, task_id: int) -> List[str]:
        """Domains available for the given task.

        Default: domains that have both an input and output file. With
        ``allow_missing_output=True``, returns all input-side domains.
        """
        cap_dir = self._cap_dirs.get(task_id)
        if not cap_dir:
            return []
        inputs = set(self._src.list_files(f"{cap_dir}/input"))
        if self.allow_missing_output:
            return sorted(inputs)
        outputs = set(self._src.list_files(f"{cap_dir}/output"))
        return sorted(inputs & outputs)

    def available_pairs(self) -> List[Tuple[int, str]]:
        """All (task_id, domain) pairs present in the data."""
        pairs: List[Tuple[int, str]] = []
        for task_id in self.available_capabilities():
            for domain in self.available_domains(task_id):
                pairs.append((task_id, domain))
        return pairs

    def load_domain(self, task_id: int, domain: str) -> List[Dict[str, Any]]:
        """Load merged samples for (task_id, domain).

        Returns a list of dicts shaped like multiturn evaluation samples, with
        `expected_output.gold_sequence` populated per turn for tool-call scoring.
        """
        cap_dir = self._cap_dirs.get(task_id)
        if not cap_dir:
            raise ValueError(f"task_id {task_id} not in data. Available: {self.available_capabilities()}")

        input_member = f"{cap_dir}/input/{domain}.json"
        output_member = f"{cap_dir}/output/{domain}.json"

        if not self._src.has(input_member):
            raise FileNotFoundError(
                f"Missing input for task_id={task_id}, domain={domain} (looked for {input_member})"
            )

        has_output = self._src.has(output_member)
        if not has_output and not self.allow_missing_output:
            raise FileNotFoundError(
                f"Missing output for task_id={task_id}, domain={domain} (looked for {output_member})"
            )

        inputs = self._src.read_json(input_member)
        outputs = self._src.read_json(output_member) if has_output else []

        outputs_by_uuid: Dict[str, Dict[str, Any]] = {
            o["uuid"]: o for o in outputs if isinstance(o, dict) and "uuid" in o
        }

        merged: List[Dict[str, Any]] = []
        for sample in inputs:
            uuid = sample.get("uuid")
            gold = outputs_by_uuid.get(uuid)

            turns = sample.get("dialogue", {}).get("turns", []) or []

            gold_per_turn: List[List[Dict[str, Any]]] = []
            answer_per_turn: List[Any] = []
            tool_response_per_turn: List[List[Any]] = []
            if gold and isinstance(gold.get("ground_truth"), list):
                gt_by_turn = {gt.get("turn_id", i): gt for i, gt in enumerate(gold["ground_truth"])}
                for i, _turn in enumerate(turns):
                    gt = gt_by_turn.get(_turn.get("turn_id", i))
                    if not gt:
                        gold_per_turn.append([])
                        answer_per_turn.append(None)
                        tool_response_per_turn.append([])
                        continue
                    gs = gt.get("gold_sequence") or {}
                    # gold_sequence["tool_call"] is a list of per-call groups.
                    # Each group is itself a list of tool_call dicts. Flatten.
                    calls_nested = gs.get("tool_call") or []
                    flat_calls: List[Dict[str, Any]] = []
                    for group in calls_nested:
                        if isinstance(group, list):
                            flat_calls.extend(c for c in group if isinstance(c, dict))
                        elif isinstance(group, dict):
                            flat_calls.append(group)
                    gold_per_turn.append(flat_calls)
                    answer_per_turn.append(gt.get("answer"))

                    # gold_sequence["tool_response"] mirrors the per-call-group
                    # shape of tool_call. Flatten one level so each entry is
                    # the response payload for one tool call. Vakra's
                    # ExactMatchJudge stringifies these and checks set membership.
                    resp_nested = gs.get("tool_response") or []
                    flat_resps: List[Any] = []
                    for group in resp_nested:
                        if isinstance(group, list):
                            flat_resps.extend(group)
                        else:
                            flat_resps.append(group)
                    tool_response_per_turn.append(flat_resps)

            merged_sample: Dict[str, Any] = {
                "uuid": uuid,
                "sample_id": uuid,
                "domain": sample.get("domain", domain),
                "num_turns": sample.get("num_turns", len(turns)),
                "dialogue": {"turns": turns},
                "additional_instructions": sample.get("additional_instructions", ""),
                "expected_output": {
                    "gold_sequence": gold_per_turn,
                    "answer_per_turn": answer_per_turn,
                    "tool_response_per_turn": tool_response_per_turn,
                },
            }
            merged.append(merged_sample)

        return merged


def strip_registry_prefix(name: str, task_id: int, domain: str) -> str:
    """Strip the `task_<task_id>_<domain>_` prefix the registry adds."""
    prefix = f"task_{task_id}_{domain}_"
    if name.startswith(prefix):
        return name[len(prefix) :]
    return name


def diff_tool_calls(
    expected: List[Dict[str, Any]],
    actual: List[Dict[str, Any]],
    task_id: int,
    domain: str,
) -> Dict[str, Any]:
    """Compare expected vs actual tool-call lists for a single turn.

    Returns a dict with counts, normalized call lists, and a per-position diff.
    """

    def _norm(call: Dict[str, Any], strip: bool) -> Dict[str, Any]:
        name = call.get("name", "")
        if strip:
            name = strip_registry_prefix(name, task_id, domain)
        return {
            "name": name,
            "arguments": call.get("arguments", call.get("args", {})),
        }

    expected_norm = [_norm(c, strip=False) for c in expected]
    actual_norm = [_norm(c, strip=True) for c in actual]

    per_position: List[Dict[str, Any]] = []
    for i in range(max(len(expected_norm), len(actual_norm))):
        exp = expected_norm[i] if i < len(expected_norm) else None
        act = actual_norm[i] if i < len(actual_norm) else None
        entry: Dict[str, Any] = {"position": i, "expected": exp, "actual": act}
        if exp is None:
            entry["status"] = "extra"
        elif act is None:
            entry["status"] = "missing"
        elif exp["name"] != act["name"]:
            entry["status"] = "name_mismatch"
        elif exp["arguments"] != act["arguments"]:
            entry["status"] = "args_mismatch"
        else:
            entry["status"] = "match"
        per_position.append(entry)

    return {
        "expected_count": len(expected_norm),
        "actual_count": len(actual_norm),
        "count_match": len(expected_norm) == len(actual_norm),
        "expected": expected_norm,
        "actual": actual_norm,
        "per_position": per_position,
    }
