from __future__ import annotations

import json
import os
import re
from typing import Any, List, Optional

from constant import N_TOOL_CALLS_PER_TURN
from langchain_openai import ChatOpenAI
from prompt import CorrectnessPrompt, GroundednessPrompt
from utils import JudgeInput, JudgeOutput

_LABEL_RE = re.compile(r"\b(yes|partial|no|unsure)\b", re.IGNORECASE)
_CONCLUSION_RE = re.compile(r"<conclusion>\s*(.*?)\s*</conclusion>", re.IGNORECASE | re.DOTALL)

_SCORE_MAP = {"yes": 1.0, "partial": 0.0, "no": 0.0, "unsure": 0.0}


class JudgeOutputParseError(ValueError):
    pass


class JudgeValidationError(ValueError):
    """Raised when a judge returns an unexpected/invalid score."""

    pass


class ChatModel(ChatOpenAI):
    """
    openai/gpt-oss-120b chat model is being used as LLM-as-a-judge using langchain-openai.
    Groq-backed OpenAI-compatible chat model.
    """

    def __init__(self, config: dict):
        # Set model with model or model_name
        model_name = config.get("model_name", "openai/gpt-oss-120b")
        end_point = config.get("end_point", "https://api.groq.com/openai")

        api_key = os.getenv("API_KEY")
        if api_key is None or api_key == "":
            raise ValueError("API_KEY is required")

        params = config.get("params", {})

        # Set default values for overriding fields
        config = {}
        config.setdefault("model", model_name)
        config.setdefault("api_key", api_key)
        config.setdefault("base_url", end_point.rstrip("/") + "/v1")
        config.setdefault("temperature", 0)

        config.update(params)

        super().__init__(**config)


class ChatRits(ChatOpenAI):
    """RITS chat model integration using langchain-openai."""

    def __init__(self, config: dict):
        model_name = config.get("model_name", "openai/gpt-oss-120b")
        end_point = config.get(
            "end_point",
            "https://inference-3scale-apicast-production.apps.rits.fmaas.res.ibm.com/gpt-oss-120b",
        )
        rits_api_key = os.getenv("RITS_API_KEY")
        if rits_api_key is None or rits_api_key == "":
            raise ValueError("RITS_API_KEY is required")

        params = config.get("params", {})
        rits_config = {}
        rits_config.setdefault("model_name", model_name)
        rits_config.setdefault("api_key", "/")
        rits_config.setdefault("default_headers", {"RITS_API_KEY": rits_api_key})
        rits_config.setdefault("base_url", end_point.rstrip("/") + "/v1")
        rits_config.update(params)

        super().__init__(**rits_config)


class LiteLLMChatModel(ChatOpenAI):
    """
    Azure/gpt-4.1 served through the IBM LiteLLM proxy, used as LLM-as-a-judge.

    Default judge backend (see ``_build_judge_llm``). The Groq ``ChatModel`` above
    is retained and still selectable via ``JUDGE_BACKEND=groq`` (or gpt-oss).
    Reads the same proxy env the agent's gpt4.1 profile uses: ``OPENAI_BASE_URL``
    + ``OPENAI_API_KEY``. Override the model with ``JUDGE_MODEL_NAME``.
    """

    def __init__(self, config: dict):
        model_name = config.get("model_name") or os.getenv("JUDGE_MODEL_NAME", "Azure/gpt-4.1")
        base_url = (
            config.get("end_point")
            or os.getenv("JUDGE_BASE_URL")
            or os.getenv("OPENAI_BASE_URL", "https://ete-litellm.bx.cloud9.ibm.com")
        )
        api_key = os.getenv("JUDGE_API_KEY") or os.getenv("OPENAI_API_KEY")
        if api_key is None or api_key == "":
            raise ValueError("OPENAI_API_KEY (or JUDGE_API_KEY) is required for the LiteLLM judge")

        params = config.get("params", {})

        # The LiteLLM proxy serves the OpenAI routes at the root, so use base_url
        # as-is (no "/v1" suffix) — matching the agent's gpt4.1 profile.
        cfg = {
            "model": model_name,
            "api_key": api_key,
            "base_url": base_url.rstrip("/"),
            "temperature": 0,
        }
        cfg.update(params)

        super().__init__(**cfg)


