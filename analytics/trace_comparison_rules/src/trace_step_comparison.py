"""
Script for step-by-step comparison of two traces or groups of traces.

This module compares traces using the Internal Representation (IR) format,
which allows for comparison of traces from different log formats.
"""

import os
import sys

# Ensure both the script directory (for sibling imports) and the repo root
# (for src.* imports) are on sys.path regardless of CWD or how the IDE launches this.
_script_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_script_dir, "..", ".."))
# Add the script dir (sibling imports) and src/utils directly.
# Do NOT add _repo_root itself — the agentops editable install puts its own
# 'src' package into site-packages (runtime, core, extensions…), and adding
# _repo_root would create a conflicting 'src' that hides 'src.utils'.
for _p in [_script_dir, os.path.join(_repo_root, "src", "utils")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv

load_dotenv()

_agentops_path = os.getenv("AGENTOPS_PATH")
if _agentops_path and _agentops_path not in sys.path:
    sys.path.insert(0, _agentops_path)

import json
from typing import Any

from comparison_functions import (
    both_or_none,
    deep_equal,
    fuzzy_similar,
    numeric_similar,
    same_type_and_length,
    semantic_similar,
)
from trace_adapter import TraceAdapterFactory
from trace_ir import TraceIR

_ADAPTER_MODULES = {
    "agentops": "agentops_adapter",
    "langfuse": "langfuse_adapter",
}

script_dir = os.path.dirname(os.path.abspath(__file__))

extraction_functions = {
    "APICodePlannerAgent": "extract_api_code_planner_schema",
    "Reflection": "extract_reflection_fields_v2",
    "Code Agent": "extract_code_agent_content",
}

skip_step_output_rules = {"APIPlannerAgent": [""]}


################################################################################
def print_add_data(output_data, str):
    print(str)
    output_data += str
    return output_data


#################################################################################
def get_nested_from_dict(d, s):
    """
    Access nested dictionary values using a dot-separated string path.
    Supports list fan-out:
        If the path hits a list, the next key is applied to every element
        of that list (if possible), and returns a list of results.
    Returns None if the initial root is not a dict.
    """
    if not isinstance(d, dict):
        return None

    keys: Any = s.split(".")
    curr: dict[Any, Any] = d

    for i, key in enumerate(keys):
        key = key.replace("[]", "")
        # Case 1: current object is a dict
        if isinstance(curr, dict):
            if key in curr:
                curr: dict[Any, Any] = curr[key]
            else:
                return None

        # Case 2: current object is a list → fan-out over elements
        elif isinstance(curr, list):
            results: list[Any] = []
            for elem in curr:
                # Each elem should be a dict to access the next key
                if isinstance(elem, dict) and key in elem:
                    results.append(elem[key])
                else:
                    results.append(None)  # or skip via "continue"
            curr: dict[Any, Any] = results

        # Any other type → cannot go deeper
        else:
            return None

    return curr


######################################################################################
def perform_step_comparison(
    current_comparison_schema,
    current_successful_output,
    current_failed_output,
    output_data,
    divergence_found,
    agent_name,
):

    num_fields = len(current_comparison_schema)

    at_least_one_match = False
    at_least_one_failure = False

    list_different_fields = []

    for i in range(0, num_fields):
        current_field = current_comparison_schema[i]["schema_field_name"]

        # output_data = print_add_data(output_data,f"\nComparison field: {current_field}\n")

        current_successful_field = get_nested_from_dict(current_successful_output, current_field)
        current_failed_field = get_nested_from_dict(current_failed_output, current_field)

        current_comparison = current_comparison_schema[i]["comparison_mode"]

        # field_exists must run before the both-non-None gate: it exists precisely
        # to detect one-sided presence, which the gate would filter out.
        if current_comparison == "field_exists":
            output_data = print_add_data(output_data, f"\nComparison field: {current_field}\n")
            output_data = print_add_data(output_data, f"\nSuccessful trace: {current_successful_field}\n")
            output_data = print_add_data(output_data, f"\nFailed trace: {current_failed_field}\n")
            output_data = print_add_data(output_data, f"\nComparison mode: {current_comparison}\n")
            comparison_result = both_or_none(current_successful_field, current_failed_field)
            if comparison_result:
                at_least_one_match = True
                output_data = print_add_data(output_data, "Fields are similar\n\n")
            else:
                at_least_one_failure = True
                output_data = print_add_data(output_data, "**Fields are different**\n\n")
                list_different_fields.append(current_field)
            continue  # flags are set; skip the both-non-None gate below

        if current_successful_field is not None and current_failed_field is not None:
            output_data = print_add_data(output_data, f"\nComparison field: {current_field}\n")
            output_data = print_add_data(output_data, f"\nSuccessful trace: {current_successful_field}\n")
            output_data = print_add_data(output_data, f"\nFailed trace: {current_failed_field}\n")
            output_data = print_add_data(output_data, f"\nComparison mode: {current_comparison}\n")

            if current_comparison == "exact_match":
                comparison_result = deep_equal(current_successful_field, current_failed_field)
            elif current_comparison == "fuzzy_match":
                comparison_result = fuzzy_similar(current_successful_field, current_failed_field)
            elif current_comparison == "semantic_similarity":
                comparison_result = semantic_similar(current_successful_field, current_failed_field)
            elif current_comparison == "approximate_numeric":
                comparison_result = numeric_similar(current_successful_field, current_failed_field)
            elif current_comparison == "list_length":
                comparison_result = same_type_and_length(current_successful_field, current_failed_field)
            else:
                print(
                    f"Warning: unknown comparison mode {current_comparison!r} for field {current_field!r} (agent: {agent_name!r}) — skipping."
                )
                continue

            if comparison_result:
                at_least_one_match = True
                output_data = print_add_data(output_data, "Fields are similar\n\n")
            else:
                at_least_one_failure = True
                output_data = print_add_data(output_data, "**Fields are different**\n\n")
                list_different_fields.append(current_field)

    if at_least_one_match and not at_least_one_failure:
        output_data = print_add_data(output_data, "**Step outputs are similar**\n\n")
    elif at_least_one_failure:
        output_data = print_add_data(output_data, "**Step outputs are different**\n\n")
    else:
        output_data = print_add_data(output_data, "Comparison could not be performed\n\n")

    if not divergence_found and at_least_one_failure:
        output_data = print_add_data(
            output_data,
            f"**First divergence between steps is detected**\nAgent name: {agent_name}\nDifferent fields: ",
        )
        num_different_fields = len(list_different_fields)

        for i in range(0, num_different_fields - 1):
            output_data = print_add_data(output_data, f"{list_different_fields[i]}, ")
        output_data = print_add_data(output_data, f"{list_different_fields[num_different_fields - 1]}\n\n")

    return output_data, at_least_one_failure


def perform_trace_comparison(
    output_data: str,
    agent_data_dict: dict[str, Any],
    trace1: TraceIR,
    trace2: TraceIR,
) -> str:
    """
    Compare two traces step by step.

    Args:
        output_data: Accumulated output string
        agent_data_dict: Dictionary of agent comparison schemas
        trace1: First trace (successful)
        trace2: Second trace (failed)

    Returns:
        str: Updated output data with comparison results
    """
    num_steps1 = trace1.num_steps
    num_steps2 = trace2.num_steps

    divergence_found = False
    divergence_step_found = False

    current_successful_step = 0
    current_failed_step = 0

    step_counter = 1

    comparison_length = min(num_steps1, num_steps2)

    while current_successful_step < num_steps1 and current_failed_step < num_steps2:
        step1 = trace1.get_step(current_successful_step)
        step2 = trace2.get_step(current_failed_step)

        if step1 is None or step2 is None:
            break

        current_successful_agent = step1.agent_name
        current_failed_agent = step2.agent_name

        current_successful_output = step1.llm_output_structured
        current_failed_output = step2.llm_output_structured

        if current_successful_agent == current_failed_agent:
            if current_successful_agent in skip_step_output_rules.keys():
                skip_output_values = skip_step_output_rules[current_successful_agent]
                if (
                    current_failed_output in skip_output_values
                    and current_successful_output in skip_output_values
                ):
                    current_successful_step += 1
                    current_failed_step += 1
                    continue

        output_data = print_add_data(output_data, f"### Step {step_counter}\n\n")
        step_counter += 1

        output_data = print_add_data(output_data, f"Successful trace: {current_successful_agent}\n\n")

        output_data = print_add_data(output_data, f"Failed trace: {current_failed_agent}\n\n")

        # if current_successful_output is None or current_successful_output == "" or current_successful_output == []:
        #     output_data = print_add_data(output_data, "Output of succesful trace is empty\n\n")

        if current_successful_agent == current_failed_agent:
            if current_successful_agent in agent_data_dict.keys():
                # Process retrials
                if (
                    current_failed_step < comparison_length - 1
                    and current_successful_step < comparison_length - 1
                ):
                    # If empty output of failed trajectory - move forward
                    if current_successful_output and not current_failed_output:
                        next_step1 = trace1.get_step(current_successful_step + 1)
                        next_step2 = trace2.get_step(current_failed_step + 1)
                        if (
                            next_step1
                            and next_step2
                            and next_step1.agent_name != current_successful_agent
                            and next_step2.agent_name == current_failed_agent
                        ):
                            current_failed_step += 1
                            step2 = trace2.get_step(current_failed_step)
                            if step2:
                                current_failed_output = step2.llm_output_structured

                    # If empty output of successful trajectory - move forward
                    elif not current_successful_output and current_failed_output:
                        next_step1 = trace1.get_step(current_successful_step + 1)
                        next_step2 = trace2.get_step(current_failed_step + 1)
                        if (
                            next_step1
                            and next_step2
                            and next_step2.agent_name != current_failed_agent
                            and next_step1.agent_name == current_successful_agent
                        ):
                            current_successful_step += 1
                            step1 = trace1.get_step(current_successful_step)
                            if step1:
                                current_successful_output = step1.llm_output_structured

                # TODO: decide if we wish to print it for step below
                if (
                    current_failed_output is None
                    or current_failed_output == ""
                    or current_failed_output == []
                ):
                    output_data = print_add_data(output_data, "Output of failed trace is empty\n\n")

                # perform comparison
                if current_successful_output and current_failed_output:
                    current_comparison_schema = agent_data_dict[current_successful_agent]["fields"]
                    output_data, divergence_step_found = perform_step_comparison(
                        current_comparison_schema,
                        current_successful_output,
                        current_failed_output,
                        output_data,
                        divergence_found,
                        current_successful_agent,
                    )

        else:
            output_data = print_add_data(
                output_data,
                "**Final divergence: different agents are called for the two traces**\n\n\n",
            )
            break

        if divergence_step_found:
            divergence_found = True

        if current_successful_step >= num_steps1 - 1 or current_failed_step >= num_steps2 - 1:
            if current_successful_step >= num_steps1 - 1 and current_failed_step < num_steps2 - 1:
                output_data = print_add_data(
                    output_data,
                    "**Final divergence: Successful trace completed**\n\n\n",
                )
            elif current_successful_step < num_steps1 - 1 and current_failed_step >= num_steps2 - 1:
                output_data = print_add_data(
                    output_data, "**Final divergence: Failed trace completed**\n\n\n"
                )
            else:
                output_data = print_add_data(output_data, "**Both traces completed**\n\n\n")

        current_successful_step += 1
        current_failed_step += 1

    return output_data


async def run_comparison(
    successful_logs: list[str],
    failed_logs: list[str],
    agent_data_file: str,
    agent_prompts: dict[str, str],
    trace_format: str = "agentops",
    output_dir: str | None = None,
) -> str | None:
    """
    Run comparison between successful and failed traces.

    Args:
        successful_logs: List of absolute paths to successful trace files.
        failed_logs: List of absolute paths to failed trace files.
        agent_data_file: Filename of the comparison rules (inside src/comparison_rules/).
        agent_prompts: Dictionary mapping agent names to system prompts.
        trace_format: Format of trace logs (default: "agentops").
        output_dir: Directory to write output files. Defaults to src/comparison_steps/.

    Returns:
        Path to the output file, or None if nothing was written.
    """
    # Read agent comparison rules
    rules_data_folder = os.path.join(script_dir, "..", "comparison_rules")
    rules_data_path = os.path.join(rules_data_folder, agent_data_file)

    agent_data_dict = {}
    buffer = ""

    num_logs = len(successful_logs)

    if num_logs != len(failed_logs):
        print("Error! Logs lists lengths are incompatible.")
        return

    output_data = ""
    print("")

    # Process rule data for agents
    with open(rules_data_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip() == "":
                if buffer.strip():
                    current_dict = json.loads(buffer)
                    agent_name = current_dict["agent_name"]
                    agent_data_dict[agent_name] = current_dict
                    buffer = ""
            else:
                buffer += line

    # Read last block
    if buffer.strip():
        current_dict = json.loads(buffer)
        agent_name = current_dict["agent_name"]
        agent_data_dict[agent_name] = current_dict

    # Import only the needed adapter so its module-level register_adapter() call fires
    import importlib

    importlib.import_module(_ADAPTER_MODULES[trace_format])

    # Create trace adapter
    adapter = TraceAdapterFactory.create_adapter(
        trace_format,
        agent_prompts=agent_prompts,
        extraction_functions=extraction_functions,
    )

    file_name = "step_comparison.md"

    output_folder = output_dir if output_dir else os.path.join(script_dir, "comparison_steps")
    os.makedirs(output_folder, exist_ok=True)

    for i in range(0, num_logs):
        file_name1 = successful_logs[i]
        file_name2 = failed_logs[i]

        # Load traces using adapter
        trace1 = await adapter.load_trace(file_name1)
        trace2 = await adapter.load_trace(file_name2)

        task_formulation1 = trace1.task_formulation
        task_formulation2 = trace2.task_formulation

        # Handle task formulation warnings
        if task_formulation1 is None and task_formulation2 is None:
            print("Warning! Task formulations were not found.")
            print("")
            task_formulation1 = "Unknown Task"

        elif task_formulation1 is None and task_formulation2 is not None:
            print("Warning! First task formulation was not found.")
            print("")
            task_formulation1 = task_formulation2

        elif task_formulation1 is not None and task_formulation2 is None:
            print("Warning! Second task formulation was not found.")
            print("")

        elif task_formulation1.strip() != task_formulation2.strip():
            print("Warning! Task formulations are not synced.")
            print(task_formulation1)
            print(task_formulation2)
            print("")

        output_data = print_add_data(output_data, f"## Comparison {i + 1}\n\n")
        output_data = print_add_data(output_data, "### Task: " + task_formulation1 + "\n\n")

        # Perform comparison using IR
        output_data = perform_trace_comparison(
            output_data,
            agent_data_dict,
            trace1,
            trace2,
        )

        output_path = os.path.join(output_folder, file_name)
        with open(output_path, "a", encoding="utf-8") as f:
            f.write(output_data)

        output_data = ""

        print("Comparison finished")

    return output_path if num_logs > 0 else None
