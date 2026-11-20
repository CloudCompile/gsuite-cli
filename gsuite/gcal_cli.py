"""gcal — school Google Calendar."""

from __future__ import annotations

import sys
from datetime import date
from typing import Optional

import typer

from . import calendar as gcal, render, session
from .cli_common import add_clean, fail

app = typer.Typer(help="Read the school calendar.", no_args_is_help=True,
                  add_completion=False,
                  context_settings={"help_option_names": ["-h", "--help"]})

CAL_URL = "https://calendar.google.com/calendar/u/0/r"


def _day(value: Optional[str]) -> date:
    if not value:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError:
        render.err.print(f"[red]bad date {value!r}; use YYYY-MM-DD[/]")
        raise typer.Exit(1)


@app.command()
def agenda(
    start: Optional[str] = typer.Option(None, "--start", "-s", help="Start date (YYYY-MM-DD)"),
    days: int = typer.Option(7, "--days", "-d"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Upcoming events."""
    when = _day(start)
    try:
        with session.tab(CAL_URL, settle=4) as (tab, ident):
            events = gcal.agenda(tab, when, days=days)
    except session.SessionError as e:
        raise fail(e)
    if json_out:
        typer.echo(render.to_json({"start": when, "days": days, "events": events}))
        return
    render.console.print(render.header(ident.email, f"agenda · {days}d from {when:%b %-d}"))
    if not events:
        render.console.print("[dim]no events in that range[/]")
        return
    render.console.print(render.events_table(events))


@app.command()
def today(json_out: bool = typer.Option(False, "--json")):
    """Today's events."""
    try:
        with session.tab(CAL_URL, settle=4) as (tab, ident):
            events = gcal.today(tab)
    except session.SessionError as e:
        raise fail(e)
    if json_out:
        typer.echo(render.to_json({"date": date.today(), "events": events}))
        return
    render.console.print(render.header(ident.email, date.today().strftime("%A, %B %-d")))
    if not events:
        render.console.print("[dim]nothing on the calendar today[/]")
        return
    render.console.print(render.events_table(events))


add_clean(app)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)
