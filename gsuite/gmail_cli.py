"""gmail — the school mailbox."""

from __future__ import annotations

import re
import sys
from typing import Optional

import typer
from rich.text import Text

from . import mail, render, session
from .cli_common import add_clean, fail

app = typer.Typer(help="Read and send school Gmail.", no_args_is_help=True,
                  add_completion=False,
                  context_settings={"help_option_names": ["-h", "--help"]})

MAIL_URL = "https://mail.google.com/mail/u/0/"


def _note_unresolved(msgs: list[mail.Message]) -> None:
    """Say so when a row had no resolvable id, instead of printing a fake one."""
    missing = sum(1 for m in msgs if not m.id)
    if missing:
        render.console.print(
            f"[yellow]{missing} result(s) had no resolvable thread id; "
            "use --json and pass --link to `read`[/]")


@app.command("list")
def list_cmd(
    limit: int = typer.Option(20, "--limit", "-n"),
    unread: bool = typer.Option(False, "--unread", help="Only unread (uses search)"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Newest inbox messages (Atom feed: title, sender, date)."""
    try:
        with session.tab(MAIL_URL) as (tab, ident):
            msgs = mail.search(tab, "is:unread", limit) if unread else mail.list_inbox(tab, limit)
    except session.SessionError as e:
        raise fail(e)
    if json_out:
        typer.echo(render.to_json({"account": ident.email, "messages": msgs}))
        return
    render.console.print(render.header(ident.email, f"inbox · {len(msgs)}"))
    render.console.print(render.messages_view(msgs))
    _note_unresolved(msgs)


@app.command()
def search(
    query: str = typer.Argument(..., help="Gmail query, e.g. 'from:teacher@school' or 'has:attachment'"),
    limit: int = typer.Option(20, "--limit", "-n"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Search mail (full Gmail query syntax)."""
    try:
        with session.tab(MAIL_URL) as (tab, ident):
            msgs = mail.search(tab, query, limit)
    except session.SessionError as e:
        raise fail(e)
    if json_out:
        typer.echo(render.to_json({"query": query, "messages": msgs}))
        return
    if not msgs:
        render.console.print(f"[dim]no messages match {query!r}[/]")
        return
    render.console.print(render.header(ident.email, f"{query!r} · {len(msgs)}"))
    render.console.print(render.messages_view(msgs))
    _note_unresolved(msgs)


@app.command()
def read(
    message_id: str = typer.Argument(..., help="Thread id from `gmail search`, or inbox id from `list`"),
    link: Optional[str] = typer.Option(None, "--link", help="Permalink (from --json)"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Print one message's text."""
    if not link and not re.fullmatch(r"[0-9a-zA-Z_-]{6,}", message_id or ""):
        render.err.print(f"[red]{message_id!r} doesn't look like a Gmail thread id[/]")
        raise typer.Exit(1)
    try:
        with session.tab(MAIL_URL) as (tab, _ident):
            thread = mail.read(tab, message_id, link or "")
    except session.SessionError as e:
        raise fail(e)
    if json_out:
        typer.echo(render.to_json(thread))
        return
    render.console.print(Text(thread.subject or "(no subject)", style="bold"))
    if thread.senders:
        render.console.print(Text(" · ".join(str(x) for x in thread.senders[:4]), style="dim"))
    render.console.print()
    render.console.print(thread.text)


@app.command()
def send(
    to: str = typer.Argument(..., help="Recipient address"),
    subject: str = typer.Option(..., "--subject", "-s"),
    body: str = typer.Option("", "--body", "-b", help="Body text"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Send without asking"),
):
    """Send an email. Asks for confirmation unless --yes."""
    if not yes:
        render.console.print(render.header(session.email(), "about to send"))
        render.console.print(f"  to:      {to}")
        render.console.print(f"  subject: {subject}")
        render.console.print(f"  body:    {body[:200] or '(empty)'}")
        if not typer.confirm("Send this email?"):
            render.console.print("[dim]cancelled[/]")
            raise typer.Exit(1)
    try:
        with session.tab(MAIL_URL) as (tab, _ident):
            result = mail.fill_and_send(tab, to, subject, body)
    except session.SessionError as e:
        raise fail(e)
    render.console.print(f"[green]sent[/] to {result['to']}")


@app.command()
def archive(
    message_id: str = typer.Argument(..., help="Thread id from `gmail search`"),
    link: Optional[str] = typer.Option(None, "--link"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Archive a thread (out of the inbox)."""
    try:
        with session.tab(MAIL_URL) as (tab, _ident):
            ok = mail.archive(tab, message_id, link or "")
    except session.SessionError as e:
        raise fail(e)
    if not ok:
        render.err.print("[red]archive did not take effect (the thread is still open)[/]")
        raise typer.Exit(3)
    if json_out:
        typer.echo(render.to_json({"id": message_id, "archived": True}))
        return
    render.console.print("[green]archived[/]")


@app.command("mark-read")
def mark_read_cmd(
    message_id: str = typer.Argument(..., help="Thread id from `gmail search`"),
    link: Optional[str] = typer.Option(None, "--link"),
    unread: bool = typer.Option(False, "--unread", help="Mark unread instead"),
):
    """Mark a thread read (or unread)."""
    try:
        with session.tab(MAIL_URL) as (tab, _ident):
            ok = mail.mark_read(tab, message_id, link or "", read=not unread)
    except session.SessionError as e:
        raise fail(e)
    if not ok:
        render.err.print("[red]the read state did not change[/]")
        raise typer.Exit(3)
    render.console.print("[green]marked unread[/]" if unread else "[green]marked read[/]")


add_clean(app)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)
