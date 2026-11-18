"""The user context names the person the agent acts for in the first person.

AppWorld calls that person the task "supervisor". Passed to a model under a
"Supervisor" label, it was read as the user's manager (cuga-eval#218).
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

pytest.importorskip(
    "appworld",
    reason="AppWorld package not installed; run ./setup_appworld.sh to enable this test.",
)

from benchmarks.appworld import eval_appworld_sdk  # noqa: E402

pytestmark = pytest.mark.unit


def _world():
    supervisor = {
        "first_name": "Ashley",
        "last_name": "Moore",
        "email": "as_moore@gmail.com",
        "phone_number": "7336094411",
    }
    task = SimpleNamespace(supervisor=supervisor, datetime=datetime(2023, 5, 20, 10, 1, 33))
    return SimpleNamespace(task=task)


def test_user_context_states_identity_in_first_person():
    context = eval_appworld_sdk._build_user_context(_world())

    assert context.startswith(
        "My name is: Ashley Moore. My personal email is as_moore@gmail.com and phone number is 7336094411."
    )


def test_user_context_does_not_call_the_user_a_supervisor():
    context = eval_appworld_sdk._build_user_context(_world())

    assert "supervisor" not in context.lower()


def test_user_context_keeps_current_datetime():
    context = eval_appworld_sdk._build_user_context(_world())

    assert "Current datetime: 2023-05-20T10:01:33" in context
