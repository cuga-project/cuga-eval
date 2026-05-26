import datetime
import json
import logging
import os
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Configure logging for the experiment manager
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
experiment_logger = logging.getLogger("experiment_manager")


@dataclass
class TaskResult:
    """Data class for storing the results of a single task run."""

    task_id: str
    success: bool = False
    steps: int = 0
    start_time: Optional[datetime.datetime] = None
    end_time: Optional[datetime.datetime] = None
    duration: Optional[float] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    exceptions: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    evaluation: Dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None
    total_llm_calls: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    node_timings: Dict[str, float] = None
    llm_call_details: List[Dict[str, Any]] = None
    generation_timings: List[Dict[str, Any]] = None
    full_execution_time: float = 0.0
    api_calls: int = 0
    total_cache_input_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert the TaskResult to a dictionary for JSON serialization."""
        result = asdict(self)
        # Convert datetime objects to ISO format strings
        if self.start_time:
            result["start_time"] = self.start_time.isoformat()
        if self.end_time:
            result["end_time"] = self.end_time.isoformat()
        return result

    def add_appworld_data(self, appworld_data: Dict[str, Any]) -> None:
        """Add AppWorld data to the task result."""
        self.metadata["appworld_data"] = appworld_data

    def add_evaluation(self, evaluation: Dict[str, Any]) -> None:
        """Add evaluation data to the task result."""
        self.evaluation.update(evaluation)

    def add_event(self, event: Dict[str, Any]) -> None:
        """Add an event to the task result."""
        # if list of events then extend else append
        if isinstance(event, list):
            self.events.extend(event)
        else:
            self.events.append(event)

    def add_exception(self, exception: Exception, context: str = "") -> None:
        """Add an exception to the task result."""
        self.exceptions.append(
            {
                "type": type(exception).__name__,
                "message": str(exception),
                "traceback": traceback.format_exc(),
                "context": context,
                "timestamp": datetime.datetime.now().isoformat(),
            }
        )

    def set_start_time(self) -> None:
        """Set the start time for the task."""
        self.start_time = datetime.datetime.now()

    def set_end_time(self) -> None:
        """Set the end time and calculate duration for the task."""
        self.end_time = datetime.datetime.now()
        # if self.start_time:
        #     self.duration = (self.end_time - self.start_time).total_seconds()


class ExperimentManager:
    """Manager for running experiments, collecting data, and generating reports."""

    def __init__(
        self,
        experiment_name: str,
        dataset_name: Optional[str] = None,
        base_dir: str = os.path.join(Path(__file__).resolve().parent.parent, "experiments"),
        continue_experiment: bool = False,
    ):
        """
        Initialize the experiment manager.

        Args:
            experiment_name: Base name for the experiment
            dataset_name: Name of the dataset being used
            base_dir: Base directory for storing experiments
            continue_experiment: Whether to continue an existing experiment
        """
        self.base_experiment_name = experiment_name
        self.dataset_name = dataset_name or "unknown"
        self.base_dir = base_dir

        # Create a timestamp for the experiment. The 6-char uuid suffix prevents
        # directory collisions when multiple ExperimentManager instances are
        # created at the same wall-clock second (per-task instantiation loops)
        # OR when datetime.now() is frozen by AppWorld's freezegun setup —
        # without it, every task in a multi-task run overwrites the previous
        # task's output files (issue #48).
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_suffix = uuid.uuid4().hex[:6]

        # Generate the full experiment name
        self.full_experiment_name = f"{experiment_name}_{self.dataset_name}_{timestamp}_{unique_suffix}"

        # If continuing an experiment, find the most recent matching experiment
        if continue_experiment:
            existing_experiments = self._find_existing_experiments(experiment_name, dataset_name)
            if existing_experiments:
                self.full_experiment_name = existing_experiments[0]
                experiment_logger.info(f"Continuing experiment: {self.full_experiment_name}")

        # Create the experiment directory
        self.experiment_dir = os.path.join(base_dir, "outputs", self.full_experiment_name)
        os.makedirs(self.experiment_dir, exist_ok=True)

        # Initialize the summary report
        self.summary_report = {
            "experiment_name": self.full_experiment_name,
            "dataset_name": dataset_name,
            "start_time": time.time(),
            "tasks_total": 0,
            "tasks_completed": 0,
            "success_rate": 0.0,
            "avg_steps": 0.0,
            "avg_duration": 0.0,
            "exceptions_count": 0,
            "task_results": {},
            "total_cache_input_tokens": 0,
        }

        # Load existing summary if continuing an experiment
        if continue_experiment:
            summary_path = os.path.join(self.experiment_dir, f"{self.dataset_name}_results.json")
            if os.path.exists(summary_path):
                try:
                    with open(summary_path, "r") as f:
                        self.summary_report = json.load(f)
                    experiment_logger.info(f"Loaded existing summary from {summary_path}")
                except Exception as e:
                    experiment_logger.error(f"Failed to load existing summary: {e}")

        experiment_logger.info(f"Experiment initialized: {self.full_experiment_name}")
        experiment_logger.info(f"Experiment directory: {self.experiment_dir}")

    def _find_existing_experiments(self, experiment_name: str, dataset_name: Optional[str]) -> List[str]:
        """Find existing experiments matching the given name and dataset."""
        if not os.path.exists(os.path.join(self.base_dir, "outputs")):
            return []

        # Check if experiment_name already contains a datetime suffix (format: YYYYMMDD_HHMMSS)
        import re

        datetime_pattern = re.compile(r'.*_\d{8}_\d{6}$')
        is_exact_experiment = datetime_pattern.match(experiment_name) is not None

        all_experiments = os.listdir(os.path.join(self.base_dir, "outputs"))

        if is_exact_experiment:
            # For exact experiment names (with datetime), look for the exact match
            matching_experiments = [
                exp
                for exp in all_experiments
                if exp == experiment_name or exp == f"{experiment_name}_{dataset_name}"
            ]
        else:
            # For general experiment names, find all that match the pattern
            matching_experiments = [
                exp for exp in all_experiments if exp.startswith(f"{experiment_name}_{dataset_name}")
            ]

        return sorted(matching_experiments, reverse=True)  # Most recent first

    def create_task_result(self, task_id: str, task_metadata: Optional[Dict[str, Any]] = None) -> TaskResult:
        """
        Create a new task result object.

        Args:
            task_id: ID of the task
            task_metadata: Metadata about the task

        Returns:
            A new TaskResult object
        """
        result = TaskResult(task_id=task_id)
        result.metadata = task_metadata or {}
        result.set_start_time()
        return result

    def update_task_result(self, task_result: TaskResult) -> None:
        """
        Update a task result and save it to disk.

        Args:
            task_result: The task result to update
        """
        # Ensure end time is set
        if not task_result.end_time:
            task_result.set_end_time()

        # Create task directory if needed
        task_dir = os.path.join(self.experiment_dir, "tasks")
        os.makedirs(task_dir, exist_ok=True)

        # Create a comprehensive filename for the task result
        difficulty = task_result.metadata.get("difficulty", "unknown")
        # success_str = "success" if task_result.success else "failure"
        # steps_str = f"steps_{task_result.steps}"

        task_filename = f"{task_result.task_id}_{self.dataset_name}_diff_{difficulty}.json"
        task_path = os.path.join(task_dir, task_filename)

        try:
            if os.path.exists(task_path):
                experiment_logger.warning(f"Task result file already exists: {task_path}")
                experiment_logger.info(f"Overwriting existing task result file: {task_path}")
            else:
                experiment_logger.info(f"Creating new task result file: {task_path}")

            with open(task_path, "w") as f:
                json.dump(task_result.to_dict(), f, indent=2)
            experiment_logger.info(f"Saved task result to {task_path}")

        except Exception as e:
            experiment_logger.error(f"Failed to save task result: {e}")
            task_result.add_exception(e, "save_task_result")

        # Update the summary report
        self._update_summary_report(task_result)

    def _update_summary_report(self, task_result: TaskResult) -> None:
        """
        Update the summary report with a task result.

        Args:
            task_result: The task result to add to the summary
        """
        task_id = task_result.task_id
        # Add task result to summary
        self.summary_report["task_results"][task_id] = {
            "success": task_result.success,
            "steps": task_result.steps,
            "duration": task_result.duration,
            "exceptions_count": len(task_result.exceptions),
            "difficulty": task_result.metadata.get("difficulty", "unknown"),
            "api_calls": task_result.api_calls,
            "total_llm_calls": task_result.total_llm_calls,
            "total_tokens": task_result.total_tokens,
            "total_cost": task_result.total_cost,
            "node_timings": task_result.node_timings,
            "llm_call_details": task_result.llm_call_details,
            "generation_timings": task_result.generation_timings,
            "full_execution_time": task_result.full_execution_time,
            "cache_input_tokens": task_result.total_cache_input_tokens,
            "trace_id": task_result.trace_id,
        }

        # Update summary statistics
        all_tasks = self.summary_report["task_results"].values()
        self.summary_report["tasks_total"] = len(all_tasks)
        self.summary_report["tasks_completed"] = sum(1 for t in all_tasks if t["success"])
        self.summary_report["exceptions_count"] = sum(t["exceptions_count"] for t in all_tasks)
        self.summary_report["total_cost"] = sum(t['total_cost'] for t in all_tasks)
        self.summary_report["total_cache_input_tokens"] = sum(t['cache_input_tokens'] for t in all_tasks)

        if all_tasks:
            self.summary_report["success_rate"] = (
                self.summary_report["tasks_completed"] / self.summary_report["tasks_total"]
            )
            self.summary_report["avg_steps"] = sum(t["steps"] for t in all_tasks) / len(all_tasks)
            durations = [t["duration"] for t in all_tasks if t["duration"] is not None]
            if durations:
                self.summary_report["avg_duration"] = sum(durations) / len(durations)

        # Update end time
        self.summary_report["end_time"] = datetime.datetime.now().isoformat()
        self.summary_report["duration"] = time.time() - self.summary_report["start_time"]

        # Save the updated summary
        summary_path = os.path.join(self.experiment_dir, f"{self.dataset_name}_results.json")
        try:
            with open(summary_path, "w") as f:
                json.dump(self.summary_report, f, indent=2)
            experiment_logger.info(f"Updated summary report at {summary_path}")
        except Exception as e:
            experiment_logger.error(f"Failed to update summary report: {e}")

    def save_final_report(self) -> None:
        """Save the final summary report with additional statistics."""
        # Group tasks by difficulty
        difficulty_groups = {}
        for task_id, result in self.summary_report["task_results"].items():
            difficulty = result.get("difficulty", "unknown")
            if difficulty not in difficulty_groups:
                difficulty_groups[difficulty] = {
                    "total": 0,
                    "completed": 0,
                    "steps": 0,
                    "duration": 0,
                    "exceptions": 0,
                }

            group = difficulty_groups[difficulty]
            group["total"] += 1
            if result["success"]:
                group["completed"] += 1
            group["steps"] += result["steps"]
            group["duration"] += result.get("duration", 0) or 0
            group["exceptions"] += result.get("exceptions_count", 0)

        # Calculate statistics per difficulty
        for difficulty, group in difficulty_groups.items():
            if group["total"] > 0:
                group["success_rate"] = group["completed"] / group["total"]
                group["avg_steps"] = group["steps"] / group["total"]
                group["avg_duration"] = group["duration"] / group["total"]

        # Add to summary report
        self.summary_report["by_difficulty"] = difficulty_groups

        # Save the final report
        final_path = os.path.join(self.experiment_dir, f"{self.dataset_name}_final_report.json")
        try:
            with open(final_path, "w") as f:
                json.dump(self.summary_report, f, indent=2)
            experiment_logger.info(f"Saved final report to {final_path}")
        except Exception as e:
            experiment_logger.error(f"Failed to save final report: {e}")

    def handle_exception(self, task_id: str, exception: Exception, context: str = "") -> None:
        """
        Handle an exception that occurred during an experiment.

        Args:
            task_id: ID of the task where the exception occurred
            exception: The exception that occurred
            context: Context where the exception occurred
        """
        # Log the exception
        experiment_logger.error(f"Exception in task {task_id} ({context}): {exception}")
        experiment_logger.error(traceback.format_exc())

        # Create or retrieve task result
        task_path = os.path.join(self.experiment_dir, "tasks")
        possible_files = (
            [f for f in os.listdir(task_path) if f.startswith(task_id)] if os.path.exists(task_path) else []
        )

        task_result = None
        if possible_files:
            try:
                with open(os.path.join(task_path, possible_files[0]), "r") as f:
                    task_data = json.load(f)
                task_result = TaskResult(task_id=task_id)
                for key, value in task_data.items():
                    if hasattr(task_result, key):
                        setattr(task_result, key, value)
            except Exception as e:
                experiment_logger.error(f"Failed to load existing task result: {e}")

        if not task_result:
            task_result = TaskResult(task_id=task_id)
            task_result.set_start_time()

        # Add the exception
        task_result.add_exception(exception, context)
        task_result.set_end_time()

        # Update the task result
        self.update_task_result(task_result)
