"""Pure string post-processors for the final answer (ported from the VAKRA runs).

Two delivery points use these functions:

* ``make_final_answer_fn(cfg)`` builds the deterministic function handed to
  ``CugaAgent(final_answer=...)`` — applied once, in-graph, by the SDK
  (merged to cuga main in #621). It carries the harmony-token strip plus the
  judge-shape canonicalization that ran inside the vendored CUGA during the
  validated runs (``advanced_features.final_answer_canonicalize``).
* The evidence-dependent guards in ``guards.py`` reuse the detectors here
  (give-up phrasing, failure/bluff shapes) and the normalizers
  (``normalize_answer``, ``extract_values_answer``).

Everything is pure, idempotent, and import-light (stdlib only) so it unit-tests
without a configured CUGA environment.
"""

from __future__ import annotations

import json
import re
from typing import Callable, Optional

from benchmarks.m3.adapter.config import AdapterConfig

#: The benchmark's canonical refusal string (the only refusal shape that passes
#: groundedness in the VAKRA judge).
REFUSAL = "I can not answer."

_CHANNEL_TOKEN_RE = re.compile(r"<\|[^>]*?\|>")


def strip_channel_tokens(text: str) -> str:
    """Remove leaked gpt-oss harmony control tokens (``<|start|>``, ``<|channel|>``...)."""
    return _CHANNEL_TOKEN_RE.sub("", text or "").strip()


# Give-up / cancellation phrasings (cuga_clean_agent.py). With refusal_norm on,
# an answer that is really "I couldn't do this" is normalized to REFUSAL.
_GIVEUP_MARKERS = (
    "i can not answer",
    "i cannot answer",
    "unable to locate",
    "unable to find",
    "i'm unable",
    "i am unable",
    "no tool",
    "no available tool",
    "no suitable tool",
    "don't have any tool",
    "do not have any tool",
    "don't have access",
    "cannot find a tool",
    "can't find a tool",
    "execution cancelled",
    "requires your approval",
    "no accessible tool",
)


def is_giveup(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _GIVEUP_MARKERS)


_GIVE_UP_RE = re.compile(
    r"unable to|no way to|not (?:available|possible)|cannot (?:find|determine|compute|retrieve)|"
    r"can't (?:find|determine|compute)|do(?:n't| not) have (?:access|a tool|any tool)|"
    r"functions? (?:do(?:n't| not) (?:include|support|allow))|I(?:'m| am) sorry|^IMPOSSIBLE$",
    re.IGNORECASE,
)

# Suspicious minimal answers that are usually bluffs after a failed step.
_BLUFF_VALUES = {"0", "n/a", "na", "[]", "none", "unknown", "impossible", "[[]]", "0.0"}


def looks_like_failure(text: str) -> bool:
    """Draft answers that signal an incomplete/failed run (give-up prose or bluff values)."""
    t = (text or "").strip()
    if not t:
        return False  # empty is handled separately by the gate corrections
    if "IMPOSSIBLE" in t.upper():
        return True
    if _GIVE_UP_RE.search(t):
        return True
    return t.strip("*` .").lower() in _BLUFF_VALUES


# Trailing citation clause CUGA's final-answer composer sometimes appends
# ("Charles. Source: hockey_get_players_by_position."). The groundedness judge
# treats the tool-name citation as an unsupported claim, so a correct value
# scores 0. Strip only a TRAILING clause; a "Source" mid-answer is content.
_SOURCE_SUFFIX_RE = re.compile(r"[\s.]*\bSources?\s*:\s*[^.:]{1,200}\.?\s*$", re.IGNORECASE)


def normalize_answer(text: str) -> str:
    """Deterministic, judge-aligned cleanup of the final answer string.

    - strips markdown emphasis and surrounding quotes/backticks
    - drops a trailing "Source: ..." citation clause (judge counts it as an
      unsupported claim)
    - collapses float-formatted integers (36526.0 -> 36526), incl. inside lists
    - drops stray IMPOSSIBLE tokens when real content is present
    - never touches non-numeric content beyond the cleanups above
    """
    t = (text or "").strip()
    t = re.sub(r"[*_`]{1,3}", "", t).strip()
    desourced = _SOURCE_SUFFIX_RE.sub("", t).strip()
    if desourced:  # keep the citation only when it is all there is
        t = desourced
    t = re.sub(r"(?<![\d.])(\d+)\.0(?![\d])", r"\1", t)
    stripped = re.sub(r"\bIMPOSSIBLE\b", "", t, flags=re.IGNORECASE).strip(" .,;:")
    if stripped:  # keep the real content; keep IMPOSSIBLE only when it's all there is
        t = stripped
    return t


