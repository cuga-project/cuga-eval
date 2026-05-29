"""Helper functions for SDK evaluation benchmarks."""

from .config_loader import load_eval_config
from .token_usage import TokenUsageCallback

__all__ = [
    "load_eval_config",
    "MetricsConfig",
    "TokenUsageCallback",
    "setup_agent_with_tools",
    "setup_react_agent_for_evaluation",
    "setup_langfuse",
    "clear_all_policies",
    "add_policy_via_agent",
    "check_keywords",
    "evaluate_task_with_langfuse",
    "evaluate_task_with_langfuse_react",
    "evaluate_multiturn_task_with_langfuse",
    "evaluate_multiturn_task_with_langfuse_react",
    "print_evaluation_summary",
    "flush_langfuse",
    "create_activity_tracker_callback",
    "save_evaluation_results",
]

_LAZY_EXPORTS = {
    "MetricsConfig": ("sdk_eval_helpers", "MetricsConfig"),
    "setup_agent_with_tools": ("sdk_eval_helpers", "setup_agent_with_tools"),
    "setup_react_agent_for_evaluation": ("sdk_eval_helpers", "setup_react_agent_for_evaluation"),
    "setup_langfuse": ("sdk_eval_helpers", "setup_langfuse"),
    "clear_all_policies": ("sdk_eval_helpers", "clear_all_policies"),
    "add_policy_via_agent": ("sdk_eval_helpers", "add_policy_via_agent"),
    "check_keywords": ("sdk_eval_helpers", "check_keywords"),
    "evaluate_task_with_langfuse": ("sdk_eval_helpers", "evaluate_task_with_langfuse"),
    "evaluate_task_with_langfuse_react": ("sdk_eval_helpers", "evaluate_task_with_langfuse_react"),
    "evaluate_multiturn_task_with_langfuse": ("sdk_eval_helpers", "evaluate_multiturn_task_with_langfuse"),
    "evaluate_multiturn_task_with_langfuse_react": (
        "sdk_eval_helpers",
        "evaluate_multiturn_task_with_langfuse_react",
    ),
    "print_evaluation_summary": ("sdk_eval_helpers", "print_evaluation_summary"),
    "flush_langfuse": ("sdk_eval_helpers", "flush_langfuse"),
    "create_activity_tracker_callback": ("sdk_eval_helpers", "create_activity_tracker_callback"),
    "save_evaluation_results": ("sdk_eval_helpers", "save_evaluation_results"),
}


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        import importlib

        module_name, attr_name = _LAZY_EXPORTS[name]
        module = importlib.import_module(f".{module_name}", __name__)
        return getattr(module, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
