"""Unit tests for copying ToolCallTracker records into AppWorld log files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.appworld import interaction_logs as il
from benchmarks.appworld import leaderboard as lb

pytestmark = [pytest.mark.unit, pytest.mark.sanity]

GMAIL_DOCS = [
    {
        "api_name": "send_email",
        "path": "/gmail/emails",
        "method": "POST",
    },
    {
        "api_name": "show_email",
        "path": "/gmail/emails/{email_id}",
        "method": "GET",
    },
]
SUPERVISOR_DOCS = [
    {
        "api_name": "complete_task",
        "path": "/supervisor/message",
        "method": "POST",
    }
]


def _docs(app: str):
    if app == "gmail":
        return GMAIL_DOCS
    if app == "supervisor":
        return SUPERVISOR_DOCS
    raise AssertionError(app)


def test_skips_cuga_internal_tools_and_complete_task():
    assert not il.is_appworld_api_call({"name": "create_update_todos", "app_name": None})
    assert not il.is_appworld_api_call({"name": "find_tools", "app_name": "runtime"})
    assert not il.is_appworld_api_call({"name": "complete_task", "app_name": "supervisor"})
    assert not il.is_appworld_api_call({"name": "complete_task_message_post", "app_name": "supervisor"})
    assert not il.is_appworld_api_call({"name": "show_account", "app_name": "admin"})
    assert il.is_appworld_api_call({"name": "send_email", "app_name": "gmail"})
    assert il.is_appworld_api_call({"name": "gmail__send_email", "app_name": None})


def test_resolve_api_name_handles_operation_id_suffix():
    assert (
        il.resolve_api_name("gmail", "send_email_emails_post", "send_email_emails_post", docs=GMAIL_DOCS)
        == "send_email"
    )
    assert il.resolve_api_name("gmail", "gmail__send_email", None, docs=GMAIL_DOCS) == "send_email"
    assert il.resolve_api_name("gmail", "send_email", None, docs=GMAIL_DOCS) == "send_email"


def test_request_substitutes_path_params_and_keeps_the_rest():
    doc = GMAIL_DOCS[1]
    rec = il.request_from_doc(doc, {"email_id": 7, "access_token": "tok"})
    assert rec == {
        "method": "get",
        "url": "/gmail/emails/7",
        "data": {"access_token": "tok"},
    }


def test_merge_prepends_tracker_calls_and_keeps_complete_task(tmp_path: Path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "environment_io.md").write_text(
        il.environment_io_block(1, "apis.supervisor.complete_task(status='success')", "{'message': 'ok'}")
    )
    (logs / "api_calls.jsonl").write_text(
        json.dumps({"method": "post", "url": "/supervisor/complete_task", "data": {}}) + "\n"
    )

    n = il.merge_tracker_into_appworld_logs(
        logs,
        [
            {
                "name": "send_email_emails_post",
                "app_name": "gmail",
                "operation_id": "send_email_emails_post",
                "arguments": {"access_token": "tok", "to": ["a@b.com"], "subject": "hi", "body": "x"},
                "result": {"email_id": 1},
            },
            {"name": "create_update_todos", "app_name": None, "arguments": {"todos": []}, "result": "ok"},
            {"name": "complete_task", "app_name": "supervisor", "arguments": {"status": "success"}},
        ],
        docs_for_app=_docs,
    )
    assert n == 1
    md = (logs / "environment_io.md").read_text()
    assert lb.count_interactions(logs / "environment_io.md") == 2
    assert "print(apis.gmail.send_email(" in md
    assert "apis.supervisor.complete_task" in md
    assert md.index("gmail.send_email") < md.index("complete_task")
    lines = [json.loads(x) for x in (logs / "api_calls.jsonl").read_text().splitlines() if x.strip()]
    assert lines[0]["url"] == "/gmail/emails"
    assert lines[0]["method"] == "post"
    assert lines[0]["data"]["to"] == ["a@b.com"]
    assert lines[-1]["url"] == "/supervisor/complete_task"


def test_merge_is_noop_without_appworld_calls(tmp_path: Path):
    logs = tmp_path / "logs"
    logs.mkdir()
    original = il.environment_io_block(1, "apis.supervisor.complete_task(status='fail')", "x")
    (logs / "environment_io.md").write_text(original)
    assert il.merge_tracker_into_appworld_logs(logs, [{"name": "find_tools"}], docs_for_app=_docs) == 0
    assert (logs / "environment_io.md").read_text() == original


def test_arguments_json_string_is_parsed(tmp_path: Path):
    logs = tmp_path / "logs"
    logs.mkdir()
    n = il.merge_tracker_into_appworld_logs(
        logs,
        [
            {
                "name": "send_email",
                "app_name": "gmail",
                "arguments": json.dumps({"access_token": "tok", "subject": "hi"}),
                "result": {"email_id": 1},
            }
        ],
        docs_for_app=_docs,
    )
    assert n == 1
    row = json.loads((logs / "api_calls.jsonl").read_text().splitlines()[0])
    assert row["data"]["subject"] == "hi"


def test_merged_log_is_parseable_by_appworld(tmp_path: Path):
    pytest.importorskip("appworld")
    from appworld.environment import AppWorld

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "environment_io.md").write_text(
        il.environment_io_block(1, "apis.supervisor.complete_task(status='success')", "{'message': 'ok'}")
    )
    (logs / "api_calls.jsonl").write_text(
        json.dumps({"method": "post", "url": "/supervisor/complete_task", "data": {}}) + "\n"
    )
    il.merge_tracker_into_appworld_logs(
        logs,
        [
            {
                "name": "send_email",
                "app_name": "gmail",
                "arguments": {"access_token": "tok", "to": ["a@b.com"], "subject": "hi", "body": "x"},
                "result": {"email_id": 1},
            }
        ],
        docs_for_app=_docs,
    )
    parsed = AppWorld._parse_environment_io_log((logs / "environment_io.md").read_text())
    assert len(parsed) == 2
    assert "gmail.send_email" in parsed[0]["input"]
    assert "complete_task" in parsed[1]["input"]
    api_parsed = AppWorld._parse_api_calls_log((logs / "api_calls.jsonl").read_text())
    assert api_parsed[0]["url"] == "/gmail/emails"
    assert api_parsed[0]["method"] == "post"
    assert api_parsed[-1]["url"] == "/supervisor/complete_task"


def test_openapi_complete_task_is_not_duplicated():
    io, api, skipped = il.records_to_interactions(
        [
            {
                "name": "complete_task_message_post",
                "app_name": "supervisor",
                "operation_id": "complete_task_message_post",
                "arguments": {"status": "success"},
            }
        ],
        docs_for_app=_docs,
    )
    assert io == []
    assert api == []
    assert skipped == []


def test_unresolved_name_is_reported_not_written():
    io, api, skipped = il.records_to_interactions(
        [{"name": "not_an_api", "app_name": "gmail", "arguments": {}}],
        docs_for_app=_docs,
    )
    assert io == []
    assert api == []
    assert skipped == ["gmail.not_an_api"]


def test_output_fences_still_parse_with_appworld(tmp_path: Path):
    pytest.importorskip("appworld")
    from appworld.environment import AppWorld

    logs = tmp_path / "logs"
    logs.mkdir()
    n = il.merge_tracker_into_appworld_logs(
        logs,
        [
            {
                "name": "send_email",
                "app_name": "gmail",
                "arguments": {"access_token": "tok", "body": "see below"},
                "result": {"body": "use ```python\nx\n``` in the email"},
            }
        ],
        docs_for_app=_docs,
    )
    assert n == 1
    parsed = AppWorld._parse_environment_io_log((logs / "environment_io.md").read_text())
    assert len(parsed) == 1
    assert "python" in parsed[0]["output"]
    assert "```" not in parsed[0]["output"]


def test_live_gmail_docs_write_parseable_jsonl(tmp_path: Path):
    pytest.importorskip("appworld")
    from appworld.api_docs import prepare_api_docs
    from appworld.environment import AppWorld

    docs = list(prepare_api_docs("gmail"))
    send = next(d for d in docs if d["api_name"] == "send_email")
    assert send["path"] == "/gmail/emails"

    logs = tmp_path / "logs"
    logs.mkdir()
    existing = "\n".join(
        [
            f"\n### Environment Interaction 1\n{il.HORIZONTAL}",
            "```python\nprint(apis.supervisor.complete_task(status='success'))\n```\n",
            "```\n{'message': 'ok'}\n```\n\n",
        ]
    )
    (logs / "environment_io.md").write_text(existing)
    (logs / "api_calls.jsonl").write_text(
        json.dumps({"method": "post", "url": "/supervisor/complete_task", "data": {}}) + "\n"
    )
    n = il.merge_tracker_into_appworld_logs(
        logs,
        [
            {
                "name": "send_email_emails_post",
                "app_name": "gmail",
                "operation_id": "send_email_emails_post",
                "arguments": {"access_token": "tok", "to": ["a@b.com"], "subject": "hi", "body": "x"},
                "result": {"email_id": 1},
            }
        ],
    )
    assert n == 1
    parsed = AppWorld._parse_environment_io_log((logs / "environment_io.md").read_text())
    assert len(parsed) == 2
    api_parsed = AppWorld._parse_api_calls_log((logs / "api_calls.jsonl").read_text())
    assert api_parsed[0] == {
        "method": "post",
        "url": "/gmail/emails",
        "data": {"access_token": "tok", "to": ["a@b.com"], "subject": "hi", "body": "x"},
    }
    assert api_parsed[-1]["url"] == "/supervisor/complete_task"


# --- block-boundary escaping (an unescaped rule/header makes the bundle unparseable) ---


def _appworld_parse(text: str):
    pytest.importorskip("appworld", reason="AppWorld not installed; run ./setup_appworld.sh")
    from appworld.environment import AppWorld

    return AppWorld._parse_environment_io_log(text)


@pytest.mark.parametrize(
    "payload",
    [
        "-" * 76,
        "  " + "-" * 76 + "  ",
        "before\n" + "-" * 76 + "\nafter",
        "### Environment Interaction 2",
        "## Execution 3",
        "leading text\n### Environment Interaction 99\ntrailing",
        "```python\nnested fence\n```",
    ],
    ids=["rule", "padded-rule", "rule-inline", "header", "execution", "header-inline", "fence"],
)
def test_unsafe_payload_stays_parseable_by_appworld(tmp_path, payload):
    """AppWorld's own parser must still see exactly one interaction."""
    logs = tmp_path / "logs"
    logs.mkdir()
    calls = [
        {
            "name": "gmail__send_email",
            "app_name": "gmail",
            "operation_id": "send_email",
            "arguments": {"to": "a@b.c"},
            "result": payload,
        }
    ]
    n = il.merge_tracker_into_appworld_logs(logs, calls, docs_for_app=lambda _a: GMAIL_DOCS)
    assert n == 1
    text = (logs / "environment_io.md").read_text()
    assert len(_appworld_parse(text)) == 1
    # and our own re-merge parser agrees
    assert len(il.parse_existing_blocks(text)) == 1


