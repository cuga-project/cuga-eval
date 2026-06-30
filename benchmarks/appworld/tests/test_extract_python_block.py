"""Regression test for PR #79/#74 review.

``appworld_eval_react._extract_python_block`` used to ``return text.strip()``
when the LLM response carried no ```python fence, so non-code prose/refusals
were handed straight to ``world.execute()`` and run as Python — and the
caller's ``if not code`` hard-fail guard never fired.

The fix returns ``""`` on the no-fence path so the guard hard-fails instead.

The eval module can't be imported here (its top-level ``load_eval_config`` needs
the AppWorld environment), so — like ``test_avg_steps`` — this asserts the source
structure with ``ast`` rather than importing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

_REACT = Path(__file__).resolve().parents[1] / "appworld_eval_react.py"


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(_REACT.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {_REACT}")


def test_extract_python_block_does_not_return_raw_text() -> None:
    fn = _function("_extract_python_block")
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]

    # No return hands back the unfenced input (e.g. ``return text.strip()``):
    # that would feed prose to world.execute().
    for r in returns:
        val = r.value
        if isinstance(val, ast.Call) and isinstance(val.func, ast.Attribute):
            target = val.func.value
            assert not (isinstance(target, ast.Name) and target.id == "text"), (
                "no-fence path must not return the raw `text`; return '' so the "
                "caller's hard-fail guard fires"
            )

    # The no-fence fallback returns an empty string constant.
    assert any(isinstance(r.value, ast.Constant) and r.value.value == "" for r in returns), (
        "expected a `return ''` fallback for the no-fence case"
    )