def extract_values_answer(text: str) -> str:
    """cap2 helper: if the answer is a JSON object, answer with its values.

    Under the verbatim rule the model relays raw tool JSON like ``{"count": 0}``;
    the ground truth wants bare values / list-of-lists. Deterministic, no LLM.
    Non-JSON content is returned as-is.
    """
    t = (text or "").strip()
    if t.startswith("[") and t.endswith("]"):
        try:
            arr = json.loads(t)
        except (ValueError, TypeError):
            return t
        if isinstance(arr, list) and arr and all(isinstance(x, dict) for x in arr):
            rows = [[v for v in x.values()] for x in arr]
            return normalize_answer(json.dumps(rows, ensure_ascii=False, default=str))
        return t
    if not (t.startswith("{") and t.endswith("}")):
        return t
    try:
        obj = json.loads(t)
    except (ValueError, TypeError):
        return t
    if not isinstance(obj, dict) or not obj:
        return t
    values = list(obj.values())
    while len(values) == 1 and isinstance(values[0], (dict, list)):
        inner = values[0]
        values = list(inner.values()) if isinstance(inner, dict) else inner
        if not isinstance(values, list):
            return json.dumps(values, ensure_ascii=False, default=str)
    if len(values) == 1 and not isinstance(values[0], (dict, list)):
        return normalize_answer(str(values[0]))
    return normalize_answer(json.dumps(values, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# Canonicalization (re-implementation of the vendored CUGA's
# advanced_features.final_answer_canonicalize, which is not in cuga main).
# ---------------------------------------------------------------------------

_MD_RE = re.compile(r"[*_`]{1,3}")
_ANSWER_LABEL_RE = re.compile(r"^\s*(?:final\s+)?answer\s*[:=]\s*", re.I)
_BRACKET_GROUP_RE = re.compile(r"\[\[.*?\]\]", re.S)
_PLACEHOLDER_RE = re.compile(r"^\[\[[\s?\-–—.​\xa0]*\]\]$")
_WS_RE = re.compile(r"\s+")
_REFUSAL_SUBSTR = ("i can not answer", "i cannot answer", "unable to")


def _is_refusal(t: str) -> bool:
    low = t.strip().lower()
    return any(s in low for s in _REFUSAL_SUBSTR)


def _strip_to_bare(t: str) -> Optional[str]:
    """Strip ``[[..]]`` wrapping / quotes to a bare comma-joined value string.

    Mirrors the evaluator's flatten-and-join of the GT answer. Returns None if
    ``t`` has no bracket structure to strip (caller keeps the cleaned text).
    """
    groups = _BRACKET_GROUP_RE.findall(t)
    if len(groups) > 1:
        good = [g for g in groups if not _PLACEHOLDER_RE.match(g.strip())]
        t = (good[-1] if good else groups[-1]).strip()
    if "[[" not in t and "]]" not in t:
        return None
    s = t
    s = re.sub(r"\]\s*,\s*\[", ", ", s)  # row separators "],[" -> ", "
    s = s.replace("[", "").replace("]", "")  # drop remaining brackets
    s = re.sub(r'"\s*,\s*"', ", ", s)  # quoted-cell separators
    s = re.sub(r"'\s*,\s*'", ", ", s)
    s = s.replace('"', "").replace("​", "")  # drop quotes + zero-width
    s = _WS_RE.sub(" ", s).strip().strip(",").strip()
    return s or None


def canonicalize_final_answer(text: str, *, bare: bool = True) -> str:
    """Return a canonicalized copy of ``text``. Non-str inputs pass through unchanged.

    The VAKRA judge compares against a stringified GT that flattens ``[[..]]``
    to bare comma-joined values; a bare answer matches deterministically while a
    bracket-wrapped one is a coin flip. Refusals and empty answers are untouched.
    """
    if not isinstance(text, str):
        return text
    t = text.strip()
    if not t:
        return t
    t = _MD_RE.sub("", t).strip()
    t = _ANSWER_LABEL_RE.sub("", t).strip()
    if _is_refusal(t):  # leave refusals untouched
        return t
    if bare:
        stripped = _strip_to_bare(t)
        if stripped is not None:
            return stripped
    return t


def make_final_answer_fn(cfg: AdapterConfig) -> Callable[[str], str]:
    """The deterministic function for ``CugaAgent(final_answer=...)``.

    Always strips leaked harmony tokens (a correctness fix, not tuning); adds
    canonicalization when the preset enables it. The SDK applies it once and
    fails open, so a surprising input can never break answer delivery.
    """

    def _final_answer(text: str) -> str:
        out = strip_channel_tokens(text)
        if cfg.canonicalize:
            out = canonicalize_final_answer(out)
        return out

    return _final_answer
