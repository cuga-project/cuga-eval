"""setup_agent_with_tools must fail fast on an empty toolbox when require_tools=True.

A zero-tool AppWorld run means the registry never reached the app API server
(startup race, issue #148); running anyway burns the whole eval on an agent
that cannot act. Default (require_tools=False) keeps the old permissive
behavior for benchmarks that may legitimately run with no tools.
"""

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.sanity


def _mock_provider(tools):
    provider = AsyncMock()
    provider.initialize = AsyncMock()
    provider.get_all_tools = AsyncMock(return_value=tools)
    return provider


@pytest.mark.asyncio
async def test_zero_tools_with_require_tools_raises():
    from benchmarks.helpers import sdk_eval_helpers

    with patch.object(sdk_eval_helpers, "CombinedToolProvider", return_value=_mock_provider([])):
        with pytest.raises(RuntimeError, match="0 tools"):
            await sdk_eval_helpers.setup_agent_with_tools(require_tools=True)


@pytest.mark.asyncio
async def test_zero_tools_without_require_tools_does_not_raise_early():
    """Default stays permissive: the zero-tool guard must not fire when opted out."""
    from benchmarks.helpers import sdk_eval_helpers

    with patch.object(sdk_eval_helpers, "CombinedToolProvider", return_value=_mock_provider([])):
        # Later setup stages (langfuse, agent construction) are irrelevant here —
        # stub them so the test pins ONLY the guard behavior.
        with (
            patch.object(sdk_eval_helpers, "setup_langfuse", return_value=None),
            patch.object(sdk_eval_helpers, "CugaAgent") as agent_cls,
        ):
            agent_cls.return_value.initialize = AsyncMock()
            try:
                await sdk_eval_helpers.setup_agent_with_tools(require_tools=False)
            except RuntimeError as e:
                if "0 tools" in str(e):
                    pytest.fail("guard fired despite require_tools=False")
                # any other RuntimeError from deeper setup is out of scope
