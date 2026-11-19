"""Build the ``user_context`` a harness passes to ``agent.invoke``.

The agent appends this text to the first message under a neutral
``## User Context`` heading and adds no wording of its own, so the text alone
has to say whose facts these are. Two rules follow, for every benchmark:

* Write the facts in the first person ("My name is ..."), as the person who
  gives the task would say them.
* Do not use a benchmark's internal role name as a label. AppWorld calls the
  person the agent acts for the "supervisor"; shown to a model as a
  "Supervisor" label it was read as the user's manager, and the agent wrote the
  user's own address for "my manager" (cuga-eval#218).

This module imports no benchmark package, so its tests run in CI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional


def build_first_person_user_context(
    *,
    first_name: str,
    last_name: str,
    email: Optional[str] = None,
    phone_number: Optional[str] = None,
    current_datetime: Optional[datetime] = None,
) -> str:
    """Return the user's identity, stated by the user, plus the current datetime.

    Contact details that are missing are left out of the sentence.
    """
    contact = []
    if email:
        contact.append(f"My personal email is {email}")
    if phone_number:
        # Continues the email clause when there is one, otherwise starts its own.
        contact.append(f"phone number is {phone_number}" if email else f"My phone number is {phone_number}")

    identity = f"My name is: {first_name} {last_name}."
    if contact:
        identity += " " + " and ".join(contact) + "."

    lines = [identity]
    if current_datetime is not None:
        lines.append(f"Current datetime: {current_datetime.isoformat()}")
    return "\n".join(lines) + "\n"