def _build_judge_llm(config: dict) -> ChatOpenAI:
    """Select the judge backend. Default ``litellm`` -> Azure/gpt-4.1 via the
    LiteLLM proxy; set ``JUDGE_BACKEND=groq`` (or gpt-oss) for the legacy
    Groq-backed gpt-oss-120b judge, or ``JUDGE_BACKEND=rits`` for RITS.
    An explicit ``config["backend"]`` wins."""
    backend = (config.get("backend") or os.getenv("JUDGE_BACKEND", "litellm")).strip().lower()
    if backend in ("groq", "gpt-oss", "gpt_oss", "oss"):
        return ChatModel(config)
    if backend == "rits":
        return ChatRits(config)
    if backend in ("litellm", "azure", ""):
        return LiteLLMChatModel(config)
    raise ValueError(
        f"Unknown judge backend {backend!r}. Set JUDGE_BACKEND (or config['backend']) to one of: "
        "'litellm'/'azure' (default, Azure/gpt-4.1 via the LiteLLM proxy) or "
        "'groq'/'gpt-oss' (legacy Groq gpt-oss-120b) or 'rits'."
    )


class LLMJudge:
    """
    Interface you implement with your provider (OpenAI, vLLM, etc).
    Must be deterministic as much as possible (temperature=0).
    """

    def __init__(self, config: dict = {}):
        self.model_config = config
        self.llm = _build_judge_llm(self.model_config)

    def invoke(self, prompt: str) -> str:
        res = self.llm.invoke(prompt).content
        return res

    def judge(self, inp: JudgeInput) -> JudgeOutput:
        raise NotImplementedError


