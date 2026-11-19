"""List every record of an AutomationBench world through the agent's own read tools (no direct world access).

The policy layer reads these records at the task start, so a rule in an app the agent never opens still reaches it.
Only read tools are called, so the world and the score do not change. Three apps hold nested data and get their own
walk (Drive -> spreadsheets -> worksheets -> rows, Slack channels -> messages -> threads, Gmail with a page size);
every other app gets each read tool that needs no argument. A worksheet is one record (its headers and rows), so a
rule table is judged as a whole.
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any, Callable, Dict, Iterator, List, Tuple

# Paging arguments set to a large value when a read tool has them (fixed names of the tool schemas).
PAGE_ARGS = {
    "max_results": 1000,
    "maxResults": 1000,
    "limit": 1000,
    "pageSize": 1000,
    "page_size": 1000,
    "per_page": 1000,
    "row_count": 10000,
}
MORE_KEYS = ("has_more", "hasMore", "nextPageToken", "next_page_token", "next_cursor")
ID_KEYS = ("id", "ts", "message_id", "Id", "ID")
NESTED_APPS = {"gmail", "slack", "google_sheets", "google_drive", "salesforce", "google_calendar"}
VALID_TYPES = re.compile(r"Valid types: \[([^\]]*)\]")  # the error text of salesforce_query


def _decode(x: Any) -> Any:
    """Tool results nest JSON inside strings; decode them all."""
    if isinstance(x, str):
        s = x.strip()
        if s[:1] in "[{":
            try:
                return _decode(json.loads(s))
            except ValueError:
                return x
        return x
    if isinstance(x, dict):
        return {k: _decode(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_decode(v) for v in x]
    return x


def _records(x: Any) -> Iterator[Dict[str, Any]]:
    """Every dict that carries an ID is a record, without the records nested in it (those come on their own)."""
    if isinstance(x, list):
        for v in x:
            yield from _records(v)
    elif isinstance(x, dict):
        nested = {k: list(_records(v)) for k, v in x.items()}
        if any(k in x for k in ID_KEYS):
            yield {k: v for k, v in x.items() if not nested[k]}
        for recs in nested.values():
            yield from recs


def _more(x: Any) -> bool:
    if isinstance(x, dict):
        if any(x.get(k) for k in MORE_KEYS):
            return True
        return any(_more(v) for v in x.values())
    if isinstance(x, list):
        return any(_more(v) for v in x)
    return False


class Lister:
    def __init__(
        self,
        fns: List[Callable[..., Any]],
        world: Any,
        app_of: Callable[[Callable[..., Any]], str],
        is_write: Callable[[str], bool],
    ):
        self.world = world
        self.by_name = {f.__name__: f for f in fns}
        self.app_of = {f.__name__: app_of(f) for f in fns}
        self.reads = [f for f in fns if not is_write(f.__name__)]
        self.calls = 0
        self.errors: List[str] = []
        self.incomplete: set = set()

    def call(self, name: str, **kwargs: Any) -> Any:
        fn = self.by_name.get(name)
        if fn is None:
            return None
        params = inspect.signature(fn).parameters
        kwargs.update({k: v for k, v in PAGE_ARGS.items() if k in params and k not in kwargs})
        self.calls += 1
        try:
            out = _decode(fn(world=self.world, **kwargs))
        except Exception as exc:  # a failed read is reported, never raised
            self.errors.append(f"{name}: {str(exc)[:120]}")
            return None
        if _more(out):
            self.incomplete.add(self.app_of.get(name, name))
        return out

    # -- nested apps ----------------------------------------------------------------------------------------------
    def gmail(self) -> List[Dict[str, Any]]:
        out = self.call("gmail_list_emails", include_spam_trash=True)
        return list(_records(out.get("messages", []) if isinstance(out, dict) else []))

    def slack(self) -> List[Dict[str, Any]]:
        chans = self.call("slack_list_channels") or {}
        recs: List[Dict[str, Any]] = []
        for c in chans.get("channels", []) if isinstance(chans, dict) else []:
            cid = c.get("id")
            got = self.call("slack_list_channel_messages", channel=cid) or {}
            msgs = got.get("messages", []) if isinstance(got, dict) else []
            for m in msgs:
                recs.append({**m, "channel_name": c.get("name")})
                if m.get("reply_count") or (m.get("thread_ts") and m.get("thread_ts") == m.get("ts")):
                    rep = self.call(
                        "slack_get_thread_replies", channel=cid, thread_ts=m.get("thread_ts") or m.get("ts")
                    )
                    for r in (rep or {}).get("messages", []) if isinstance(rep, dict) else []:
                        if r.get("ts") != m.get("ts"):
                            recs.append({**r, "channel_name": c.get("name")})
        return recs

    def sheets(self) -> List[Dict[str, Any]]:
        files = self.call("google_drive_find_multiple_files") or {}
        ids = []
        for f in _records(files):
            if "spreadsheet" in str(f.get("mimeType", "")) and f.get("id") not in ids:
                ids.append(f.get("id"))
        recs: List[Dict[str, Any]] = []
        for sid in ids:
            ss = (self.call("google_sheets_get_spreadsheet_by_id", spreadsheet_id=sid) or {}).get(
                "spreadsheet"
            ) or {}
            for ws in ss.get("worksheets", []):
                rows = (
                    self.call("google_sheets_get_many_rows", spreadsheet_id=sid, worksheet_id=ws.get("id"))
                    or {}
                )
                recs.append(
                    {
                        "id": f"{sid}/{ws.get('id')}",
                        "spreadsheet": ss.get("title"),
                        "worksheet": ws.get("title"),
                        "headers": ws.get("headers"),
                        "rows": _rows(rows),
                    }
                )
        return recs

    def salesforce(self) -> List[Dict[str, Any]]:
        """One query per object type; the types come from the tool's own error for an empty query."""
        err = self.call("salesforce_query") or {}
        m = VALID_TYPES.search(str(err.get("error", "")) if isinstance(err, dict) else "")
        types = re.findall(r"'([A-Za-z]+)'", m.group(1)) if m else []
        recs: List[Dict[str, Any]] = []
        for t in types:
            got = self.call(
                "salesforce_query", object_type=t, where_clause="Id != ''"
            )  # every record has an Id
            recs.extend({**r, "object_type": t} for r in _records(got))
        return recs

    def calendar(self) -> List[Dict[str, Any]]:
        """Events of every listed calendar and of "primary", the Google Calendar API name of the user's own calendar."""
        cals = self.call("google_calendar_find_calendars", showHidden=True, showDeleted=True) or {}
        ids = ["primary"] + [c.get("id") for c in _records(cals) if c.get("id") not in (None, "primary")]
        recs: List[Dict[str, Any]] = list(_records(cals))
        for cid in ids:
            recs.extend(_records(self.call("google_calendar_find_event", calendarid=cid)))
        return recs

    # -- every other app ------------------------------------------------------------------------------------------
    def flat(self, app: str) -> List[Dict[str, Any]]:
        recs: List[Dict[str, Any]] = []
        for f in self.reads:
            if self.app_of[f.__name__] != app:
                continue
            ps = [
                p
                for n, p in inspect.signature(f).parameters.items()
                if n != "world" and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)
            ]
            if all(p.default is not p.empty for p in ps):
                recs.extend(_records(self.call(f.__name__)))
        return recs

    def all(self) -> Dict[str, List[Dict[str, Any]]]:
        apps = sorted({a for a in self.app_of.values() if a})
        out: Dict[str, List[Dict[str, Any]]] = {}
        if "gmail" in apps:
            out["gmail"] = self.gmail()
        if "slack" in apps:
            out["slack"] = self.slack()
        if "google_sheets" in apps and "google_drive_find_multiple_files" in self.by_name:
            out["google_sheets"] = self.sheets()
        if "salesforce" in apps:
            out["salesforce"] = self.salesforce()
        if "google_calendar" in apps:
            out["google_calendar"] = self.calendar()
        for a in apps:
            if a not in NESTED_APPS:
                out[a] = self.flat(a)
        return {a: _unique(r) for a, r in out.items() if r}


def _rows(x: Any) -> List[Any]:
    if isinstance(x, dict):
        for k in ("rows", "values", "results", "data"):
            if isinstance(x.get(k), list):
                return x[k]
    return list(_records(x))


def _unique(recs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for r in recs:
        k = json.dumps(r, sort_keys=True, default=str)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def list_world(
    fns: List[Callable[..., Any]], world: Any, app_of: Callable[..., str], is_write: Callable[[str], bool]
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Any]]:
    """(records by app, report). The report has the read calls, failed reads and apps with pages left. The tools run on
    a copy of the world: some read tools log the call in the world's action list, and the scored world must not
    change."""
    lister = Lister(fns, world.model_copy(deep=True), app_of, is_write)
    recs = lister.all()
    report: Dict[str, Any] = {
        "calls": lister.calls,
        "errors": lister.errors,
        "incomplete": sorted(lister.incomplete),
        "records": {a: len(r) for a, r in recs.items()},
    }
    return recs, report
