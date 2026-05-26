"""Token usage tracking callback for LangChain/LangGraph agents."""


class TokenUsageCallback:
    """Resettable callback that accumulates LLM token usage per task.

    Attach once at agent creation via extra_callbacks; call reset() before each
    task so counts reflect only that task's invoke.
    """

    def __init__(self):
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self._handler = None

    def _ensure_handler(self):
        if self._handler is not None:
            return self._handler
        from langchain_core.callbacks import BaseCallbackHandler

        outer = self

        class _Inner(BaseCallbackHandler):
            def on_llm_end(self, response, **kwargs):
                if not response.llm_output:
                    return
                out = response.llm_output
                usage = out.get("usage", {}) or {}
                outer.input_tokens += usage.get("input_tokens", 0)
                outer.output_tokens += usage.get("output_tokens", 0)
                token_usage = out.get("token_usage", {}) or {}
                outer.input_tokens += token_usage.get("prompt_tokens", 0)
                outer.output_tokens += token_usage.get("completion_tokens", 0)

        self._handler = _Inner()
        return self._handler

    def __getattr__(self, name: str):
        return getattr(self._ensure_handler(), name)

    def reset(self):
        self.input_tokens = 0
        self.output_tokens = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
