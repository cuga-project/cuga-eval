import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import orjson
from appworld import AppWorld
from appworld.evaluator import TestTracker

logger = logging.getLogger("api_cuga_agent")


def read_json(file_path: str, use_json_plus: bool = True) -> dict:
    try:
        with open(file_path) as file:
            content = file.read()
        if not content.strip():
            return {}
        json_ = orjson
        data = json_.loads(content)
        return data
    except Exception as e:
        logger.error(f"Error reading JSON file {file_path}: {e}")
        return {}


def get_task_difficulty(task_id: str) -> Dict[str, Any]:
    """Get metadata about a task including its difficulty."""
    try:
        proj_path = Path(__file__).parent.parent.parent.resolve()
        task_metadata_file_path = os.path.join(
            proj_path, "appworld", "appworld", "data", "tasks", task_id, "ground_truth", "metadata.json"
        )
        metadata = read_json(task_metadata_file_path)
        return metadata
    except Exception as e:
        logger.error(f"Error getting task difficulty for {task_id}: {e}")
        return {"difficulty": "unknown", "error": str(e)}


def get_task_intent(task_id: str) -> str:
    """Get metadata about a task including its difficulty."""
    try:
        proj_path = Path(__file__).parent.parent.parent.resolve()
        task_metadata_file_path = os.path.join(
            proj_path, "appworld", "appworld", "data", "tasks", task_id, "specs.json"
        )
        metadata = read_json(task_metadata_file_path)
        return metadata['instruction']
    except Exception as e:
        logger.error(f"Error getting task difficulty for {task_id}: {e}")
        return {"difficulty": "unknown", "error": str(e)}


def get_specific_task_levels(
    task_ids: list[str],
    specific_task_levels: list[int],
) -> list[str]:
    """
    Get specific task levels based on the provided task level and task levels.

    Args:
        task_ids (list[str]): The list of task IDs to filter.
        task_levels (list[str]): The list of task levels to filter.

    Returns:
        list[str]: A list of task levels that match the specific task level.
    """
    filtered_task_ids = []
    for task_id in task_ids:
        try:
            difficulty = get_task_difficulty(task_id).get('difficulty')
            if difficulty in specific_task_levels:
                filtered_task_ids.append(task_id)
        except Exception as e:
            logger.error(f"Error checking difficulty for task {task_id}: {e}")

    return filtered_task_ids


def evaluation_task_info(evaluation: TestTracker):
    """
    Convert the evaluation object to a dictionary.
    """
    evaluation_dict = {
        "failures": evaluation.failures,
        "passes": evaluation.passes,
        "num_tests": evaluation.num_tests,
        "pass_count": evaluation.pass_count,
        "pass_percentage": evaluation.pass_percentage,
        "requirement": evaluation.requirement,
        "success": evaluation.success,
        "suppress_errors": evaluation.suppress_errors,
        "test_data": evaluation.test_data,
        "total_count": evaluation.total_count,
    }
    return evaluation_dict


def appworld_task_info(world: AppWorld, config=None, task_metadata: Optional[Dict[str, Any]] = None):
    appworld_data = {
        "task_id": world.task_id,
        "task_instruction": world.task.instruction,
        "servers_config": {
            k: v for k, v in (config.__dict__ if config else {}).items() if k.endswith('_url')
        },
        "ground_truth": world.task.ground_truth.answer,
        "test_data": world.task.ground_truth.test_data,
    }
    return appworld_data
