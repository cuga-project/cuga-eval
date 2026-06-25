"""
LLM Judge scaffold for semantic similarity evaluation.

Provides an abstract interface for LLM-based judging of agent outputs.

The LLM judge can evaluate semantic equivalence between predicted
and expected outputs, accounting for paraphrasing and different
phrasings of the same answer.
"""

import asyncio
import json
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

try:
    import requests
except ImportError:
    requests = None


class LLMJudge(ABC):
    """
    Abstract interface for LLM-based similarity judging.

    LLM judges evaluate whether an agent's output is semantically
    equivalent to the expected output, even if worded differently.
    """

    @abstractmethod
    async def judge(
        self,
        predicted: str,
        expected: str,
        task_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Judge similarity between predicted and expected outputs.

        Args:
            predicted: The agent's output text.
            expected: The expected/ground truth output.
            task_context: Additional context about the task (utterance, etc.)

        Returns:
            Dict containing:
                - score: float between 0 and 1
                - rationale: str explaining the score
                - metadata: Optional additional info
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this judge implementation."""
        pass


class NotConfiguredJudge(LLMJudge):
    """
    Placeholder judge that raises error when called.

    Used when no LLM judge is configured, to provide clear error messages.
    """

    async def judge(
        self,
        predicted: str,
        expected: str,
        task_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Raise NotImplementedError with helpful message."""
        raise NotImplementedError(
            "LLM judge not configured. "
            "To use LLM-based judging, implement an LLMJudge subclass "
            "or configure a judge provider."
        )

    @property
    def name(self) -> str:
        """Return placeholder name."""
        return "not_configured"


class MockJudge(LLMJudge):
    """
    Mock judge for testing purposes.

    Returns a fixed score based on exact match for testing the judge interface.
    """

    async def judge(
        self,
        predicted: str,
        expected: str,
        task_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return mock judgment based on simple comparison."""
        # Simple heuristic for testing
        predicted_lower = predicted.lower().strip()
        expected_lower = expected.lower().strip()

        if predicted_lower == expected_lower:
            score = 1.0
            rationale = "Exact match"
        elif expected_lower in predicted_lower:
            score = 0.8
            rationale = "Expected output found within prediction"
        else:
            # Count common words
            pred_words = set(predicted_lower.split())
            exp_words = set(expected_lower.split())
            common = len(pred_words & exp_words)
            total = len(exp_words)
            score = common / total if total > 0 else 0.0
            rationale = f"Word overlap: {common}/{total}"

        return {
            "score": score,
            "rationale": rationale,
            "metadata": {"judge": "mock"},
        }

    @property
    def name(self) -> str:
        """Return mock judge name."""
        return "mock"


QWEN_GRADER_MODEL = "qwen3.7-max"
OPENROUTER_QWEN_GRADER_MODEL = "qwen/qwen3.7-max"
ALLOWED_GRADER_MODELS = {QWEN_GRADER_MODEL, OPENROUTER_QWEN_GRADER_MODEL}
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _normalize_chat_base_url(base_url: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith("/v1"):
        return value
    if value.endswith("/compatible-mode") or value.endswith("/api"):
        return value + "/v1"
    return value


class QwenJudge(LLMJudge):
    """
    Qwen3.7 Max semantic judge using an OpenAI-compatible chat endpoint.

    Requires:
      - QWEN_API_KEY, OPENROUTER_API_KEY, or LLM_JUDGE_API_KEY
    Optional:
      - LLM_JUDGE_MODEL (qwen3.7-max or qwen/qwen3.7-max)
      - LLM_JUDGE_BASE_URL, QWEN_BASE_URL, or OPENROUTER_BASE_URL
    """

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_s: int = 30,
    ) -> None:
        self._model = model or os.getenv("LLM_JUDGE_MODEL")
        if not self._model:
            self._model = (
                OPENROUTER_QWEN_GRADER_MODEL
                if os.getenv("OPENROUTER_API_KEY") and not os.getenv("QWEN_API_KEY")
                else QWEN_GRADER_MODEL
            )
        if self._model not in ALLOWED_GRADER_MODELS:
            allowed = ", ".join(sorted(ALLOWED_GRADER_MODELS))
            raise ValueError(f"LLM judge model must be Qwen3.7 Max ({allowed}), got {self._model!r}")
        self._api_key = api_key or os.getenv("LLM_JUDGE_API_KEY")
        if not self._api_key:
            self._api_key = (
                os.getenv("OPENROUTER_API_KEY")
                if self._model == OPENROUTER_QWEN_GRADER_MODEL
                else os.getenv("QWEN_API_KEY")
            )
        if not self._api_key:
            raise ValueError("QWEN_API_KEY, OPENROUTER_API_KEY, or LLM_JUDGE_API_KEY is required for QwenJudge")

        explicit_base_url = base_url or os.getenv("LLM_JUDGE_BASE_URL")
        if explicit_base_url:
            resolved_base_url = explicit_base_url
        elif self._model == OPENROUTER_QWEN_GRADER_MODEL:
            resolved_base_url = os.getenv("OPENROUTER_BASE_URL") or OPENROUTER_BASE_URL
        else:
            resolved_base_url = os.getenv("QWEN_BASE_URL") or QWEN_BASE_URL
        self._base_url = _normalize_chat_base_url(resolved_base_url)
        self._timeout_s = timeout_s

    @property
    def name(self) -> str:
        return f"qwen:{self._model}"

    async def judge(
        self,
        predicted: str,
        expected: str,
        task_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        # Keep payload small and stable for cost/speed.
        utterance = str(task_context.get("utterance", ""))[:500]
        predicted = str(predicted)[:2000]
        expected = str(expected)[:2000]

        system = (
            "You are an evaluation judge assessing semantic equivalence between a PREDICTED and EXPECTED answer.\n\n"
            "Scoring Guidelines:\n"
            "- Score 1.0: Semantically identical - same meaning, entities, and facts (minor wording differences OK)\n"
            "- Score 0.8-0.9: Semantically equivalent - same core meaning with slight elaboration or different phrasing\n"
            "- Score 0.5-0.7: Partially equivalent - same topic but missing key details or extra information\n"
            "- Score 0.2-0.4: Somewhat related - addresses same question but with different focus or incomplete answer\n"
            "- Score 0.0-0.1: Unrelated or contradictory - different facts, wrong information, or completely different meaning\n\n"
            "CRITICAL SEMANTIC EQUIVALENCE RULES:\n"
            "1. FOCUS ON MEANING, NOT EXACT WORDING:\n"
            "   - 'Insufficient data to determine' ≈ 'Need requisition ID' ≈ 'Cannot answer without more information'\n"
            "   - 'Unable to provide' ≈ 'Cannot determine' ≈ 'Insufficient data'\n"
            "   - All express the same semantic concept: missing required information\n\n"
            "2. REQUESTING MISSING INFORMATION:\n"
            "   - If EXPECTED asks for requisition ID, and PREDICTED says 'insufficient data' or 'cannot determine', score 0.85-0.95\n"
            "   - Both convey: 'I need more information to answer'\n"
            "   - Only score lower if PREDICTED provides wrong information instead of acknowledging missing data\n\n"
            "3. CONTEXT MATTERS:\n"
            "   - Consider the UTTERANCE to understand what's being asked\n"
            "   - If question requires specific context (like requisition ID) and agent acknowledges this, that's correct\n\n"
            "4. PRECISION IN SCORING:\n"
            "   - Don't score 0.0 unless answers are truly unrelated or contradictory\n"
            "   - Score 0.0 only when PREDICTED provides factually wrong information or completely different answer\n"
            "   - If PREDICTED is on the right track but incomplete, score 0.3-0.7 based on completeness\n\n"
            "5. FORMATTING DOESN'T MATTER:\n"
            "   - Focus on semantic content, not presentation\n"
            "   - 'CyberSec Jobs with 67%' = 'CyberSec Jobs: 67%' = 'The source is CyberSec Jobs (67%)'\n\n"
            "Return ONLY valid JSON: {\"score\": <number 0.0-1.0>, \"rationale\": \"<explanation>\"}\n"
        )

        user = f"UTTERANCE:\n{utterance}\n\nEXPECTED:\n{expected}\n\nPREDICTED:\n{predicted}\n"

        payload = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        def _do_request() -> Dict[str, Any]:
            url = f"{self._base_url}/chat/completions"

            if requests is not None:
                # Prefer requests library (more reliable, better error handling)
                response = requests.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self._timeout_s,
                )
                response.raise_for_status()
                return response.json()
            else:
                # Fallback to urllib (requires User-Agent for some APIs)
                import urllib.request

                req = urllib.request.Request(  # noqa: S310 — URL is a configured LLM endpoint, not user input
                    url=url,
                    method="POST",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "bpo-benchmark/1.0",
                    },
                )
                with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:  # noqa: S310  # nosec B310 — same controlled URL
                    raw = resp.read().decode("utf-8")
                return json.loads(raw)

        data = await asyncio.to_thread(_do_request)

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Strict parse; tolerate surrounding text by extracting first JSON object.
        parsed: Dict[str, Any]
        try:
            parsed = json.loads(content)
        except Exception:
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise ValueError(f"QwenJudge returned non-JSON: {content[:200]!r}")
            parsed = json.loads(content[start : end + 1])

        score = float(parsed.get("score", 0.0))
        score = max(0.0, min(1.0, score))
        rationale = str(parsed.get("rationale", ""))[:1000]

        return {
            "score": score,
            "rationale": rationale,
            "metadata": {
                "judge": "qwen",
                "model": self._model,
            },
        }


class GroqJudge(QwenJudge):
    """Deprecated compatibility alias. Configure provider `qwen` instead."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise ValueError("GroqJudge is retired for task judging. Use provider 'qwen' with Qwen3.7 Max.")


def get_llm_judge(provider: Optional[str] = None, **kwargs: Any) -> LLMJudge:
    """
    Get an LLM judge instance.

    Args:
        provider: Name of the judge provider. Options:
            - None: Returns NotConfiguredJudge
            - "mock": Returns MockJudge for testing
            - "qwen": Returns QwenJudge for Qwen3.7 Max

    Returns:
        LLMJudge instance

    Raises:
        ValueError: If provider is unknown
    """
    if provider is None:
        return NotConfiguredJudge()

    if provider == "mock":
        return MockJudge()

    if provider == "qwen":
        return QwenJudge(**kwargs)
    if provider == "groq":
        raise ValueError("Provider 'groq' is retired for task judging. Use provider 'qwen'.")

    raise ValueError(f"Unknown LLM judge provider: {provider}. Available providers: mock, qwen")


async def judge_output(
    predicted: str,
    expected: str,
    task_context: Dict[str, Any],
    judge: Optional[LLMJudge] = None,
) -> Optional[Dict[str, Any]]:
    """
    Convenience function to judge an output.

    Args:
        predicted: Agent's output
        expected: Expected output
        task_context: Task context
        judge: LLMJudge instance (if None, returns None)

    Returns:
        Judge result dict or None if no judge configured
    """
    if judge is None:
        return None

    try:
        return await judge.judge(predicted, expected, task_context)
    except NotImplementedError:
        return None
