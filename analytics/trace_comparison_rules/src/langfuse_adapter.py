"""
Langfuse trace format adapter.

This adapter converts Langfuse log files to the Internal Representation (IR).
"""

import json
import os
import sys
from datetime import datetime
from typing import Any, Optional

import output_extraction
from dotenv import load_dotenv
from trace_adapter import TraceAdapter, TraceAdapterFactory
from trace_ir import TraceIR, TraceStep

load_dotenv()

_script_dir = os.path.dirname(os.path.abspath(__file__))
_utils_dir = os.path.normpath(os.path.join(_script_dir, "..", "utils"))
if _utils_dir not in sys.path:
    sys.path.insert(0, _utils_dir)

from trace_utils import get_agent_name_from_prompt


class LangfuseAdapter(TraceAdapter):
    """
    Adapter for converting Langfuse trace logs to Internal Representation.
    """

    def __init__(
        self,
        agent_prompts: Optional[dict[str, str]] = None,
        extraction_functions: Optional[dict[str, str]] = None,
    ):
        """
        Initialize the Langfuse adapter.

        Args:
            agent_prompts: Optional dictionary mapping agent names to
                          system prompts
            extraction_functions: Optional dict mapping agent names to
                                extraction function names
        """
        self.agent_prompts = agent_prompts or {}
        self.extraction_functions = extraction_functions or {}

    def get_format_name(self) -> str:
        """Get the format name."""
        return "langfuse"

    async def load_trace(self, file_path: str) -> TraceIR:
        """
        Load a Langfuse trace from a file and convert to IR.

        Args:
            file_path: Absolute path to the Langfuse trace JSON file.

        Returns:
            TraceIR: The trace in internal representation
        """
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Extract trace ID
        trace_id = data.get("id", os.path.basename(file_path).split(".")[0])

        # Create trace IR
        trace = TraceIR(trace_id=trace_id)

        # Extract task formulation from top-level input field
        trace.task_formulation = data.get("input", {}).get("intent")

        # Get observations list
        observations = data.get("observations", [])

        # Filter and sort GENERATION type observations by startTime
        generation_observations = [obs for obs in observations if obs.get("type") == "GENERATION"]
        generation_observations.sort(key=lambda x: x.get("startTime", ""))

        # Process each GENERATION observation
        step_number = 0

        for observation in generation_observations:
            # Extract system and user prompts from input
            system_prompt = None
            user_input = None
            llm_output = None

            # Get input field (should be a list of message objects)
            input_data = observation.get("input", [])
            if isinstance(input_data, list):
                # Find first system and user messages
                for message in input_data:
                    if isinstance(message, dict):
                        role = message.get("role")
                        content = message.get("content")

                        if role == "system" and system_prompt is None:
                            system_prompt = content
                        elif role == "user" and user_input is None:
                            user_input = content

            # Extract LLM output from output field
            output_data = observation.get("output")
            if isinstance(output_data, dict):
                # Look for assistant role in output
                if output_data.get("role") == "assistant":
                    llm_output = output_data.get("content")

            metadata = observation.get("metadata", {})

            # Determine agent name by matching system prompt, fall back to metadata
            agent_name = None
            if self.agent_prompts and system_prompt:
                agent_name = get_agent_name_from_prompt(self.agent_prompts, system_prompt)
            if agent_name is None:
                agent_name = metadata.get("langgraph_node", observation.get("name", "Unknown"))

            # Parse structured output
            llm_structured = self._parse_llm_output(llm_output, agent_name)

            # Parse timestamps
            start_time = self._parse_timestamp(observation.get("startTime"))
            end_time = self._parse_timestamp(observation.get("endTime"))

            # Create trace step
            step = TraceStep(
                step_number=step_number,
                agent_name=agent_name,
                system_prompt=system_prompt,
                user_input=user_input,
                llm_output_raw=llm_output,
                llm_output_structured=llm_structured,
                start_time=start_time,
                end_time=end_time,
                metadata={
                    "observation_id": observation.get("id"),
                    "observation_name": observation.get("name"),
                    "model": observation.get("model"),
                    "langgraph_node": metadata.get("langgraph_node"),
                    "langgraph_step": metadata.get("langgraph_step"),
                },
            )

            trace.add_step(step)
            step_number += 1

        return trace

    def _parse_llm_output(self, llm_output: Optional[str], agent_name: str) -> dict[str, Any]:
        """
        Parse LLM output into structured format.

        Args:
            llm_output: Raw LLM output string
            agent_name: Name of the agent

        Returns:
            dict: Structured output
        """
        if not llm_output:
            return {}

        try:
            # Try to parse as JSON
            llm_structured = json.loads(llm_output)
            return llm_structured

        except Exception as e:
            print(f"LLM output for {agent_name} is not valid JSON: {e}")

            # Try extraction function if available
            if agent_name in self.extraction_functions:
                func_name = self.extraction_functions[agent_name]
                parsing_function = getattr(output_extraction, func_name)

                try:
                    return parsing_function(llm_output)
                except Exception as e2:
                    print(f"Parsing function for {agent_name} failed: {e2}")

            return {}

    def _parse_timestamp(self, timestamp_str: Optional[str]) -> Optional[datetime]:
        """
        Parse ISO 8601 timestamp string to datetime object.

        Args:
            timestamp_str: ISO 8601 timestamp string

        Returns:
            datetime object or None
        """
        if not timestamp_str:
            return None

        try:
            # Parse ISO 8601 format
            return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except Exception as e:
            print(f"Failed to parse timestamp {timestamp_str}: {e}")
            return None


# Register the adapter
TraceAdapterFactory.register_adapter("langfuse", LangfuseAdapter)
