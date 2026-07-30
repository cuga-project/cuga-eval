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
async def test_zero_tools_without_require_tools_completes():
    """Default stays permissive: with zero tools and require_tools unset, setup must
    run to completion and return the constructed agent and langfuse handler."""
    from benchmarks.helpers import sdk_eval_helpers

    provider = _mock_provider([])
    with (
        patch.object(sdk_eval_helpers, "CombinedToolProvider", return_value=provider),
        patch.object(sdk_eval_helpers, "setup_langfuse", return_value=None),
        patch.object(sdk_eval_helpers, "CugaAgent") as agent_cls,
    ):
        agent, handler = await sdk_eval_helpers.setup_agent_with_tools(require_tools=False)

    assert agent is agent_cls.return_value
    assert handler is None
    agent_cls.assert_called_once_with(tool_provider=provider)


@pytest.mark.asyncio
async def test_react_zero_tools_with_require_tools_raises():
    """AppWorld's --agent react/codeact paths go through the ReAct helper, so the
    same guard must apply there (issue #148 review)."""
    from benchmarks.helpers import react_agent

    with patch.object(react_agent, "CombinedToolProvider", return_value=_mock_provider([])):
        with pytest.raises(RuntimeError, match="0 tools"):
            await react_agent.setup_react_agent_with_tools(require_tools=True)


@pytest.mark.asyncio
async def test_react_for_evaluation_forwards_require_tools():
    """The sdk_eval_helpers wrapper used by the AppWorld evaluators must forward the flag."""
    from benchmarks.helpers import sdk_eval_helpers

    with patch.object(
        sdk_eval_helpers, "setup_react_agent_with_tools", new=AsyncMock(return_value=(None, None))
    ) as inner:
        await sdk_eval_helpers.setup_react_agent_for_evaluation(require_tools=True)

    assert inner.await_args.kwargs["require_tools"] is True
