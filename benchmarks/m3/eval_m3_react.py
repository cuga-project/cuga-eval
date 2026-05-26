"""Evaluation loop for M3 tasks using the generic ReAct agent."""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

import os

os.chdir(project_root)

from config_loader import load_eval_config

load_eval_config("m3")

import os

cuga_logging_dir = os.getenv("CUGA_LOGGING_DIR")
if not cuga_logging_dir:
    raise RuntimeError("CUGA_LOGGING_DIR not set after load_eval_config! Check config files.")

import asyncio
import json
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple, Union

from loguru import logger

logger.info(f"CUGA_LOGGING_DIR: {cuga_logging_dir}")
logger.info(f"TRACKER_ENABLED: {os.environ.get('DYNACONF_ADVANCED_FEATURES__TRACKER_ENABLED', 'not set')}")

from cuga.backend.activity_tracker.tracker import ActivityTracker
from cuga.backend.cuga_graph.state.agent_state import VariablesManager

from benchmarks.helpers import (
    add_policy_via_agent,
    clear_all_policies,
    create_activity_tracker_callback,
    evaluate_task_with_langfuse_react,
    flush_langfuse,
    save_evaluation_results,
    setup_react_agent_for_evaluation,
)
from benchmarks.m3.m3_data_loader import M3DataLoader


# Lazy: m3_vakra_score's top-level import instantiates LLM judges that need
# API_KEY. --no-ground-truth runs never score, so don't import eagerly.
def _vakra():
    from benchmarks.m3 import m3_vakra_score as _mod

    return _mod


def vakra_score_results_async(*args, **kwargs):
    return _vakra().score_results_async(*args, **kwargs)


def patch_tracker_scores(*args, **kwargs):
    return _vakra().patch_tracker_scores(*args, **kwargs)


def print_vakra_summary(*args, **kwargs):
    return _vakra().print_vakra_summary(*args, **kwargs)


def _vakra_capability_for_task_id(*args, **kwargs):
    return _vakra().capability_name_for_task_id(*args, **kwargs)


# Map capability service-name → numeric task_id understood by M3DataLoader.
# Mirrors the registry config in benchmarks/m3/config/m3_registry_m3_data.yaml.
_CAPABILITY_TASK_IDS = {
    "m3_task_2": 2,
    "m3_task_3": 3,
    "capability_dashboard_apis": 2,
    "capability_multihop_reasoning": 3,
}


def _stringify_answer(answer: Any) -> str:
    if answer is None:
        return ""
    if isinstance(answer, str):
        return answer
    try:
        return json.dumps(answer, default=str)
    except (TypeError, ValueError):
        return str(answer)


