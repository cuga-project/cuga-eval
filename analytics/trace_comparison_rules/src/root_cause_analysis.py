## Root cause analysis - Last stage of automatic trace comparison

## OUTPUT:
## Report on problem clusters, root causes and recommendations

import itertools
import os
import sys
import threading
import time
from contextlib import contextmanager

from dotenv import load_dotenv
from jinja2 import Template

script_dir = os.path.dirname(os.path.abspath(__file__))

if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

load_dotenv()

from llm_client import LLMClient

MODEL = "aws/claude-opus-4-6"


@contextmanager
def _spinner(message: str):
    stop = threading.Event()

    def _run():
        frames = itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
        start = time.time()
        while not stop.is_set():
            elapsed = time.time() - start
            sys.stdout.write(f"\r{next(frames)} {message} [{elapsed:.0f}s]  ")
            sys.stdout.flush()
            time.sleep(0.1)
        elapsed = time.time() - start
        sys.stdout.write(f"\r✓ {message} [{elapsed:.0f}s]\n")
        sys.stdout.flush()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join()


def run_root_cause_analysis(
    prompt_file,
    input_data,
    input_dir=None,
    output_dir=None,
):
    """
    Perform root cause analysis on trace comparison reports.

    Args:
        prompt_file: Jinja2 template filename inside src/prompts/.
        input_data: Filename of the comparison report.
        input_dir: Directory containing input_data. Defaults to src/comparison_steps/.
        output_dir: Directory for the analysis output. Defaults to src/comparison_summaries/.
    """
    prompt_file_path = os.path.join(script_dir, "..", "prompts", prompt_file)

    with open(prompt_file_path, encoding="utf-8") as f:
        prompt_template = Template(f.read())

    _input_dir = input_dir if input_dir else os.path.join(script_dir, "comparison_steps")
    report_file_path = os.path.join(_input_dir, input_data)

    with open(report_file_path, "r", encoding="utf-8") as file:
        trace_comparison_report = file.read()

    llm_client = LLMClient(model=MODEL)
    system_message = "You are an expert that analyzes trace comparison reports for a multi-agent system"

    with _spinner(f"Running root cause analysis with {MODEL}"):
        analysis_output = llm_client.analyze_with_template(
            prompt_template,
            {"trace_comparison_report": trace_comparison_report},
            system_message,
        )

    output_file_name = "summary.md"
    _output_dir = output_dir if output_dir else os.path.join(script_dir, "comparison_summaries")
    os.makedirs(_output_dir, exist_ok=True)
    output_file_path = os.path.join(_output_dir, output_file_name)

    with open(output_file_path, "w", encoding="utf-8") as f:
        f.write(analysis_output)
        print(analysis_output)

    return output_file_path, llm_client.last_usage
