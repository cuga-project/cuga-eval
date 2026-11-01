"""Test-time defaults for the m3 package.

Importing ``m3_vakra_score`` pulls in ``benchmarks.m3.evaluator`` (a bridge to
vendor/vakra's evaluator — see that module's docstring), whose ``CapabilityPolicy``
instantiates every judge at class-definition time. The judge LLM backend defaults
to this org's LiteLLM proxy (``JUDGE_BACKEND=litellm``, the bridge's own default),
which raises ``ValueError`` if ``OPENAI_BASE_URL``/``OPENAI_API_KEY`` aren't set;
vendor's own Groq/RITS backends raise similarly on their own env vars. Tests that
exercise pure-Python helpers (no real LLM calls) shouldn't have to provision real
credentials, so placeholders for all of them are set before any m3 module is
imported.
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

# `pytest.importorskip("evaluator")` (used by every test that needs the Vakra
# evaluator present) can only succeed if benchmarks/m3/evaluator is itself on
# sys.path at collection time — nothing else adds it that early. Without this,
# those tests always skip regardless of whether vendor/vakra is cloned.
_eval_dir = Path(__file__).resolve().parents[1] / "evaluator"
if str(_eval_dir) not in sys.path:
    sys.path.insert(0, str(_eval_dir))

os.environ.setdefault("API_KEY", "test-key-not-used")  # noqa: S105 — vendor's Groq backend
os.environ.setdefault("RITS_API_KEY", "test-key-not-used")  # noqa: S105 — vendor's RITS backend
os.environ.setdefault("OPENAI_BASE_URL", "https://example.invalid")  # bridge's litellm default
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")  # noqa: S105
