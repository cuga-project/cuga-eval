"""AppWorld evaluation for external agents (Deep Agents, OpenClaw, Hermes).

Reuses CombinedToolProvider LangChain tools and the same AppWorld harness as the SDK path.
"""

import sys
from datetime import datetime
from pathlib import Path

_eval_run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

appworld_src = Path(__file__).parent / "appworld" / "src"
if appworld_src.is_dir():
    sys.path.insert(0, str(appworld_src))

from config_loader import load_eval_config

load_eval_config("appworld")

import argparse
import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from cuga.backend.activity_tracker.tracker import ActivityTracker, Step
from cuga.backend.cuga_graph.state.agent_state import VariablesManager
from cuga.backend.cuga_graph.utils.controller import AgentRunner
from cuga.config import settings
from loguru import logger

cuga_logging_dir = os.getenv("CUGA_LOGGING_DIR")
if not cuga_logging_dir:
    raise RuntimeError("CUGA_LOGGING_DIR not set after load_eval_config! Check config files.")

from appworld import AppWorld, load_task_ids

from benchmarks.appworld.agents.factory import EXTERNAL_AGENT_NAMES, create_appworld_agent
from benchmarks.appworld.agents.tools import (
    authenticate_apps_for_task,
    reset_registry,
    setup_appworld_tools,
    task_app_names,
)
from benchmarks.appworld.utils.appworld_harness import build_user_context, invoke_and_score_appworld_agent
from benchmarks.appworld.utils.appworld_utils import (
    get_specific_task_levels,
    get_task_difficulty,
)
from benchmarks.helpers import (
    flush_langfuse,
    print_evaluation_summary,
    save_evaluation_results,
    setup_langfuse,
)
from benchmarks.helpers.eval_status import EvalStatusWriter

tracker = ActivityTracker()
var_manager = VariablesManager()


def _task_ids_for_run(
    task_id: Optional[str],
    dataset_name: str,
    eval_key: Optional[str],
    from_dataset: bool,
) -> tuple[List[str], Optional[str]]:
    if task_id:
        return [task_id], None
    if from_dataset:
        return load_task_ids(dataset_name), None
    key = eval_key or getattr(settings.eval_config, "eval_key", None)
    if key:
        raw = settings.eval_config.get(key)
        if raw:
            ids = [str(t) for t in raw]
            return ids, str(key)
        logger.warning(
            f"eval_config.toml has no task list for key {key!r}; falling back to dataset {dataset_name!r}"
        )
    return load_task_ids(dataset_name), None


