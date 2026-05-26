"""Test-time defaults for the m3 package.

Importing ``m3_vakra_score`` pulls in ``benchmarks.m3.evaluator`` which
instantiates Vakra's CorrectnessJudge at class-definition time. That
constructor raises ``ValueError("API_KEY is required")`` when no API key
is configured. Tests that exercise pure-Python helpers (no real LLM
calls) shouldn't have to provision a real key, so we set a placeholder
before any m3 module is imported.
"""

import os

os.environ.setdefault("API_KEY", "test-key-not-used")  # noqa: S105
