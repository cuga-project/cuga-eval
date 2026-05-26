"""
Test script for Langfuse adapter.
"""

import asyncio

from langfuse_adapter import LangfuseAdapter


async def test_langfuse_adapter():
    """Test the Langfuse adapter with the example log file."""

    # Create adapter instance
    adapter = LangfuseAdapter()

    # Load the example trace
    trace = await adapter.load_trace("e775c78_1_7b67bd9bfaa2221023891cfd304328b8_s.json")

    # Print trace information
    print(f"Trace ID: {trace.trace_id}")
    print(f"Task Formulation: {trace.task_formulation}")
    print(f"Number of steps: {trace.num_steps}")
    print(f"Agent sequence: {trace.agent_sequence}")
    print()

    # Print details of each step
    for i, step in enumerate(trace.steps):
        print(f"Step {i}:")
        print(f"  Agent: {step.agent_name}")
        print(
            f"  System Prompt (first 100 chars): {step.system_prompt[:100] if step.system_prompt else 'None'}..."
        )
        print(f"  User Input (first 100 chars): {step.user_input[:100] if step.user_input else 'None'}...")
        print(
            f"  LLM Output (first 100 chars): {step.llm_output_raw[:100] if step.llm_output_raw else 'None'}..."
        )
        print(f"  Start Time: {step.start_time}")
        print(f"  End Time: {step.end_time}")
        print()


if __name__ == "__main__":
    asyncio.run(test_langfuse_adapter())
