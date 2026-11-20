"""CLI wiring: commands exist and bad input fails loudly (no browser needed)."""
from typer.testing import CliRunner

from gsuite import gcal_cli, gdocs_cli, gdrive_cli, gmail_cli

runner = CliRunner()


def test_gmail_commands():
    r = runner.invoke(gmail_cli.app, ["--help"])
    assert r.exit_code == 0
    for cmd in ("list", "search", "read", "send", "archive", "mark-read"):
        assert cmd in r.output


def test_gdrive_commands():
    r = runner.invoke(gdrive_cli.app, ["--help"])
    assert r.exit_code == 0
    for cmd in ("ls", "find", "cat"):
        assert cmd in r.output


def test_gdocs_commands():
    r = runner.invoke(gdocs_cli.app, ["--help"])
    assert r.exit_code == 0
    for cmd in ("recent", "find", "cat"):
        assert cmd in r.output


def test_gdocs_search_is_scoped_to_documents():
    """`find` must not return spreadsheets or PDFs."""
    assert gdocs_cli._query("Week 13") == "type:document Week 13"
    assert gdocs_cli._query("") == "type:document"


def test_gdocs_cat_rejects_bad_id(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("should not open a browser for bad input")

    monkeypatch.setattr(gdocs_cli.session, "tab", boom)
    r = runner.invoke(gdocs_cli.app, ["cat", "nope"])
    assert r.exit_code == 1


def test_gcal_commands():
    r = runner.invoke(gcal_cli.app, ["--help"])
    assert r.exit_code == 0
    for cmd in ("agenda", "today"):
        assert cmd in r.output


def test_gcal_rejects_bad_date():
    r = runner.invoke(gcal_cli.app, ["agenda", "--start", "whenever"])
    assert r.exit_code == 1
    assert "YYYY-MM-DD" in r.output


def test_gmail_read_rejects_bad_id(monkeypatch):
    """A malformed id must fail before touching the browser."""
    def boom(*a, **kw):
        raise AssertionError("should not open a browser for bad input")

    monkeypatch.setattr(gmail_cli.session, "tab", boom)
    r = runner.invoke(gmail_cli.app, ["read", "x"])
    assert r.exit_code == 1
    assert "thread id" in r.output


def test_gdrive_cat_rejects_bad_id(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("should not open a browser for bad input")

    monkeypatch.setattr(gdrive_cli.session, "tab", boom)
    r = runner.invoke(gdrive_cli.app, ["cat", "nope"])
    assert r.exit_code == 1
    assert "Drive file id" in r.output
