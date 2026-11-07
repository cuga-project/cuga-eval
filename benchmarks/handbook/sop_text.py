"""The text of a HANDBOOK task's SOP: one parser, used by the old runner, the golden tool, the replay and the harness.

The sample is downloaded content: files are only read, and whoever imports this runs with ``-I``.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, List, Optional

_BLOCKS = ("p", "div", "br", "li", "tr", "table", "ul", "ol", "pre", "h1", "h2", "h3", "h4", "h5", "h6")
_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")


class _Visible(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.out: List[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style"):
            self.skip += 1
        if tag in _BLOCKS:
            self.out.append("\n")
        if tag in _HEADINGS:
            self.out.append("#" * int(tag[1]) + " ")
        if tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(data)


def html_text(raw: str) -> str:
    """Visible text of an HTML document (headings kept as '#' lines); plain text passes through."""
    if "<" not in raw[:2000]:
        return raw
    parser = _Visible()
    parser.feed(raw)
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", "".join(parser.out)))


def largest_sop_file(task_dir: Path) -> Optional[Path]:
    """The largest file of the task's workspace named as an SOP, or ``None`` when no file is."""
    files = [
        f for f in (Path(task_dir) / "environment/initial_workspace").iterdir() if "sop" in f.name.lower()
    ]
    return max(files, key=lambda f: f.stat().st_size) if files else None
