"""gdocs — Google Docs for the school account.

The Docs home page is a JS grid with no stable file ids, so documents are
found through Drive instead: Drive search understands `type:document`, which
returns the same rows `gdrive find` already parses reliably.
"""

from __future__ import annotations

import re
import sys

import typer

from . import drive, render, session
from .cli_common import add_clean, fail

app = typer.Typer(help="Find and read school Google Docs.", no_args_is_help=True,
                  add_completion=False,
                  context_settings={"help_option_names": ["-h", "--help"]})

DRIVE_URL = "https://drive.google.com/drive/my-drive"
DOCS_FILTER = "type:document"


def _query(text: str = "") -> str:
    return f"{DOCS_FILTER} {(text or '').strip()}".strip()


@app.command()
def recent(
    limit: int = typer.Option(20, "--limit", "-n"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Recently modified documents."""
    try:
        with session.tab(DRIVE_URL) as (tab, ident):
            files = drive.search(tab, DOCS_FILTER, limit)
    except session.SessionError as e:
        raise fail(e)
    if json_out:
        typer.echo(render.to_json({"documents": files}))
        return
    if not files:
        render.console.print("[dim]no documents found[/]")
        return
    render.console.print(render.header(ident.email, f"recent docs · {len(files)}"))
    render.console.print(render.files_view(files))


@app.command()
def find(
    query: str = typer.Argument(..., help="Name fragment, e.g. 'Week 13'"),
    limit: int = typer.Option(25, "--limit", "-n"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Find documents by name."""
    try:
        with session.tab(DRIVE_URL) as (tab, ident):
            files = drive.search(tab, _query(query), limit)
    except session.SessionError as e:
        raise fail(e)
    if json_out:
        typer.echo(render.to_json({"query": query, "documents": files}))
        return
    if not files:
        render.console.print(f"[dim]no documents match {query!r}[/]")
        return
    render.console.print(render.header(ident.email, f"{query!r} · {len(files)}"))
    render.console.print(render.files_view(files))


@app.command()
def cat(
    file_id: str = typer.Argument(..., help="Document id from `gdocs recent`/`find`"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Print a document's text."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{15,}", file_id or ""):
        render.err.print(f"[red]{file_id!r} doesn't look like a Drive file id[/]")
        raise typer.Exit(1)
    try:
        with session.tab(DRIVE_URL) as (tab, _ident):
            title, text = drive.read(tab, file_id)
    except session.SessionError as e:
        raise fail(e)
    if json_out:
        typer.echo(render.to_json({"id": file_id, "title": title, "text": text}))
        return
    if title:
        from rich.text import Text
        render.console.print(Text(title, style="bold"))
        render.console.print()
    render.console.print(text)


add_clean(app)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)
