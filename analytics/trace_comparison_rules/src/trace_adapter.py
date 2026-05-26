"""
Base adapter interface for converting different trace formats to Internal Representation.

This module defines the abstract base class that all trace format adapters must implement.
"""

from abc import ABC, abstractmethod
from typing import Any

from trace_ir import TraceIR


class TraceAdapter(ABC):
    """
    Abstract base class for trace format adapters.

    Each adapter is responsible for converting a specific log format
    (e.g., AgentOps, Langfuse) into the common Internal Representation (IR).
    """

    @abstractmethod
    async def load_trace(self, file_name: str) -> TraceIR:
        """
        Load a trace from a file and convert it to IR.

        Args:
            file_name: Path to the trace log file

        Returns:
            TraceIR: The trace in internal representation format

        Raises:
            FileNotFoundError: If the file doesn't exist
            ValueError: If the file format is invalid
        """
        pass

    @abstractmethod
    def get_format_name(self) -> str:
        """
        Get the name of the trace format this adapter handles.

        Returns:
            str: Format name (e.g., "agentops", "langfuse")
        """
        pass

    def validate_trace(self, trace: TraceIR) -> bool:
        """
        Validate that a trace IR is well-formed.

        Args:
            trace: The trace to validate

        Returns:
            bool: True if valid, False otherwise
        """
        if not trace.trace_id:
            return False
        if not trace.steps:
            return False
        if len(trace.steps) != len(trace.agent_sequence):
            return False
        return True


class TraceAdapterFactory:
    """
    Factory for creating trace adapters based on format type.
    """

    _adapters: dict[str, type[TraceAdapter]] = {}

    @classmethod
    def register_adapter(cls, format_name: str, adapter_class: type[TraceAdapter]) -> None:
        """
        Register a new adapter for a specific format.

        Args:
            format_name: Name of the format (e.g., "agentops")
            adapter_class: The adapter class to register
        """
        cls._adapters[format_name] = adapter_class

    @classmethod
    def create_adapter(cls, format_name: str, **kwargs: Any) -> TraceAdapter:
        """
        Create an adapter instance for the specified format.

        Args:
            format_name: Name of the format
            **kwargs: Additional arguments to pass to the adapter constructor

        Returns:
            TraceAdapter: An instance of the appropriate adapter

        Raises:
            ValueError: If the format is not registered
        """
        if format_name not in cls._adapters:
            raise ValueError(
                f"Unknown trace format: {format_name}. Available formats: {list(cls._adapters.keys())}"
            )
        return cls._adapters[format_name](**kwargs)

    @classmethod
    def get_available_formats(cls) -> list[str]:
        """
        Get a list of all registered trace formats.

        Returns:
            list[str]: List of format names
        """
        return list(cls._adapters.keys())
