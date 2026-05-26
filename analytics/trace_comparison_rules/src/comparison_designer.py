## Experimental script on LLM comparison designer
## Input - list of agent system prompts (raw or preprocessed)

## OUTPUT:
## List of objects
## Agent name
## Output schema of an agent: Example oj json
## Comparison Recommendation: List of pairs (schema field, comparison mode)

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from jinja2 import Template

script_dir = os.path.dirname(os.path.abspath(__file__))

load_dotenv()

_utils_dir = os.path.normpath(os.path.join(script_dir, "..", "utils"))
if _utils_dir not in sys.path:
    sys.path.insert(0, _utils_dir)

from llm_client import LLMClient

DEFAULT_MODEL = "aws/claude-opus-4-6"


###############################################################################################
def create_output(agent_name, comparison_output):

    output = {}
    output["agent_name"] = agent_name

    if comparison_output[0:7] == "```json":
        comparison_output = comparison_output[7:]
    if comparison_output[-3:] == "```":
        comparison_output = comparison_output[:-3]

    try:
        output_dict = json.loads(comparison_output)
        output["output_schema"] = output_dict["output_schema"]
        output["fields"] = output_dict["fields"]

    except Exception as e:
        print("COMPARISON output for " + agent_name + " is not a valid json")
        print(e)
        output["output_schema"] = {}
        output["fields"] = {}

    return output


#################################################################################################
def get_comparison_schema(experiment_name, prompt_file, agent_info, agent_config=None, model=None):
    num_agents = len(agent_info)

    prompt_file_path = os.path.join(script_dir, "..", "prompts", prompt_file)

    with open(prompt_file_path) as f:
        prompt_template = Template(f.read())

    current_time = time.strftime("%Y-%m-%d_%H-%M-%S")
    output_file_name = current_time + "_" + experiment_name + ".txt"
    output_file_path = os.path.join(script_dir, "..", "comparison_rules", output_file_name)

    llm_client = LLMClient(model=model or DEFAULT_MODEL)
    system_message = "You are an expert that analyses a system prompt of AI agent"

    # Resolve the prompts directory: new layout under agent_prompts/{config}/,
    # falling back to the legacy agent_data/ location.
    if agent_config:
        prompts_dir = os.path.join(script_dir, "..", "agent_prompts", agent_config)
    else:
        prompts_dir = os.path.join(script_dir, "..", "..", "agent_data")

    for i in range(0, num_agents):
        agent_name = agent_info[i]["agent_name"]
        agent_info_file_path = os.path.join(prompts_dir, agent_info[i]["system_prompt"])

        with open(agent_info_file_path, "r") as file:
            agent_prompt = file.read()

        comparison_output = llm_client.analyze_with_template(
            prompt_template, {"agent_info": agent_prompt}, system_message
        )

        output = create_output(agent_name, comparison_output)

        with open(output_file_path, "a") as f:
            json_str = json.dumps(output, indent=4)
            f.write(json_str + "\n\n")

        print(json_str + "\n\n")

    return output_file_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate comparison rules from agent system prompts.")
    parser.add_argument(
        "--agent-config",
        required=True,
        help="Subfolder under agent_prompts/ containing .jinja2 prompt files (e.g. appworld_mcp)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"LLM model to use (default: {DEFAULT_MODEL})")
    parser.add_argument(
        "--prompt-file",
        default="comparison_designer.jinja",
        help="Jinja2 prompt template in src/prompts/ (default: comparison_designer.jinja)",
    )
    parser.add_argument(
        "--experiment-name", default=None, help="Output file label (default: {agent_config}_comparisons)"
    )
    args = parser.parse_args()

    config_dir = Path(script_dir) / ".." / "agent_prompts" / args.agent_config
    names_file = config_dir / "cuga_agent_manifest.json"
    if not names_file.exists():
        print(f"cuga_agent_manifest.json not found in {config_dir.resolve()}")
        raise SystemExit(1)

    agent_info = json.loads(names_file.read_text())

    experiment_name = args.experiment_name or f"{args.agent_config}_comparisons"

    get_comparison_schema(
        experiment_name,
        args.prompt_file,
        agent_info,
        agent_config=args.agent_config,
        model=args.model,
    )


if __name__ == "__main__":
    main()