class AppWorldExternalEvaluator:
    def __init__(
        self,
        agent_name: str,
        dataset_name: str = "train",
        task_id: Optional[str] = None,
        specific_task_levels: Optional[List[int]] = None,
        experiment_name: Optional[str] = None,
        environment_url: Optional[str] = None,
        apis_url: Optional[str] = None,
        eval_key: Optional[str] = None,
        from_dataset: bool = False,
        max_steps: int = 12,
    ):
        normalized = agent_name.strip().lower()
        if normalized not in EXTERNAL_AGENT_NAMES:
            raise ValueError(
                f"Unsupported agent {agent_name!r}. Supported: {', '.join(sorted(EXTERNAL_AGENT_NAMES))}"
            )
        self.agent_name = normalized
        self.dataset_name = dataset_name
        self.task_id = task_id
        self.specific_task_levels = specific_task_levels
        self.eval_key = eval_key
        self.from_dataset = from_dataset
        self.max_steps = max_steps
        self.experiment_name = experiment_name or os.getenv(
            f"APPWORLD_{normalized.upper()}_EXPERIMENT_NAME",
            f"appworld_{normalized}_evaluation",
        )
        self.environment_url = environment_url or f"http://localhost:{settings.server_ports.environment_url}"
        self.apis_url = apis_url or f"http://localhost:{settings.server_ports.apis_url}"
        self.agent: Any = None
        self.langfuse_handler: Optional[Any] = None
        self.results: List[Dict[str, Any]] = []
        self.status_writer = EvalStatusWriter()
        self._run_status: str = "completed"

    async def setup(self):
        self.langfuse_handler = setup_langfuse()
        logger.info(f"External agent {self.agent_name!r} ready (task-scoped tools loaded per task)")

    def _agent_for_tools(self, tools: list[Any]) -> Any:
        prefer_eval_llm = self.agent_name in ("openclaw", "hermes")
        kwargs: dict[str, Any] = {"max_steps": self.max_steps}
        if prefer_eval_llm:
            kwargs["prefer_eval_llm"] = True
        if self.agent_name == "deepagents":
            kwargs["prefer_tool_react"] = os.getenv("APPWORLD_DEEPAGENTS_TOOL_REACT", "").lower() in (
                "1",
                "true",
                "yes",
            )
        return create_appworld_agent(self.agent_name, tools=tools, **kwargs)

    async def evaluate_task(self, task_id: str, task_index: int) -> Dict[str, Any]:
        meta = get_task_difficulty(task_id)
        difficulty = str(meta.get("difficulty", "unknown"))
        agent_runner = AgentRunner(browser_enabled=False)

        try:
            await reset_registry()
            await agent_runner.initialize_appworld_env()

            with AppWorld(
                task_id=task_id,
                experiment_name=self.experiment_name,
                remote_environment_url=self.environment_url,
                remote_apis_url=self.apis_url,
            ) as world:
                tracker.reset(intent=world.task.instruction, task_id=world.task_id)
                var_manager.reset()
                tracker.current_date = world.task.datetime.isoformat()
                tracker.pi = json.dumps(world.task.supervisor)
                tracker.pi += f"current_datetime: {tracker.current_date}"

                await authenticate_apps_for_task(world)
                user_context = build_user_context(world)

                app_names = task_app_names(world)
                _tool_provider, task_tools = await setup_appworld_tools(app_names=app_names)
                agent = self._agent_for_tools(task_tools)

                merged = await invoke_and_score_appworld_agent(
                    agent=agent,
                    langfuse_handler=self.langfuse_handler,
                    world=world,
                    task_id=task_id,
                    task_index=task_index,
                    difficulty=difficulty,
                    user_context=user_context,
                    agent_label=self.agent_name,
                    tracker=tracker,
                )

                agent_steps = merged.get("steps")
                if agent_steps is None:
                    agent_steps = len(tracker.steps) or len(merged.get("tool_calls") or [])
                eval_info = merged.get("appworld_evaluation") or {}
                report_md = json.dumps(
                    {
                        "task_id": task_id,
                        "success": merged.get("success"),
                        "pass_percentage": eval_info.get("pass_percentage"),
                        "evaluation": eval_info,
                    }
                )
                score = float(merged.get("match_rate", 0.0))
                if merged.get("error"):
                    tracker.finish_task(
                        intent=world.task.instruction,
                        site="",
                        task_id=task_id,
                        eval=report_md,
                        score=0.0,
                        agent_answer="",
                        exception=True,
                        num_steps=agent_steps,
                        total_llm_calls=merged.get("total_llm_calls", 0),
                        total_tokens=merged.get("total_tokens", 0),
                        total_cost=merged.get("total_cost", 0.0),
                        total_cache_input_tokens=merged.get("total_cache_input_tokens", 0),
                        duration=merged.get("full_execution_time", 0),
                        agent_v=self.agent_name,
                    )
                    tracker.collect_score(0.0)
                else:
                    tracker.finish_task(
                        intent=world.task.instruction,
                        site="",
                        task_id=task_id,
                        eval=report_md,
                        score=score,
                        agent_answer=merged.get("response", ""),
                        exception=False,
                        num_steps=agent_steps,
                        total_llm_calls=merged.get("total_llm_calls", 0),
                        total_tokens=merged.get("total_tokens", 0),
                        total_cost=merged.get("total_cost", 0.0),
                        total_cache_input_tokens=merged.get("total_cache_input_tokens", 0),
                        duration=merged.get("full_execution_time", 0),
                        agent_v=self.agent_name,
                    )
                    tracker.collect_step(Step(name="EvaluationResult", data=report_md))
                    tracker.collect_score(score)

                return merged
        finally:
            try:
                await agent_runner.env.close()
            except Exception as e:
                logger.debug(f"agent_runner.env.close: {e}")

    async def evaluate_all(self):
        task_ids, eval_group = _task_ids_for_run(
            self.task_id,
            self.dataset_name,
            self.eval_key,
            self.from_dataset,
        )
        if self.task_id:
            logger.info(f"Single task mode: {self.task_id}")
        elif eval_group:
            logger.info(f"Tasks from eval_config.toml (group {eval_group!r}): {len(task_ids)} tasks")
        else:
            logger.info(f"Dataset '{self.dataset_name}': {len(task_ids)} tasks")

        if self.specific_task_levels and not self.task_id:
            task_ids = get_specific_task_levels(task_ids, self.specific_task_levels)
            logger.info(f"Filtered to levels {self.specific_task_levels}: {len(task_ids)} tasks")

        tracker.start_experiment(
            task_ids=task_ids,
            experiment_name=self.experiment_name,
            description=f"AppWorld external agent ({self.agent_name}) evaluation",
        )

        eval_key_label = eval_group or self.eval_key
        self.status_writer.start_run(
            agent=self.agent_name,
            task_ids=task_ids,
            eval_key=eval_key_label,
            model=os.getenv("MODEL_NAME"),
            max_steps=self.max_steps,
        )

        self.results = []
        try:
            for i, tid in enumerate(task_ids, 1):
                logger.info(f"\n[{i}/{len(task_ids)}] Task {tid}")
                self.status_writer.start_task(tid, i)
                result = await self.evaluate_task(tid, task_index=i)
                self.results.append(result)
                self.status_writer.finish_task(result)
                if i < len(task_ids):
                    await asyncio.sleep(0.5)
        except KeyboardInterrupt:
            self._run_status = "interrupted"
            raise
        except Exception:
            self._run_status = "failed"
            raise
        finally:
            self.status_writer.finish_run(self._run_status)

        flush_langfuse(self.langfuse_handler)

    def print_summary(self):
        print_evaluation_summary(self.results)

    def save_results(self, output_dir: Optional[str] = None):
        if output_dir is None:
            output_dir = Path(__file__).parent / "experiments" / "outputs"
        prefix = f"appworld_{self.agent_name}"
        saved_file = save_evaluation_results(
            self.results,
            Path(output_dir),
            prefix=prefix,
            run_timestamp=_eval_run_timestamp,
        )

        final_report_path = saved_file.parent / f"{prefix}_{_eval_run_timestamp}_final_report.json"
        if not final_report_path.exists():
            try:
                import shutil

                shutil.copy(saved_file, final_report_path)
                logger.info(f"Final report: {final_report_path}")
            except Exception as e:
                logger.warning(f"Failed to create final report copy: {e}")

        return saved_file