class GroundednessJudge(LLMJudge):
    """
    Check if the predicted answer is grounded in the answers in the turn.
    """

    def __init__(self, config: dict = {}):
        # Allow overriding ONLY the groundedness judge model, independent of the
        # shared JUDGE_MODEL_NAME used by the correctness judge. Falls back to the
        # standard default in LiteLLMChatModel when unset.
        override = os.getenv("GROUNDEDNESS_JUDGE_MODEL_NAME")
        if override and not config.get("model_name"):
            config = {**config, "model_name": override}
        super().__init__(config)

    _ws = re.compile(r"\s+")

    def _norm(self, s: str) -> str:
        return self._ws.sub(" ", s.strip().lower())

    def judge(self, inp: JudgeInput) -> JudgeOutput:
        # Individual tool responses can be arbitrarily large (e.g. a broad
        # free-text retriever query returning many documents); the last 20 of
        # them concatenated uncapped has been observed to produce a prompt
        # north of 1M tokens, exceeding even a 1M+-token judge context window
        # (cuga-eval#143 / vakra#25). The bare except below then silently
        # turns that infra-level BadRequestError into a hard groundedness
        # FAIL, indistinguishable from a genuine ungrounded verdict. Cap
        # defensively in characters (not tokens) so this doesn't depend on a
        # tokenizer being available here, and stays correct across whichever
        # judge model JUDGE_MODEL_NAME/GROUNDEDNESS_JUDGE_MODEL_NAME resolves
        # to. Read fresh per call (not cached at class/import time) so an
        # in-process env var change — a pytest fixture, an A/B toggle — takes
        # effect immediately, matching this repo's convention elsewhere.
        max_input_chars = int(os.getenv("M3_GROUNDEDNESS_JUDGE_MAX_CHARS", "100000"))

        tr = " ".join(
            [self._norm(str(t)) for t in inp.pred_tool_responses[-N_TOOL_CALLS_PER_TURN:]]
        )  # Concatenate the "tool_responses". Only top 20 tool_responses considered.
        if len(tr) > max_input_chars:
            # Keep the tail: most recent tool responses are most relevant to
            # the final answer, and the truncation above already prioritizes
            # recency by taking the *last* N_TOOL_CALLS_PER_TURN responses.
            tr = tr[-max_input_chars:]
        tr = f"QUERY: {inp.query} {tr}"  # Add Query to the responses
        pr = self._norm(inp.pred_answer)
        if len(pr) > max_input_chars:
            pr = pr[:max_input_chars]

        prompt = GroundednessPrompt.format(doc=tr, response=pr)
        try:
            result = self.invoke(prompt)
            result_parsed = self._parse_response(result)
            return JudgeOutput(score=result_parsed["score"], explanation=result_parsed["explanation"])
        except Exception as e:
            return JudgeOutput(score=0.0, explanation=f"Judge Error {e}.")

    def _find_label_and_line(self, text: str) -> tuple[Optional[str], Optional[int]]:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        for i, ln in enumerate(lines[:10]):  # scan first few meaningful lines
            clean = re.sub(r"^\s*[-*•\d.)]+\s*", "", ln)
            m = _LABEL_RE.search(clean)
            if m:
                return m.group(1).lower(), i
        m = _LABEL_RE.search(text)
        return (m.group(1).lower(), None) if m else (None, None)

    def _parse_response(self, raw: str) -> dict:
        """
        Parse the judge output into:
        {"explanation": str, "score": int}

        Accepts:
        - Two-line format: "<label>\\n<explanation>"
        - Optional wrapping: <conclusion> ... </conclusion>
        - Extra text/bullets/prefixes like "Label: yes - ..."

        Returns:
        JudgeOutput(score, explanation)
        """
        if raw is None:
            raise JudgeOutputParseError("raw output is None")
        text = raw.strip()
        if not text:
            raise JudgeOutputParseError("empty output")

        # Prefer <conclusion>...</conclusion> content if present
        m = _CONCLUSION_RE.search(text)
        if m:
            text = m.group(1).strip()
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Find label (prefer early lines)
        label, line_idx = self._find_label_and_line(text)

        if label is None:
            raise JudgeOutputParseError("No label found (expected: yes/partial/no/unsure)")

        explanation = self._extract_explanation(text, label, line_idx).strip()

        return {"explanation": explanation.strip(), "score": _SCORE_MAP[label]}

    def _extract_explanation(self, text: str, label: str, line_idx: Optional[int]) -> str:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

        if line_idx is not None:
            # If same line contains text after the label, treat as explanation.
            ln = re.sub(r"^\s*[-*•\d.)]+\s*", "", lines[line_idx])
            parts = re.split(rf"\b{re.escape(label)}\b", ln, flags=re.IGNORECASE, maxsplit=1)
            if len(parts) == 2:
                tail = parts[1].lstrip(" :\-–—").strip()
                if tail:
                    return tail

            # Otherwise next line is explanation if present
            if line_idx + 1 < len(lines):
                return lines[line_idx + 1]

            return ""

        # Fallback: explanation is whatever comes after the first label occurrence (same line)
        m = _LABEL_RE.search(text)
        if not m:
            return ""
        tail = text[m.end() :].lstrip(" \t:;-–—\n").strip()
        return tail.split("\n", 1)[0].strip() if tail else ""


