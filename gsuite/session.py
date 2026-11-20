"""Shared session: borrow classroom's browser, profile and identity guard.

Everything here exists so a new service needs no login of its own. If the
classroom profile is signed in as the school account, mail/drive/calendar are
too — Google sessions are per-profile, not per-service.

The identity check is not optional: reading mail as the wrong account is a far
worse failure than reading the wrong Classroom.

Tab lifecycle differs from classroom's on purpose. classroom reuses one
long-lived tab and finds it by a marker in its URL; that breaks here because
these commands navigate the tab to mail/drive/calendar, which erases the
marker — so a fresh process could never find the tab again and would open
another one, leaking a tab per run. Instead each call opens its own tab and
`session.tab()` always closes the target afterwards.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from pathlib import Path

# classroom owns the profile; import it rather than duplicating the logic.
_SIBLING = Path(os.environ.get("CLASSROOM_HOME") or (Path.home() / "classroom")).expanduser()
if _SIBLING.is_dir() and str(_SIBLING) not in sys.path:
    sys.path.insert(0, str(_SIBLING))

try:
    from classroom import cdp, identity          # type: ignore
    from classroom import profile as cprofile    # type: ignore
    from classroom.profile import ClassroomError, NotSignedIn, WrongAccount  # type: ignore
except Exception as exc:                          # noqa: BLE001
    raise ImportError(
        "gsuite needs the classroom package (a checkout at ~/classroom by "
        f"default, or set CLASSROOM_HOME). Could not import it: {exc}")


class SessionError(Exception):
    """A service call failed (page changed, not signed in, whatever)."""


def port() -> int:
    return int(os.environ.get("CLASSROOM_CDP_PORT", "9351"))


def email() -> str:
    """The pinned school account, for display."""
    return cprofile.expected_account()


def _browser():
    try:
        browser = cprofile.Browser(port=port())
        browser.json("/json/version")
        return browser
    except Exception:                             # noqa: BLE001
        try:
            return cprofile.launch(headed=False, url="https://classroom.google.com/h")
        except ClassroomError as e:
            raise SessionError(
                f"{e}\nIf you haven't signed in yet, run: classroom login") from e


def _close_target(browser, target_id: str) -> None:
    if not target_id:
        return
    try:
        browser.json(f"/json/close/{target_id}")
    except Exception:                             # noqa: BLE001
        pass


@contextlib.contextmanager
def tab(url: str = "https://classroom.google.com/h", settle: float = 3.0):
    """Open a tab, verify the account, yield (tab, identity), always close it."""
    browser = _browser()
    target = browser.open_tab(url)
    target_id = (target or {}).get("id", "")
    tb = None
    try:
        time.sleep(0.6)
        # Chrome may swap the target during the first navigation.
        resolved = None
        for t in browser.tabs():
            if t.get("type") == "page" and t.get("id") == target_id:
                resolved = t
                break
        if resolved is None:
            pages = [t for t in browser.tabs() if t.get("type") == "page"]
            resolved = pages[-1] if pages else target
            target_id = (resolved or {}).get("id", target_id)
        tb = cdp.Tab(browser, resolved).connect()
        tb.navigate(url, wait=settle)
        try:
            ident = identity.verify(tb)
        except NotSignedIn as e:
            raise SessionError(f"not signed in: {e}\nrun: classroom login") from e
        except WrongAccount as e:
            raise SessionError(f"refusing to continue: {e}") from e
        # The guard reads the address from myaccount.google.com, so put the
        # tab back where the caller asked for.
        if url and url.split("#")[0] not in (tb.url() or ""):
            tb.navigate(url, wait=settle)
        yield tb, ident
    finally:
        if tb is not None:
            try:
                tb.close()
            except Exception:                     # noqa: BLE001
                pass
        _close_target(browser, target_id)


def close_strays() -> int:
    """Close leftover automation tabs from earlier runs (classroom's included).

    Tabs pile up when a process dies mid-run; they slow every later lookup and
    eventually make the CDP socket time out.
    """
    browser = _browser()
    hosts = ("mail.google.com", "drive.google.com", "docs.google.com",
             "calendar.google.com", "myaccount.google.com")
    closed = 0
    for t in browser.tabs():
        if t.get("type") != "page":
            continue
        url = t.get("url") or ""
        if any(h in url for h in hosts):
            _close_target(browser, t.get("id", ""))
            closed += 1
    return closed
