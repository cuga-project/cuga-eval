"""TokenUsageTracker-like callback for SDK mode to capture LLM prompts and responses.

This module provides a LangChain callback handler that mimics the behavior of
TokenUsageTracker from cuga-agent, enabling SDK mode (CugaAgent) to produce
trajectory files with the same prompt richness as AgentRunner mode.

Related issues:
- cuga-internal-evaluation#37: Standardize CUGA invocation mode across benchmarks
- cuga-agent#71: Instrument CugaAgent SDK with TokenUsageTracker
"""

from typing import Any, Dict, List, Optional

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult
from loguru import logger


class SDKTokenUsageTrackerCallback(AsyncCallbackHandler):
    """LangChain callback handler that captures prompts and responses for ActivityTracker.

    This callback mimics the behavior of TokenUsageTracker from cuga-agent's agent_loop.py,
    enabling SDK mode to produce rich trajectory files with full LLM conversation history.

    The callback captures:
    - on_llm_start: System and user prompts
    - on_llm_end: Assistant responses
    - on_llm_error: Error information

    All captured data is forwarded to ActivityTracker via collect_prompt() and collect_step().
    """

    def __init__(self, tracker: Any):
        """Initialize the callback with an ActivityTracker instance.

        Args:
            tracker: ActivityTracker instance to collect prompts and steps
        """
        super().__init__()
        self.tracker = tracker
        self._call_count = 0
        logger.debug("SDKTokenUsageTrackerCallback initialized")

    async def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: Any,
        parent_run_id: Optional[Any] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Capture prompts when LLM call starts.

        This method extracts system and user messages from the prompts and
        forwards them to ActivityTracker.collect_prompt().
        """
        self._call_count += 1
        logger.debug(f"[SDKTokenUsageTracker] LLM call #{self._call_count} started")

        # Extract messages from kwargs if available (LangChain passes messages here)
        messages = kwargs.get("invocation_params", {}).get("messages", [])
        if not messages and "messages" in kwargs:
            messages = kwargs["messages"]

        # If we have structured messages, extract them
        if messages:
            for msg in messages:
                if isinstance(msg, BaseMessage):
                    role = msg.type if hasattr(msg, 'type') else 'unknown'
                    content = msg.content if hasattr(msg, 'content') else str(msg)

                    # Map LangChain message types to standard roles
                    if role == 'system':
                        self.tracker.collect_prompt(role="system", value=content)
                        logger.debug(f"[SDKTokenUsageTracker] Captured system prompt ({len(content)} chars)")
                    elif role == 'human':
                        self.tracker.collect_prompt(role="user", value=content)
                        logger.debug(f"[SDKTokenUsageTracker] Captured user prompt ({len(content)} chars)")
                    elif role == 'ai':
                        # Sometimes previous AI messages are included in context
                        self.tracker.collect_prompt(role="assistant", value=content)
                        logger.debug(
                            f"[SDKTokenUsageTracker] Captured assistant context ({len(content)} chars)"
                        )
                elif isinstance(msg, dict):
                    # Handle dict-style messages
                    role = msg.get('role', msg.get('type', 'unknown'))
                    content = msg.get('content', str(msg))

                    if role in ['system', 'user', 'assistant']:
                        self.tracker.collect_prompt(role=role, value=content)
                        logger.debug(f"[SDKTokenUsageTracker] Captured {role} prompt ({len(content)} chars)")

        # Fallback: if no structured messages, try to parse prompts list
        elif prompts:
            for prompt in prompts:
                # Simple heuristic: if prompt is very long, it likely contains system instructions
                if len(prompt) > 500:
                    self.tracker.collect_prompt(role="system", value=prompt)
                    logger.debug(f"[SDKTokenUsageTracker] Captured prompt as system ({len(prompt)} chars)")
                else:
                    self.tracker.collect_prompt(role="user", value=prompt)
                    logger.debug(f"[SDKTokenUsageTracker] Captured prompt as user ({len(prompt)} chars)")

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: Any,
        parent_run_id: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Capture assistant response when LLM call completes.

        This method extracts the generated text and forwards it to
        ActivityTracker.collect_prompt() as an assistant message.
        """
        logger.debug(f"[SDKTokenUsageTracker] LLM call #{self._call_count} completed")

        # Extract the generated text from the response
        if response.generations:
            for generation_list in response.generations:
                for generation in generation_list:
                    text = generation.text if hasattr(generation, 'text') else str(generation)
                    if text:
                        self.tracker.collect_prompt(role="assistant", value=text)
                        logger.debug(
                            f"[SDKTokenUsageTracker] Captured assistant response ({len(text)} chars)"
                        )

        # Also capture token usage if available
        if response.llm_output:
            token_usage = response.llm_output.get('token_usage', {})
            if token_usage:
                logger.debug(f"[SDKTokenUsageTracker] Token usage: {token_usage}")

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        parent_run_id: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Capture error information when LLM call fails."""
        logger.warning(f"[SDKTokenUsageTracker] LLM call #{self._call_count} failed: {error}")

        # Record error as a step
        from cuga.backend.activity_tracker.tracker import Step

        error_msg = f"LLM Error: {str(error)}"
        self.tracker.collect_step(Step(name="LLM_Error", data=error_msg))


def create_token_usage_tracker_callback(tracker: Any) -> SDKTokenUsageTrackerCallback:
    """Factory function to create a TokenUsageTracker-like callback.

    Args:
        tracker: ActivityTracker instance

    Returns:
        SDKTokenUsageTrackerCallback instance

    Example:
        >>> from cuga.backend.activity_tracker.tracker import ActivityTracker
        >>> tracker = ActivityTracker()
        >>> callback = create_token_usage_tracker_callback(tracker)
        >>> agent = CugaAgent(tool_provider=provider, callbacks=[langfuse_handler, callback])
    """
    return SDKTokenUsageTrackerCallback(tracker)


# Made with Bob
