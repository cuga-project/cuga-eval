"""Configurable VAKRA adapter for CUGA — "configured CUGA, never bare main".

Layers the benchmark-validated VAKRA behaviors on an unmodified ``CugaAgent``
through public SDK surfaces only. See ``benchmarks/m3/ADAPTER.md`` for the
preset table, every knob, and provenance. Default preset ``off`` = the eval's
current behavior, byte-identical.

Import note: only ``agent.py`` touches ``cuga`` (lazily); config, instruction
composition, answer functions and guards are importable and testable without a
configured CUGA environment.
"""

from benchmarks.m3.adapter.config import (
    PRESETS,
    AdapterConfig,
    TaskContext,
    resolve_adapter_config,
)

__all__ = [
    "AdapterConfig",
    "PRESETS",
    "TaskContext",
    "resolve_adapter_config",
    "build_m3_agent",
    "wrap_existing_agent",
]


def __getattr__(name: str):
    # Lazy re-exports: keep `from benchmarks.m3.adapter import resolve_adapter_config`
    # cuga-free while still offering the factories from the package root.
    if name in ("build_m3_agent", "wrap_existing_agent"):
        from benchmarks.m3.adapter import agent as _agent

        return getattr(_agent, name)
    raise AttributeError(name)
