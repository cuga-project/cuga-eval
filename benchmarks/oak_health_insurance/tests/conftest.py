"""Pytest configuration for Oak Health Insurance benchmark tests."""

import sys
from pathlib import Path

# Add project root to path so `from benchmarks.oak_health_insurance...` resolves.
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
