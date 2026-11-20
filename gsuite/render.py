"""Shared rich rendering for the gsuite CLIs."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

console = Console()
err = Console(stderr=True)


def header(who: str, what: str = "") -> Text:
    t = Text(who, style="dim")
    if what:
        t.append(f"  ·  {what}", style="dim")
    return t


def to_json(obj: Any) -> str:
    def default(o: Any) -> Any:
        if is_dataclass(o) and not isinstance(o, type):
            return asdict(o)
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        raise TypeError(f"{type(o).__name__} is not JSON serialisable")
    return json.dumps(obj, indent=2, default=default, ensure_ascii=False)


def messages_table(msgs: list[Any]) -> Table:
    """Fixed widths + no wrap: Gmail subjects are long and would reflow the ID."""
    t = Table(box=None, pad_edge=False, header_style="dim", expand=False)
    # Ids are printed in full: they are the argument to `read`, so a
    # truncated display id is a trap. Search returns long thread ids while the
    # inbox feed returns short message ids, so size the column to the content.
    widest = max((len(m.id) for m in msgs), default=0)
    t.add_column("Id", style="dim", no_wrap=True,
                 width=max(16, min(widest, 35)))
    t.add_column("When", style="dim", no_wrap=True, width=16)
    t.add_column("From", no_wrap=True, width=18, overflow="ellipsis")
    t.add_column("Subject", no_wrap=True, overflow="ellipsis")
    for m in msgs:
        when = (m.when or "")[:16].replace("T", " ")
        sender = (m.sender or m.email_addr or "").replace("\n", " ").strip()
        subject = (m.subject or "").replace("\n", " ").strip()
        t.add_row(m.id or "—", when, sender, subject)
    return t


def messages_view(msgs: list[Any]) -> Any:
    """Table when ids are short, stacked lines when they are long.

    Search returns ~35-char thread ids. Squeezing those into columns pushes
    them past the console width, and rich then ellipsizes the one field that
    has to be exact (the id you paste into `read`). So long ids are printed
    in full on their own line with the metadata beneath.
    """
    # Inbox-feed ids are 16 chars; anything longer is a search thread id.
    widest = max((len(m.id) for m in msgs), default=0)
    if widest <= 16:
        return messages_table(msgs)
    from rich.console import Group

    lines = []
    for m in msgs:
        who = (m.sender or m.email_addr or "").replace("\n", " ").strip()
        when = (m.when or "").replace("T", " ").strip()
        meta = " · ".join(x for x in (when, who) if x)
        lines.append(Text(m.id or "—  (no id; use --link from --json)", style="dim"))
        lines.append(Text(f"  {(m.subject or '').strip()}", overflow="fold"))
        if meta:
            lines.append(Text(f"  {meta}", style="dim", overflow="fold"))
        lines.append(Text(""))
    return Group(*lines[:-1])


def files_view(files: list[Any]) -> Any:
    """Table for short ids, stacked "id / name" pairs for Drive's long ones.

    Drive ids run 33-65 characters. Side by side with a name they don't fit a
    normal terminal, and rich resolves that by ellipsizing the name — so the
    listing becomes a column of ids. Stacking keeps both readable and keeps
    the id exact.
    """
    widest = max((len(f.id) for f in files), default=0)
    if widest <= 28:
        return files_table(files)
    from rich.console import Group

    lines = []
    for f in files:
        lines.append(Text(f.id, style="dim"))
        lines.append(Text(f"  {f.name.strip()}", overflow="fold"))
    return Group(*lines)


def files_table(files: list[Any]) -> Table:
    t = Table(box=None, pad_edge=False, header_style="dim")
    t.add_column("Id", style="dim", no_wrap=True)
    t.add_column("Name", overflow="ellipsis")
    for f in files:
        t.add_row(f.id, f.name[:70])
    return t


def events_table(events: list[Any]) -> Table:
    t = Table(box=None, pad_edge=False, header_style="dim")
    t.add_column("Date", no_wrap=True)
    t.add_column("Time", style="dim", no_wrap=True)
    t.add_column("Event")
    for e in events:
        day = e.day.strftime("%a %b %-d") if e.day else "—"
        when = e.when or ""
        if e.day and e.day.strftime("%B %-d, %Y") in when:
            when = "all day"
        t.add_row(day, when[:22], e.summary[:70])
    return t
