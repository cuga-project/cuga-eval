"""Test-time defaults for the m3 package.

Importing ``m3_vakra_score`` pulls in ``benchmarks.m3.evaluator`` which
instantiates Vakra's CorrectnessJudge at class-definition time. That
constructor raises ``ValueError("API_KEY is required")`` when no API key
is configured. Tests that exercise pure-Python helpers (no real LLM
calls) shouldn't have to provision a real key, so we set a placeholder
before any m3 module is imported.
"""

import os
import sys
from pathlib import Path

# When pytest is invoked with a single m3 test path (e.g. pytest
# benchmarks/m3/tests/test_foo.py), the project root isn't on sys.path,
# so `from benchmarks.helpers...` imports fail. The bpo conftest does the
# same thing — mirror it here so m3 tests are runnable in isolation.
_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

os.environ.setdefault("API_KEY", "test-key-not-used")  # noqa: S105
