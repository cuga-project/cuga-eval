"""The shared user context states the user's identity in the first person (cuga-eval#218)."""

from datetime import datetime

import pytest

from benchmarks.helpers.user_context import build_first_person_user_context

pytestmark = [pytest.mark.unit, pytest.mark.sanity]


def _context(**overrides):
    fields = {
        "first_name": "Ashley",
        "last_name": "Moore",
        "email": "as_moore@gmail.com",
        "phone_number": "7336094411",
        "current_datetime": datetime(2023, 5, 20, 10, 1, 33),
    }
    fields.update(overrides)
    return build_first_person_user_context(**fields)


def test_full_context_is_the_exact_text_validated_on_appworld():
    assert _context() == (
        "My name is: Ashley Moore. My personal email is as_moore@gmail.com"
        " and phone number is 7336094411.\n"
        "Current datetime: 2023-05-20T10:01:33\n"
    )


def test_context_never_uses_a_role_label():
    context = _context().lower()

    assert "supervisor" not in context
    assert "{" not in context


def test_missing_contact_details_are_left_out():
    assert _context(email=None, phone_number=None, current_datetime=None) == "My name is: Ashley Moore.\n"
    assert _context(email=None, current_datetime=None) == (
        "My name is: Ashley Moore. My phone number is 7336094411.\n"
    )
    assert _context(phone_number=None, current_datetime=None) == (
        "My name is: Ashley Moore. My personal email is as_moore@gmail.com.\n"
    )