class CorrectnessJudge(LLMJudge):
    """
    Score the predicted answer as opposed to ground truth answer and query.
    """

    _ws = re.compile(r"\s+")

    def _norm(self, s: str) -> str:
        return self._ws.sub(" ", s.strip().lower())

    def _parse_response(self, raw: str) -> dict:
        """
        Parse the judge output into:
        {"explanation": str, "score": int}

        Accepts:
        - pure JSON output
        - JSON embedded in markdown or extra prose
        - score as 0/1, "0"/"1", true/false (coerced), or "yes"/"no" (coerced)
        """
        if raw is None:
            raise JudgeOutputParseError("raw output is None")

        text = raw.strip()
        if not text:
            raise JudgeOutputParseError("empty output")

        # 1) Try direct JSON parse
        obj = None
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2) Try extracting the first JSON object from surrounding text
        if obj is None:
            json_sub = self._find_first_json_object(text)
            if not json_sub:
                # Sometimes models wrap in ```json ... ```
                fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
                json_sub = fenced.group(1) if fenced else None

            if not json_sub:
                raise JudgeOutputParseError("could not find a JSON object in output")

            try:
                obj = json.loads(json_sub)
            except json.JSONDecodeError as e:
                raise JudgeOutputParseError(f"found JSON-like text but failed to parse: {e}") from e

        if not isinstance(obj, dict):
            raise JudgeOutputParseError(f"expected JSON object/dict, got {type(obj).__name__}")

        # 3) Normalize fields
        explanation = obj.get("explanation", "")
        score = obj.get("score", None)

        if explanation is None:
            explanation = ""
        if not isinstance(explanation, str):
            explanation = str(explanation)

        def coerce_score(v: Any) -> int:
            if isinstance(v, bool):
                return 1 if v else 0
            if isinstance(v, int):
                return 1 if v == 1 else 0
            if isinstance(v, float):
                return 1 if v == 1.0 else 0
            if isinstance(v, str):
                s = v.strip().lower()
                if s in {"1", "true", "yes", "y"}:
                    return 1
                if s in {"0", "false", "no", "n"}:
                    return 0
                # If they put "score: 1" in a string, try to extract.
                m = re.search(r"\b([01])\b", s)
                if m:
                    return int(m.group(1))
            raise JudgeOutputParseError(f"invalid score value: {v!r}")

        if score is None:
            raise JudgeOutputParseError("missing required field: 'score'")

        score_int = coerce_score(score)

        return {"explanation": explanation.strip(), "score": score_int}

    def _find_first_json_object(self, text: str) -> Optional[str]:
        """
        Returns the substring of the first top-level JSON object found in `text`,
        or None if none is found.

        This is robust to extra text before/after JSON and to braces inside strings.
        """
        start = text.find("{")
        if start == -1:
            return None

        in_str = False
        escape = False
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]

            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            else:
                if ch == '"':
                    in_str = True
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start : i + 1]

        return None

    def judge(self, inp: JudgeInput) -> JudgeOutput:
        query = self._norm(inp.query)
        gt = self._norm(inp.gt_answer)
        pr = self._norm(inp.pred_answer)
        if not gt and not pr:
            return JudgeOutput(score=1.0, explanation="Both empty.")
        prompt = CorrectnessPrompt.format(question=query, answer=gt, prediction=pr)
        try:
            result = self.invoke(prompt)
            result_parsed = self._parse_response(result)
            return JudgeOutput(score=result_parsed["score"], explanation=result_parsed["explanation"])
        except Exception as e:
            # Was `except Exception: ... "Judge Error {e}."` — no `as e` bound
            # and no f-string, so the actual exception was always discarded;
            # every infra/API failure here looked identical and undebuggable.
            return JudgeOutput(score=0.0, explanation=f"Judge Error {e}.")


class ExactMatchJudge(LLMJudge):
    """
    Ensures the tool_responses (tool_response) match exactly.

    This is deterministic and does NOT call an LLM.
    Intended use:
      - gt_answer: expected tool_response (string or list-like as string)
      - tool_responses: actual tool_response list from the run
    """

    _ws = re.compile(r"\s+")

    def _as_list_of_str(self, xs: Any) -> List[str]:
        if xs is None:
            return []
        if isinstance(xs, list):
            return ["" if x is None else str(x) for x in xs]
        return [str(xs)]

    def judge(self, inp: "JudgeInput") -> "JudgeOutput":
        actual = self._as_list_of_str(inp.pred_tool_responses)[-N_TOOL_CALLS_PER_TURN:]
        expected = self._as_list_of_str(inp.gt_tool_responses)

        actual_cmp = actual
        expected_cmp = expected

        # Check that every expected element appears in actual
        missing = [e for e in expected_cmp if e not in actual_cmp]

        if not missing:
            return JudgeOutput(score=1.0, explanation="All expected tool_responses are present in actual.")
        else:
            return JudgeOutput(
                score=0.0,
                explanation=(
                    f"Missing expected tool_responses.\nMissing: {missing}\n"
                    # f"Expected ({len(expected_cmp)}): {expected_cmp}\n"
                    # f"Actual   ({len(actual_cmp)}): {actual_cmp}"
                ),
            )
