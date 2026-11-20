"""Bits every gsuite CLI shares: error exits and the stray-tab sweep."""

from __future__ import annotations

import typer

from . import render, session


def fail(e: Exception) -> "typer.Exit":
    render.err.print(f"[red]{e}[/]")
    return typer.Exit(3)


def add_clean(app: typer.Typer) -> None:
    """`<cli> clean` — close automation tabs left behind by earlier runs."""

    @app.command("clean")
    def clean() -> None:
        """Close leftover mail/drive/calendar tabs."""
        try:
            n = session.close_strays()
        except session.SessionError as e:
            raise fail(e)
        render.console.print(f"[green]closed {n} stray tab(s)[/]" if n
                             else "[dim]no stray tabs[/]")
