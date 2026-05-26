"""
Internal Representation (IR) for trace data.

This module defines the internal data structures used to represent traces
in a format-agnostic way. Different log formats (AgentOps, Langfuse, etc.)
will be converted to this IR via adapters.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class TraceStep:
    """
    Represents a single step in a trace execution.

    A step typically corresponds to an agent invocation or LLM call.
    """

    step_number: int
    agent_name: str
    system_prompt: Optional[str] = None
    user_input: Optional[str] = None
    llm_output_raw: Optional[str] = None
    llm_output_structured: Optional[dict[str, Any]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure llm_output_structured is a dict if None."""
        if self.llm_output_structured is None:
            self.llm_output_structured = {}


@dataclass
class TraceIR:
    """
    Internal Representation of a complete trace.

    Contains all steps and metadata for a single trace execution.
    """

    trace_id: str
    task_formulation: Optional[str] = None
    steps: list[TraceStep] = field(default_factory=list)
    agent_sequence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: TraceStep) -> None:
        """Add a step to the trace."""
        self.steps.append(step)
        self.agent_sequence.append(step.agent_name)

    def get_step(self, step_number: int) -> Optional[TraceStep]:
        """Get a step by its number (0-indexed)."""
        if 0 <= step_number < len(self.steps):
            return self.steps[step_number]
        return None

    def get_steps_by_agent(self, agent_name: str) -> list[TraceStep]:
        """Get all steps for a specific agent."""
        return [step for step in self.steps if step.agent_name == agent_name]

    @property
    def num_steps(self) -> int:
        """Get the total number of steps in the trace."""
        return len(self.steps)
