"""Pytest configuration and fixtures for BPO benchmark tests."""

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


def to_dict(obj):
    """Convert Pydantic model or dict to dict."""
    if hasattr(obj, 'model_dump'):
        return obj.model_dump()
    elif hasattr(obj, 'dict'):
        return obj.dict()
    return obj