def test_escaped_payload_is_still_readable(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    calls = [
        {
            "name": "gmail__send_email",
            "app_name": "gmail",
            "operation_id": "send_email",
            "arguments": {},
            "result": "-" * 76,
        }
    ]
    il.merge_tracker_into_appworld_logs(logs, calls, docs_for_app=lambda _a: GMAIL_DOCS)
    output = _appworld_parse((logs / "environment_io.md").read_text())[0]["output"]
    assert output.replace("​", "") == "-" * 76


def test_parse_existing_blocks_refuses_to_drop_unparseable(tmp_path):
    """Rewriting a file we cannot fully parse would delete real interactions."""
    text = "\n### Environment Interaction 1\n---\nnot a code block at all\n\n"
    with pytest.raises(ValueError, match="refusing to rewrite"):
        il.parse_existing_blocks(text)


def test_merge_leaves_file_untouched_when_existing_is_unparseable(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    broken = "\n### Environment Interaction 1\n---\nnot a code block at all\n\n"
    (logs / "environment_io.md").write_text(broken)
    calls = [
        {
            "name": "gmail__send_email",
            "app_name": "gmail",
            "operation_id": "send_email",
            "arguments": {},
            "result": "ok",
        }
    ]
    with pytest.raises(ValueError):
        il.merge_tracker_into_appworld_logs(logs, calls, docs_for_app=lambda _a: GMAIL_DOCS)
    assert (logs / "environment_io.md").read_text() == broken


# --- api-name resolution must not silently drop a call ---


def test_resolve_prefixed_name_with_suffix_and_no_operation_id():
    """`call_api` defaults operation_id to None; the prefixed name must still map."""
    assert il.resolve_api_name("gmail", "gmail__send_email_v2", None, docs=GMAIL_DOCS) == "send_email"


def test_resolve_prefers_longest_match():
    docs = [
        {"api_name": "send", "path": "/gmail/x", "method": "post"},
        {"api_name": "send_email", "path": "/gmail/emails", "method": "post"},
    ]
    assert il.resolve_api_name("gmail", "gmail__send_email_v2", None, docs=docs) == "send_email"


def test_resolve_unknown_still_returns_none():
    assert il.resolve_api_name("gmail", "gmail__totally_unknown", None, docs=GMAIL_DOCS) is None


def test_call_without_operation_id_reaches_the_logs(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    calls = [
        {
            "name": "gmail__send_email_v2",
            "app_name": "gmail",
            "operation_id": None,
            "arguments": {"to": "a@b.c"},
            "result": "sent",
        }
    ]
    assert il.merge_tracker_into_appworld_logs(logs, calls, docs_for_app=lambda _a: GMAIL_DOCS) == 1
    assert "apis.gmail.send_email(" in (logs / "environment_io.md").read_text()