async def main():
    parser = argparse.ArgumentParser(description="Evaluate AppWorld tasks via external agent adapters")
    parser.add_argument(
        "--agent",
        required=True,
        choices=sorted(EXTERNAL_AGENT_NAMES),
        help="External agent to run",
    )
    parser.add_argument("--dataset", default="train", help="Dataset name when using --from-dataset")
    parser.add_argument("--task-id", default=None, help="Run a single task ID")
    parser.add_argument("--eval-key", default=None, help="Task group key in eval_config.toml")
    parser.add_argument("--from-dataset", action="store_true", help="Use load_task_ids(--dataset)")
    parser.add_argument(
        "--specific-task-levels",
        type=int,
        nargs="+",
        choices=[1, 2, 3],
        help="Filter tasks by difficulty level",
    )
    parser.add_argument(
        "--environment-url",
        default=f"http://localhost:{settings.server_ports.environment_url}",
        help="AppWorld environment server URL",
    )
    parser.add_argument(
        "--apis-url",
        default=f"http://localhost:{settings.server_ports.apis_url}",
        help="AppWorld APIs URL",
    )
    parser.add_argument("--experiment-name", default=None, help="Experiment name")
    parser.add_argument("--max-steps", type=int, default=12, help="Max ReAct steps for tool-loop agents")

    from benchmarks.helpers.logging_args import add_log_level_args, apply_log_level

    add_log_level_args(parser)
    args = parser.parse_args()
    apply_log_level(args)

    eval_key_toml = getattr(settings.eval_config, "eval_key", None)
    eval_key_resolved = args.eval_key or eval_key_toml
    experiment_name = args.experiment_name
    if experiment_name is None:
        experiment_name = os.getenv(f"APPWORLD_{args.agent.upper()}_EXPERIMENT_NAME")
    if experiment_name is None and not args.from_dataset and eval_key_resolved and not args.task_id:
        experiment_name = eval_key_resolved
    if experiment_name is None:
        experiment_name = f"appworld_{args.agent}_evaluation"

    evaluator = AppWorldExternalEvaluator(
        agent_name=args.agent,
        dataset_name=args.dataset,
        task_id=args.task_id,
        specific_task_levels=args.specific_task_levels,
        experiment_name=experiment_name,
        environment_url=args.environment_url,
        apis_url=args.apis_url,
        eval_key=args.eval_key,
        from_dataset=args.from_dataset,
        max_steps=args.max_steps,
    )

    try:
        await evaluator.setup()
        await evaluator.evaluate_all()
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


if __name__ == "__main__":
    asyncio.run(main())
