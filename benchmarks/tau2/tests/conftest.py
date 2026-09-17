"""Pytest configuration for tau2 benchmark tests.

When pytest is invoked with a single tau2 test path (e.g. pytest
benchmarks/tau2/tests/test_config_load.py), the project root isn't on sys.path,
so `from config_loader import ...` / `import benchmarks.tau2...` fail. The bpo and
m3 conftests do the same thing — mirror it here so tau2 tests run in isolation.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
