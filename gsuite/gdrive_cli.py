"""gdrive — school Drive files and Docs text."""

from __future__ import annotations

import re
import sys

import typer

from . import drive, render, session
from .cli_common import add_clean, fail

app = typer.Typer(help="List, find and read school Drive files.", no_args_is_help=True,
                  add_completion=False,
                  context_settings={"help_option_names": ["-h", "--help"]})

DRIVE_URL = "https://drive.google.com/drive/my-drive"


@app.command("ls")
def ls(
    path: str = typer.Option("my-drive", "--path", "-p",
                             help="my-drive, shared-with-me, starred, recent, or a folder id"),
    limit: int = typer.Option(50, "--limit", "-n"),
    json_out: bool = typer.Option(False, "--json"),
):
    """List a Drive location."""
    try:
        with session.tab(DRIVE_URL) as (tab, ident):
            files = drive.list_folder(tab, path, limit)
    except session.SessionError as e:
        raise fail(e)
    if json_out:
        typer.echo(render.to_json({"path": path, "files": files}))
        return
    if not files:
        render.console.print(f"[dim]{path} is empty[/]")
        return
    render.console.print(render.header(ident.email, f"{path} · {len(files)}"))
    render.console.print(render.files_view(files))


@app.command()
def find(
    query: str = typer.Argument(..., help="File name fragment (or Drive query, e.g. 'type:document Week')"),
    limit: int = typer.Option(25, "--limit", "-n"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Find files by name."""
    try:
        with session.tab(DRIVE_URL) as (tab, ident):
            files = drive.search(tab, query, limit)
    except session.SessionError as e:
        raise fail(e)
    if json_out:
        typer.echo(render.to_json({"query": query, "files": files}))
        return
    if not files:
        render.console.print(f"[dim]no files match {query!r}[/]")
        return
    render.console.print(render.header(ident.email, f"{query!r} · {len(files)}"))
    render.console.print(render.files_view(files))


@app.command()
def cat(
    file_id: str = typer.Argument(..., help="Drive file id (from `gdrive ls`/`find`)"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Print a file's text (Docs, PDFs, and anything Drive renders)."""
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