def _merged_to_react_test_case(
    sample: Dict[str, Any], task_id: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """Convert one M3DataLoader merged sample (multi-turn shape) into the
    single-turn ``test_case`` shape expected by ``evaluate_task_with_langfuse_react``.

    Only single-turn samples are supported (zip data has ``num_turns: 1``);
    multi-turn samples are skipped with a warning so they don't silently degrade.
    The numeric ``task_id`` is stamped on each test_case so the evaluator can
    group cases by ``(task_id, domain)`` and restart the registry per group.
    """
    turns = sample.get("dialogue", {}).get("turns") or []
    if not turns:
        return None
    if len(turns) > 1:
        logger.warning(f"Skipping multi-turn sample {sample.get('uuid')!r}: react agent is single-turn only.")
        return None

    intent = turns[0].get("query", "")
    expected = sample.get("expected_output") or {}
    gold_seq = expected.get("gold_sequence") or []
    answers = expected.get("answer_per_turn") or []
    tool_resps = expected.get("tool_response_per_turn") or []
    gold_calls = gold_seq[0] if gold_seq else []
    gt_answer = _stringify_answer(answers[0] if answers else None)
    gt_tool_responses = tool_resps[0] if tool_resps else []

    return {
        "name": sample.get("uuid"),
        "uuid": sample.get("uuid"),
        "intent": intent,
        "domain": sample.get("domain"),
        "m3_task_id": task_id,
        "expected_output": {
            "response": gt_answer,
            "tool_calls": gold_calls,
            "tool_responses": gt_tool_responses,
            "keywords": [],  # legacy keyword scoring is disabled in m3
        },
    }


def _resolve_capability_task_id(name: Optional[str], available: List[int]) -> Optional[int]:
    """Map a capability/service name (or numeric task_id) to a numeric task_id."""
    if name is None:
        return None
    if str(name).isdigit():
        return int(name)
    return _CAPABILITY_TASK_IDS.get(str(name))


tracker = ActivityTracker()
var_manager = VariablesManager()


class M3ReactEvaluator:
    """Evaluator for M3 tasks using the generic ReAct agent."""

    def __init__(
        self,
        difficulty_filter: Optional[str] = None,
        task_id: Optional[Union[str, List[str]]] = None,
        m3_data_path: Optional[str] = None,
        capability: Optional[str] = None,
        domain_filter: Optional[Union[str, List[str]]] = None,
        max_samples: Optional[int] = None,
        from_config: Optional[str] = None,
        no_ground_truth: bool = False,
    ):
        self.difficulty_filter = difficulty_filter
        self.task_ids = [task_id] if isinstance(task_id, str) else task_id
        self.m3_data_path = m3_data_path
        self.capability = capability
        # Normalize domain_filter to a set[str] so single/multi forms behave the same
        if domain_filter is None:
            self.domain_filter: Optional[set] = None
        elif isinstance(domain_filter, str):
            self.domain_filter = {domain_filter}
        else:
            self.domain_filter = set(domain_filter) if domain_filter else None
        self.max_samples = max_samples
        self.from_config = from_config
        self.no_ground_truth = no_ground_truth
        self.agent = None
        self.langfuse_handler = None
        self.results: List[Dict[str, Any]] = []
        # Registry process started for the --m3-data path; stopped in shutdown().
        self._registry_process = None
        self._registry_tmp_yaml: Optional[str] = None
        # Cached expanded registry services for m3-data mode (filled in setup()).
        self._m3_registry_services: List[Dict[str, Any]] = []
        self._active_group: Optional[Tuple[int, str]] = None

    def _load_m3_registry_services(self) -> List[Dict[str, Any]]:
        """Expand m3_registry_m3_data.yaml into per-(task_id, domain) services.

        Cached on the evaluator so we only expand once even when iterating
        many groups.
        """
        if self._m3_registry_services:
            return self._m3_registry_services
        import yaml

        from benchmarks.m3.eval_m3 import expand_registry_config

        config_path = self.from_config or os.path.join(
            os.path.dirname(__file__), "config", "m3_registry_m3_data.yaml"
        )
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Registry config not found: {config_path}")

        expanded_path = expand_registry_config(config_path)
        try:
            with open(expanded_path) as f:
                expanded = yaml.safe_load(f) or {}
            self._m3_registry_services = expanded.get("services", []) or []
        finally:
            try:
                os.unlink(expanded_path)
            except OSError:
                pass
        return self._m3_registry_services

    def _find_service_for_group(self, task_id: int, domain: str) -> Optional[Dict[str, Any]]:
        for svc in self._load_m3_registry_services():
            name = list(svc.keys())[0]
            meta = svc[name].get("metadata", {})
            if int(meta.get("task_id", -1)) != int(task_id):
                continue
            domains = meta.get("domains") or []
            names = [d if isinstance(d, str) else d.get("name") for d in domains]
            if domain in names:
                return svc
        return None

    async def _stop_active_registry(self) -> None:
        if self._registry_process is not None:
            from benchmarks.m3.eval_m3 import stop_registry_server

            try:
                await stop_registry_server(self._registry_process)
            except Exception as e:
                logger.warning(f"stop_registry_server failed (continuing): {e}")
            finally:
                self._registry_process = None
        if self._registry_tmp_yaml:
            try:
                os.unlink(self._registry_tmp_yaml)
            except OSError:
                pass
            self._registry_tmp_yaml = None
        # OS may take a moment to fully release the port (TIME_WAIT etc).
        # Without this poll, the next group's start_registry_server hits
        # "Port 8001 is already in use" and aborts.
        await self._wait_for_port_free(8001, timeout=15.0)
        self._active_group = None

    async def _wait_for_port_free(self, port: int, timeout: float) -> None:
        import socket

        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                in_use = sock.connect_ex(("127.0.0.1", port)) == 0
            finally:
                sock.close()
            if not in_use:
                return
            # Try to nudge any straggler.
            try:
                import subprocess

                subprocess.run(  # noqa: S603 — fixed args, no shell, port is an int
                    ["lsof", "-ti", f":{port}"],  # noqa: S607 — lsof resolved from PATH
                    capture_output=True,
                    text=True,
                    timeout=2,
                ).stdout.strip()
            except Exception:  # noqa: S110 — port discovery is best-effort
                pass
            await asyncio.sleep(0.5)
        # Last resort: force-kill anything on that port and check once more.
        try:
            import subprocess

            pids = (
                subprocess.run(  # noqa: S603 — fixed args, no shell, port is an int
                    ["lsof", "-ti", f":{port}"],  # noqa: S607 — lsof resolved from PATH
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                .stdout.strip()
                .split()
            )
            for pid in pids:
                subprocess.run(  # noqa: S603 — pid is from lsof stdout, not user input
                    ["kill", "-9", pid],  # noqa: S607 — kill resolved from PATH
                    capture_output=True,
                    timeout=2,
                )
        except Exception:  # noqa: S110 — kill cleanup is best-effort
            pass
        await asyncio.sleep(0.5)

    async def _set_active_group(self, task_id: int, domain: str) -> None:
        """Restart the registry to expose only the (task_id, domain) service
        and re-create the react agent so its tool provider sees the new tools.

        This is the same pattern cuga's run_config_mode follows: each
        (task_id, domain) gets its own registry instance on :8001 with that
        domain's MCP server. Without this, the agent's CombinedToolProvider is
        stale and it tries to call tools that aren't exposed.
        """
        if self._active_group == (task_id, domain) and self.agent is not None:
            return  # already on this group

        # Local import so non-m3-data runs don't pull cuga modules.
        from benchmarks.m3.eval_m3 import (
            _write_single_service_yaml,
            start_registry_server,
        )

        await self._stop_active_registry()

        chosen = self._find_service_for_group(task_id, domain)
        if chosen is None:
            raise RuntimeError(f"No registry service matches task_id={task_id} domain={domain!r}")

        mini_yaml = _write_single_service_yaml(chosen)
        self._registry_tmp_yaml = mini_yaml
        chosen_name = list(chosen.keys())[0]
        logger.info(
            f"🚀 Starting registry for react/m3-data group: "
            f"service={chosen_name} task_id={task_id} domain={domain}"
        )
        self._registry_process = await start_registry_server(mini_yaml)

        # Recreate the agent — its CombinedToolProvider was initialized against
        # the previous registry's tool list and would otherwise be stale.
        self.agent, self.langfuse_handler = await setup_react_agent_for_evaluation()
        try:
            await clear_all_policies(self.agent)  # type: ignore[arg-type]
        except Exception as e:
            logger.warning(f"Skipping policy reset for react agent: {e}")

        self._active_group = (task_id, domain)

    async def setup(self, policies: Optional[List] = None):
        # In --m3-data mode the agent + registry are created lazily inside
        # evaluate_all on a per-(task_id, domain) basis (see _set_active_group).
        # Cache `policies` so we can apply them after each group switch.
        self._pending_policies = policies or None
        if self.m3_data_path:
            # Pre-load the expanded service list so failures surface early.
            self._load_m3_registry_services()
            return

        # Non-m3-data path: single agent, no per-domain switching.
        self.agent, self.langfuse_handler = await setup_react_agent_for_evaluation()

        logger.info("Resetting policy database...")
        try:
            await clear_all_policies(self.agent)  # type: ignore[arg-type]
        except Exception as e:
            logger.warning(f"Skipping policy reset for react agent: {e}")

        if policies:
            logger.info(f"Loading {len(policies)} policies...")
            for policy in policies:
                try:
                    await add_policy_via_agent(self.agent, policy)  # type: ignore[arg-type]
                except Exception as e:
                    logger.warning(f"Skipping policy load for react agent: {e}")
            logger.info(f"✅ Processed {len(policies)} policies")
        else:
            logger.info("No policies to load")

    async def evaluate_task(self, task: Dict[str, Any], task_index: int) -> Dict[str, Any]:
        task_name = task.get("name", "unknown")
        intent = task.get("intent", "")

        tracker.reset(intent=intent, task_id=task_name)
        var_manager.reset()

        tracker_callback = create_activity_tracker_callback(tracker, var_manager)

        if self.agent is None:
            raise RuntimeError("Agent not initialized")

        result = await evaluate_task_with_langfuse_react(
            agent=self.agent,
            task=task,
            task_index=task_index,
            langfuse_handler=self.langfuse_handler,
            user_context=None,
            tracker_callback=tracker_callback,
            track_tool_calls=True,
        )

        # Preserve task identity + GT bits Vakra needs to build a real
        # ground-truth dialogue. Without this, _to_vakra_pair sees no GT and
        # ExactMatchJudge passes vacuously, masking failures as successes.
        if "uuid" in task and "uuid" not in result:
            result["uuid"] = task["uuid"]
        if task.get("domain") and not result.get("domain"):
            result["domain"] = task["domain"]
        if task.get("intent") and not result.get("intent"):
            result["intent"] = task["intent"]
        if task.get("expected_output"):
            result["expected_output"] = task["expected_output"]
        return result

    def _load_test_cases_from_m3_data(self) -> List[Dict[str, Any]]:
        """Load test cases from an M3 zip/dir via M3DataLoader and convert to
        the test_case shape expected by the react agent path."""
        loader = M3DataLoader(
            self.m3_data_path,  # type: ignore[arg-type]
            allow_missing_output=self.no_ground_truth,
        )
        available = loader.available_capabilities()
        if self.capability is not None:
            tid = _resolve_capability_task_id(self.capability, available)
            if tid is None:
                raise ValueError(
                    f"Unknown --capability {self.capability!r}. "
                    f"Known: m3_task_2, m3_task_3 or numeric task ids ({available})."
                )
            task_ids = [tid]
        else:
            task_ids = list(available)

        all_cases: List[Dict[str, Any]] = []
        for tid in task_ids:
            for dom in loader.available_domains(tid):
                if self.domain_filter and dom not in self.domain_filter:
                    continue
                merged_samples = loader.load_domain(tid, dom)
                for sample in merged_samples:
                    tc = _merged_to_react_test_case(sample, task_id=tid)
                    if tc is not None:
                        all_cases.append(tc)
        return all_cases

    async def evaluate_all(self, data_path: Optional[str] = None):
        if self.m3_data_path:
            test_cases = self._load_test_cases_from_m3_data()
            logger.info(
                f"Loaded {len(test_cases)} test case(s) from --m3-data "
                f"{self.m3_data_path}"
                + (f" capability={self.capability}" if self.capability else "")
                + (f" domain={self.domain_filter}" if self.domain_filter else "")
            )
        else:
            if data_path is None:
                data_path = os.path.join(os.path.dirname(__file__), "data", "hockey.json")

            with open(data_path, "r") as f:
                data = json.load(f)

            test_cases = []
            for app_data in data:
                if "test_cases" in app_data:
                    test_cases.extend(app_data["test_cases"])

        if self.task_ids:
            task_ids_lower = [tid.lower() for tid in self.task_ids]
            test_cases = [tc for tc in test_cases if tc.get("name", "").lower() in task_ids_lower]
            if not test_cases:
                logger.error(f"Task(s) {self.task_ids} not found in test data")
                return
            logger.info(f"Filtered to {len(test_cases)} task(s): {self.task_ids}")
        elif self.difficulty_filter:
            test_cases = [
                tc for tc in test_cases if tc.get("difficulty", "").lower() == self.difficulty_filter.lower()
            ]
            logger.info(f"Filtered to {len(test_cases)} {self.difficulty_filter} tasks")
        else:
            logger.info(f"Evaluating all {len(test_cases)} tasks")

        if self.max_samples and len(test_cases) > self.max_samples:
            test_cases = test_cases[: self.max_samples]
            logger.info(f"Limited to {self.max_samples} task(s)")

        experiment_name = os.getenv("M3_EXPERIMENT_NAME", "m3_evaluation_react")
        task_ids_label = [tc.get("name", f"task_{i}") for i, tc in enumerate(test_cases, 1)]
        tracker.start_experiment(
            task_ids=task_ids_label,
            experiment_name=experiment_name,
            description="M3 benchmark evaluation (react)",
        )

        self.results = []
        if self.m3_data_path:
            await self._run_m3_data_groups(test_cases)
        else:
            await self._run_single_group(test_cases)

        flush_langfuse(self.langfuse_handler)

    async def _run_single_group(self, test_cases: List[Dict[str, Any]]) -> None:
        """Non-m3-data flow: one agent, no registry switching, score once at end."""
        for i, task in enumerate(test_cases, 1):
            logger.info(f"\n[{i}/{len(test_cases)}] Processing task...")
            result = await self.evaluate_task(task, task_index=i)
            self.results.append(result)
            if i < len(test_cases):
                await asyncio.sleep(0.5)

        if self.no_ground_truth:
            from collections import defaultdict

            from benchmarks.m3.eval_m3 import write_predictions_no_gt

            grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for r in self.results:
                grouped[r.get("domain") or "unknown"].append(r)
            for dom, rs in grouped.items():
                try:
                    write_predictions_no_gt(rs, output_dir=Path(__file__).parent / "results", domain=dom)
                except Exception as e:
                    logger.warning(f"[{dom}] writing prediction file failed: {e}")
            return

        try:
            cap_name = os.getenv("M3_VAKRA_CAPABILITY")
            if not cap_name and self.capability:
                cap_name = _vakra_capability_for_task_id(self.capability)
            if not cap_name:
                cap_name = "capability_bi_apis"
            # domain_filter is normalized to a set; pick a single domain string
            # for vakra. If multiple are filtered, vakra is per-domain anyway —
            # _run_m3_data_groups handles that path.
            single_domain = next(iter(self.domain_filter)) if self.domain_filter else None
            domain_name = (
                os.getenv("M3_DOMAIN")
                or single_domain
                or next((r.get("domain") for r in self.results if r.get("domain")), "hockey")
            )
            await vakra_score_results_async(
                self.results,
                output_dir=Path(__file__).parent / "results",
                capability_name=cap_name,
                domain=domain_name,
            )
            # Push Vakra-corrected scores back into the tracker so
            # trajectories/results.json matches report.md (issue #71).
            patch_tracker_scores(self.results, tracker)
        except Exception as e:
            logger.warning(f"Vakra scoring failed (continuing): {e}")

    async def _run_m3_data_groups(self, test_cases: List[Dict[str, Any]]) -> None:
        """m3-data flow: group test cases by (task_id, domain), restart the
        registry per group, recreate the agent so its tools match, then score
        each group with the matching capability_name."""
        groups: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
        for tc in test_cases:
            task_id = tc.get("m3_task_id")
            domain = tc.get("domain")
            if task_id is None or domain is None:
                logger.warning(f"Skipping test case without m3_task_id/domain: {tc.get('uuid')}")
                continue
            groups[(int(task_id), str(domain))].append(tc)

        if not groups:
            logger.error("No groupable test cases found for --m3-data run.")
            return

        sorted_groups = sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1]))
        total_groups = len(sorted_groups)
        global_idx = 0
        global_total = sum(len(tcs) for _, tcs in sorted_groups)
        for gi, ((task_id, domain), tcs) in enumerate(sorted_groups, 1):
            logger.info("=" * 80)
            logger.info(f"[group {gi}/{total_groups}] task_id={task_id} domain={domain} tasks={len(tcs)}")
            logger.info("=" * 80)
            try:
                await self._set_active_group(task_id, domain)
            except Exception as e:
                logger.error(f"Failed to set active group task_id={task_id} domain={domain}: {e}")
                # Mark all tasks in this group as failed-to-setup but keep going.
                for tc in tcs:
                    self.results.append(
                        {
                            "uuid": tc.get("uuid"),
                            "name": tc.get("name"),
                            "intent": tc.get("intent"),
                            "domain": domain,
                            "m3_task_id": task_id,
                            "expected_output": tc.get("expected_output"),
                            "success": False,
                            "match_rate": 0.0,
                            "error": f"registry-setup-failed: {e}",
                        }
                    )
                continue

            group_results: List[Dict[str, Any]] = []
            for ti, task in enumerate(tcs, 1):
                global_idx += 1
                logger.info(
                    f"[group {gi}/{total_groups}] "
                    f"[{ti}/{len(tcs)}] (overall {global_idx}/{global_total}) "
                    f"Processing task..."
                )
                result = await self.evaluate_task(task, task_index=global_idx)
                group_results.append(result)
                self.results.append(result)
                if ti < len(tcs):
                    await asyncio.sleep(0.5)

            # In --no-ground-truth mode, skip scoring; just write predictions
            # for this domain and move on.
            if self.no_ground_truth:
                from benchmarks.m3.eval_m3 import write_predictions_no_gt

                try:
                    write_predictions_no_gt(
                        group_results,
                        output_dir=Path(__file__).parent / "results",
                        domain=domain,
                    )
                except Exception as e:
                    logger.warning(f"[{domain}] writing prediction file failed: {e}")
                await self._stop_active_registry()
                continue

            # Vakra-score this group with the matching capability_name + domain.
            # IMPORTANT: keep the registry UP while scoring. Vakra spawns its
            # own stdio session via docker exec; that exec runs mcp_dispatch.py
            # which fetches the OpenAPI spec from the registry on :8001 at
            # startup. If the registry is already gone, mcp_dispatch fails with
            # "All connection attempts failed" and we see "Failed to connect to
            # MCP server via stdio". (Cuga's run_config_mode follows the same
            # pattern: registry stays up until the per-domain block exits.)
            try:
                cap_name = (
                    os.getenv("M3_VAKRA_CAPABILITY")
                    or _vakra_capability_for_task_id(task_id)
                    or "capability_bi_apis"
                )
                await vakra_score_results_async(
                    group_results,
                    output_dir=Path(__file__).parent / "results",
                    capability_name=cap_name,
                    domain=domain,
                )
                # Push Vakra-corrected scores back into the tracker so
                # trajectories/results.json matches report.md (issue #71).
                patch_tracker_scores(group_results, tracker)
            except Exception as e:
                logger.warning(f"Vakra scoring failed for task_id={task_id} domain={domain}: {e}")

            # Now safe to tear down the registry — both the agent run and the
            # Vakra replay are done with this group's capability container.
            await self._stop_active_registry()

    def print_summary(self):
        # Vakra-only summary; the legacy keyword summary was removed from M3.
        if self.no_ground_truth:
            from benchmarks.m3.eval_m3 import print_no_gt_summary

            print_no_gt_summary(self.results)
            return
        if any("vakra" in r for r in self.results):
            print_vakra_summary(self.results)
        else:
            logger.warning("No Vakra scores produced — check API_KEY and the Vakra warnings above.")

    def save_results(self, output_dir: Optional[Path] = None):
        if output_dir is None:
            output_dir = Path(__file__).parent / "results"
        return save_evaluation_results(self.results, output_dir, prefix="m3")

    async def shutdown(self) -> None:
        """Stop the registry started in --m3-data mode and clean up its temp yaml."""
        if self._registry_process is not None:
            try:
                from benchmarks.m3.eval_m3 import stop_registry_server

                await stop_registry_server(self._registry_process)
            except Exception as e:
                logger.warning(f"stop_registry_server failed (continuing): {e}")
            finally:
                self._registry_process = None
        if self._registry_tmp_yaml:
            try:
                os.unlink(self._registry_tmp_yaml)
            except OSError:
                pass
            self._registry_tmp_yaml = None


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate M3 tasks with React")
    parser.add_argument(
        "--difficulty",
        type=str,
        choices=["easy", "medium", "hard"],
        default=None,
        help="Filter by difficulty level (default: all)",
    )
    default_data_file = os.getenv("M3_DATA_FILE", "hockey.json")
    parser.add_argument(
        "--data",
        type=str,
        default=os.path.join(os.path.dirname(__file__), "data", default_data_file),
        help=f"Path to data file (default: data/{default_data_file})",
    )
    parser.add_argument(
        "--task",
        type=str,
        nargs="*",
        default=None,
        help="Run specific tasks by ID/name. Accepts multiple. Overrides --difficulty filter.",
    )
    parser.add_argument(
        "--m3-data",
        dest="m3_data",
        type=str,
        default=None,
        help="Path to an M3 zip / merged-data directory (e.g. small_train.zip). "
        "When set, --data is ignored and samples are loaded via M3DataLoader.",
    )
    parser.add_argument(
        "--no-ground-truth",
        dest="no_ground_truth",
        action="store_true",
        help="Run --m3-data on input-only data (no output/ folder). Skips "
        "evaluation/scoring; collects predictions only into "
        "results/_vakra/prediction/<domain>.json.",
    )
    parser.add_argument(
        "--capability",
        type=str,
        default=None,
        help="Capability filter for --m3-data mode (m3_task_2 or m3_task_3).",
    )
    parser.add_argument(
        "--domain",
        type=str,
        nargs="*",
        default=None,
        help="Domain filter for --m3-data mode (e.g. hockey). Accepts multiple values to match eval_m3.py.",
    )
    parser.add_argument(
        "--max-samples",
        "--max-samples-per-domain",
        dest="max_samples",
        type=int,
        default=None,
        help="Maximum number of test cases to run after filtering. "
        "`--max-samples-per-domain` is accepted as an alias for parity with eval_m3.py.",
    )
    # Tolerate flags that eval.sh forwards but eval_m3_react.py doesn't use.
    parser.add_argument("--from-config", dest="from_config", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--batch-size", dest="batch_size", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--domains-per-container", dest="domains_per_container", default=None, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--parallel-containers", dest="parallel_containers", default=None, help=argparse.SUPPRESS
    )

    from benchmarks.helpers.logging_args import add_log_level_args, apply_log_level

    add_log_level_args(parser)

    args = parser.parse_args()
    apply_log_level(args)

    if getattr(args, "no_ground_truth", False) and not args.m3_data:
        logger.error("--no-ground-truth requires --m3-data <path>")
        return

    evaluator = M3ReactEvaluator(
        difficulty_filter=args.difficulty,
        task_id=args.task,
        m3_data_path=args.m3_data,
        capability=args.capability,
        domain_filter=args.domain,
        max_samples=args.max_samples,
        from_config=args.from_config,
        no_ground_truth=getattr(args, "no_ground_truth", False),
    )

    try:
        await evaluator.setup()
        await evaluator.evaluate_all(args.data)
        evaluator.print_summary()
        evaluator.save_results()
    except KeyboardInterrupt:
        logger.warning("\nEvaluation interrupted by user")
        if evaluator.results:
            evaluator.print_summary()
            evaluator.save_results()
    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        await evaluator.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

# Made with Bob
