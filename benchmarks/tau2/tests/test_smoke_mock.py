"""End-to-end smoke test: one `mock` task through CUGA + the bridge + τ².

PLACEHOLDER (Phase 5). Not implemented yet; marker so the file exists in the
layout. See TAU2_CUGA_EVAL_PLAN.md Phase 5 / §6.

When implemented: run `--subset mock --num-tasks 1`; assert a reward in [0, 1]
and no thread left alive. Mock the user sim if possible to keep LLMs out of CI.
"""

import pytest

pytestmark = pytest.mark.regression


@pytest.mark.skip(reason="end-to-end mock smoke implemented in Phase 5 (see plan §6)")
def test_smoke_mock_one_task():
    raise NotImplementedError
