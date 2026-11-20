"""Gmail for the school account.

Two access paths, deliberately:

* **Listing** uses `/mail/u/0/feed/atom/`, the documented Atom feed: stable XML
  with title, sender and date, no DOM scraping.
* **Everything else** (search, reading a thread, send, archive) drives the UI,
  because the feed only covers the newest inbox messages.

Gmail quirks that each cost a debugging session:

1. The feed's `message_id` is not a thread id: `#all/<id>` opens nothing. Its
   permalink does work, so `Message` carries both and `read` resolves the id
   back through the feed.
2. A fragment-only navigation does not re-run a search. The query box updates
   immediately but the rows swap in asynchronously, so waiting for "rows
   exist" reads the *previous* query. `_settle_search` waits for the box and
   rows to agree.
3. The page contains a second, hidden copy of the mail list and of the
   toolbar. Reading `tr.zA` or `[aria-label^="Archive"]` without scoping finds
   those instead — hence `[role="main"]` and visibility checks everywhere.
4. Programmatic `element.click()` is ignored by Gmail's toolbar handlers; it
   wants real pointer events. Mutations dispatch CDP mouse events at the
   element's on-screen centre and then verify the result from page state.

An id that cannot be resolved is left empty rather than hashed into something
plausible: a fabricated id is worse than a missing one, because `read` and
`archive` accept it and then quietly do nothing.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from .session import SessionError

ATOM_NS = {"a": "http://purl.org/atom/ns#"}
BASE = "https://mail.google.com/mail/u/0/"

FEED_JS = """(async () => {
  const res = await fetch('/mail/u/0/feed/atom/', {credentials: 'include'});
  return {status: res.status, body: await res.text()};
})()"""

READ_JS = r"""(() => {
  const text = el => (el ? (el.innerText || '') : '');
  const subject = document.querySelector('h2.hP') || document.querySelector('h2');
  const bodies = [...document.querySelectorAll('div.a3s')].map(text).filter(t => t.trim());
  const froms = [...document.querySelectorAll('span.gD')]
    .map(e => e.getAttribute('email') || text(e).trim()).filter(Boolean);
  return {
    url: location.href,
    subject: subject ? text(subject).trim() : '',
    bodies: bodies.map(b => b.replace(/\u00a0/g, ' ').trim()),
    froms,
    signed_out: /accounts\.google\.com/.test(location.href),
  };
})()"""

SEARCH_STATE_JS = r"""(() => {
  const box = document.querySelector('input[name="q"]');
  // Scope to the main pane: Gmail keeps a second, stale list of rows outside
  // it, and reading those returns the wrong messages entirely.
  const rows = [...document.querySelectorAll('[role="main"] tr.zA')];
  return {
    query: box ? box.value : null,
    rows: rows.length,
    first: rows.length ? ((rows[0].querySelector('.bog') || {}).innerText || '').trim() : '',
    matched_nothing: /did not match any messages|No messages matched/i
      .test(document.body.innerText || ''),
  };
})()"""

SEARCH_ROWS_JS = r"""(limit => [...document.querySelectorAll('[role="main"] tr.zA')]
  .slice(0, limit).map(tr => ({
    jslog: tr.getAttribute('jslog') || '',
    subject: ((tr.querySelector('.bog') || {}).innerText || '').trim(),
    snippet: ((tr.querySelector('.y2') || {}).innerText || '').trim(),
    sender: tr.querySelector('.yW span')
      ? tr.querySelector('.yW span').getAttribute('email') || ''
      : '',
    when: tr.querySelector('.xW')
      ? tr.querySelector('.xW').getAttribute('title')
        || ((tr.querySelector('.xW span') || {}).innerText || '').trim()
      : '',
  })))"""

ROW_LIST_JS = r"""(() => [...document.querySelectorAll('[role="main"] tr.zA')].map(tr => ({
  jslog: tr.getAttribute('jslog') || '',
  cls: tr.className || '',
  subject: ((tr.querySelector('.bog') || {}).innerText || '').trim(),
})))()"""

_ROW_FIND = r"""
  const rows = [...document.querySelectorAll('[role="main"] tr.zA')];
  const row = rows.find(r => ((r.querySelector('.bog') || {}).innerText || '').trim() === want);
"""

ROW_CHECKBOX_JS = r"""((want) => {""" + _ROW_FIND + r"""
  if (!row) return null;
  const box = row.querySelector('div[role="checkbox"], span[role="checkbox"]');
  if (!box) return null;
  const rect = box.getBoundingClientRect();
  return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
})"""

ROW_STATE_JS = r"""((want) => {""" + _ROW_FIND + r"""
  if (!row) return null;
  return {unread: /\bzE\b/.test(row.className || '')};
})"""


@dataclass
class Message:
    id: str
    subject: str
    sender: str
    email_addr: str
    when: str
    snippet: str = ""
    link: str = ""          # permalink that opens the message as-is

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "subject": self.subject, "from": self.sender,
                "email": self.email_addr, "when": self.when,
                "snippet": self.snippet, "link": self.link}


@dataclass
class Thread:
    subject: str
    bodies: list[str] = field(default_factory=list)
    senders: list[str] = field(default_factory=list)
    url: str = ""

    @property
    def text(self) -> str:
        return "\n\n".join(self.bodies)

    def to_dict(self) -> dict[str, Any]:
        return {"subject": self.subject, "senders": self.senders,
                "bodies": self.bodies, "url": self.url}


# ── listing (Atom feed) ──────────────────────────────────────────────────

def parse_feed(xml_text: str) -> list[Message]:
    """Atom feed -> messages, newest first."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise SessionError(f"Gmail feed was not valid XML (signed out?): {e}")
    out = []
    for entry in root.findall("a:entry", ATOM_NS):
        title = entry.findtext("a:title", default="", namespaces=ATOM_NS) or ""
        sender = entry.findtext("a:author/a:name", default="", namespaces=ATOM_NS) or ""
        email_addr = entry.findtext("a:author/a:email", default="", namespaces=ATOM_NS) or ""
        when = entry.findtext("a:issued", default="", namespaces=ATOM_NS) or ""
        link_el = entry.find("a:link", ATOM_NS)
        link = link_el.get("href", "") if link_el is not None else ""
        summary = entry.findtext("a:summary", default="", namespaces=ATOM_NS) or ""
        # The message id identifies the entry and is what `read` resolves back
        # to this permalink; it is not itself navigable.
        m = re.search(r"[?&]message_id=([0-9a-f]{10,})", link or "")
        out.append(Message(id=m.group(1) if m else "",
                           subject=re.sub(r"\s+", " ", title).strip()[:160],
                           sender=sender.strip(), email_addr=email_addr.strip(),
                           when=when.strip(),
                           snippet=re.sub(r"\s+", " ", summary).strip()[:280],
                           link=link))
    return out


def list_inbox(tab, limit: int = 20) -> list[Message]:
    tab.navigate(BASE, wait=4)
    res = tab.js(FEED_JS) or {}
    if res.get("status") != 200:
        raise SessionError(f"Gmail feed returned {res.get('status')}; session may have expired")
    return parse_feed(res.get("body") or "")[:limit]


# ── search ───────────────────────────────────────────────────────────────

def _thread_from_jslog(jslog: str) -> str:
    """Gmail embeds the real thread id in the row's base64 `jslog` blob.

    The `41:` field is unpadded base64url of a protobuf; the leading `W` is
    part of the encoding (it decodes to `[null,...`), not a type prefix, so it
    must not be stripped. The blob ends with `..`, which is not base64.
    """
    import base64

    m = re.search(r"41:([A-Za-z0-9+/=_-]{24,})", jslog or "")
    if not m:
        return ""
    raw = m.group(1)
    try:
        text = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace")
    except Exception:                         # noqa: BLE001
        return ""
    ids = re.findall(r"[A-Za-z0-9]{16,}", text)
    # First long token is the thread id (Ktbx...), second the message id.
    return ids[0] if ids else ""


def _settle_search(tab, query: str, timeout: float = 25.0) -> dict[str, Any]:
    """Wait until the rendered rows belong to *this* query."""
    deadline = time.monotonic() + timeout
    last: tuple[int, str] | None = None
    stable = 0
    state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        state = tab.js(SEARCH_STATE_JS) or {}
        # Gmail leaves a trailing space in the box after submitting a query.
        if (state.get("query") or "").strip() == query.strip() and \
                (state.get("rows") or state.get("matched_nothing")):
            marker = (int(state.get("rows") or 0), str(state.get("first") or ""))
            if marker == last:
                stable += 1
                if stable >= 2:
                    return state
            else:
                stable, last = 0, marker
        time.sleep(0.4)
    raise SessionError(
        f"search results for {query!r} never settled (box={state.get('query')!r}); "
        "Gmail may be slow or a layout change broke the reader")


def search(tab, query: str, limit: int = 20) -> list[Message]:
    """Gmail search via the UI; thread ids come from each row's jslog blob."""
    from urllib.parse import quote

    # Fragments don't reload the app, so leave the search view first.
    if "/#search/" in (tab.url() or ""):
        tab.navigate(f"{BASE}#inbox", wait=2)
    tab.navigate(f"{BASE}#search/{quote(query)}", wait=3)
    _settle_search(tab, query)
    rows = tab.js(f"({SEARCH_ROWS_JS})({int(limit)})") or []
    out = []
    for r in rows:
        tid = _thread_from_jslog(r.get("jslog", ""))
        subject = re.sub(r"\s+", " ", r.get("subject") or "").strip()
        out.append(Message(
            id=tid,
            subject=(subject or "(no subject)")[:160],
            sender="", email_addr=(r.get("sender") or "").strip(),
            when=(r.get("when") or "").strip(),
            snippet=re.sub(r"\s+", " ", r.get("snippet") or "").strip()[:280],
            link=f"{BASE}#all/{tid}" if tid else ""))
    return out


# ── opening a thread ─────────────────────────────────────────────────────

def _extract(tab) -> dict[str, Any]:
    """Read the currently open thread, or {} if none is rendered."""
    raw = tab.js(READ_JS) or {}
    if raw.get("signed_out"):
        raise SessionError("Gmail redirected to sign-in while reading")
    return raw if (raw.get("bodies") or []) else {}


def _open_thread(tab, message_id: str = "", link: str = "") -> dict[str, Any]:
    """Open a thread by real thread id, or by a feed permalink.

    Raises if nothing opens, so a mutation is never attempted against a page
    that isn't the intended conversation.
    """
    if link:
        tab.navigate(link, wait=4)
        raw = _extract(tab)
    elif re.fullmatch(r"[0-9a-zA-Z_-]{6,}", message_id or ""):
        tab.navigate(f"{BASE}#all/{message_id}", wait=5)
        raw = _extract(tab)
        if not raw:
            # Not a thread id: try it as a feed message id.
            matches = [m for m in list_inbox(tab, 100) if m.id == message_id]
            if not matches or not matches[0].link:
                raise SessionError(
                    f"{message_id!r} is not an openable thread id; use an id "
                    "from `gmail search`, or pass --link")
            tab.navigate(matches[0].link, wait=4)
            raw = _extract(tab)
    else:
        raise SessionError(f"{message_id!r} doesn't look like a Gmail thread id")
    if not raw:
        raise SessionError("opened the message but found no body text (layout changed?)")
    return raw


def read(tab, message_id: str = "", link: str = "") -> Thread:
    """Open a message/thread and pull out its text."""
    raw = _open_thread(tab, message_id, link)
    return Thread(subject=raw.get("subject") or "", bodies=raw.get("bodies") or [],
                  senders=raw.get("froms") or [], url=raw.get("url") or "")


# ── real pointer input ───────────────────────────────────────────────────

_FIND_VISIBLE = r"""((m) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const b = [...document.querySelectorAll('[role="button"], [role="menuitem"]')]
    .filter(vis)
    .find(e => ((e.getAttribute('aria-label') || '') + ' '
                + (e.innerText || '')).includes(m));
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return {x: r.x + r.width / 2, y: r.y + r.height / 2,
          label: (b.getAttribute('aria-label') || b.innerText || '').trim().slice(0, 60)};
})"""


def _rect(tab, needle: str) -> dict[str, Any] | None:
    return tab.js(_FIND_VISIBLE + "(" + repr(needle) + ")")


def _real_click(tab, needle: str) -> bool:
    """Click the first visible control whose label/text contains `needle`."""
    box = _rect(tab, needle)
    if not box:
        return False
    for kind in ("mousePressed", "mouseReleased"):
        tab.send("Input.dispatchMouseEvent", type=kind, x=box["x"], y=box["y"],
                 button="left", clickCount=1)
    return True


def _has(tab, needle: str) -> bool:
    return _rect(tab, needle) is not None


def _thread_id_of(tab) -> str:
    """The thread id Gmail is showing, taken from the address bar."""
    m = re.search(r"#(?:all|inbox|search/[^/]+)/([A-Za-z0-9_-]{12,})", tab.url() or "")
    return m.group(1) if m else ""


# ── mutating the thread ──────────────────────────────────────────────────

def _in_inbox(tab, thread_id: str, subject: str) -> bool | None:
    """Is this thread in the inbox right now? None if it can't be determined."""
    from urllib.parse import quote

    safe = (subject or "").replace('"', "").strip()
    if not safe:
        return None
    query = f'in:inbox subject:("{safe}")'
    tab.navigate(f"{BASE}#search/{quote(query)}", wait=3)
    try:
        _settle_search(tab, query)
    except SessionError:
        return None
    for row in tab.js(ROW_LIST_JS) or []:
        if thread_id:
            if _thread_from_jslog(row.get("jslog", "")) == thread_id:
                return True
        elif (row.get("subject") or "") == safe:
            return True
    return False


def archive(tab, message_id: str = "", link: str = "") -> bool:
    """Archive one thread and prove it left the inbox.

    The archive control in the open-thread view is the "Remove label Inbox
    from this conversation" chip, and the thread stays on screen afterwards.
    The chip vanishing is not proof — Gmail re-renders the header mid-click —
    so the outcome is checked with an `in:inbox` search for the thread itself.
    """
    raw = _open_thread(tab, message_id, link)
    thread_id = _thread_id_of(tab)
    subject = (raw.get("subject") or "").strip()

    for _ in range(2):
        if not _has(tab, "Remove label Inbox"):
            break
        _real_click(tab, "Remove label Inbox")
        time.sleep(2.0)

    state = _in_inbox(tab, thread_id, subject)
    if state is None:
        return not _has(tab, "Remove label Inbox")
    return state is False


def mark_read(tab, message_id: str = "", link: str = "", read: bool = True) -> bool:
    """Mark a thread read/unread from the search list, then confirm.

    The open-thread menu is unreliable to drive (its items shift as menus open
    and close), but the search list gives a real signal: unread rows carry the
    `zE` class, and a selected row enables the toolbar's "Mark as read" /
    "Mark as unread" buttons. Act only if the state differs, verify after.
    """
    from urllib.parse import quote

    raw = _open_thread(tab, message_id, link)
    subject = (raw.get("subject") or "").strip()
    if not subject:
        raise SessionError("could not read the thread's subject, so its row "
                           "can't be located in the list")

    query = f'subject:("{subject.replace(chr(34), "")}")'
    tab.navigate(f"{BASE}#search/{quote(query)}", wait=3)
    _settle_search(tab, query)

    state = tab.js(f"({ROW_STATE_JS})({subject!r})")
    if not state:
        raise SessionError(f"no list row for {subject!r}")
    if bool(state.get("unread")) == (not read):
        return True                            # already in the wanted state

    box = tab.js(f"({ROW_CHECKBOX_JS})({subject!r})")
    if not box:
        raise SessionError("found the row but not its checkbox")
    for kind in ("mousePressed", "mouseReleased"):
        tab.send("Input.dispatchMouseEvent", type=kind, x=box["x"], y=box["y"],
                 button="left", clickCount=1)
    time.sleep(1.0)
    if not _real_click(tab, "Mark as read" if read else "Mark as unread"):
        raise SessionError("selected the row but the read/unread button did not "
                           "appear in the toolbar")
    for _ in range(8):
        time.sleep(0.6)
        now = tab.js(f"({ROW_STATE_JS})({subject!r})")
        if now and bool(now.get("unread")) == (not read):
            return True
    return False


# ── writing ──────────────────────────────────────────────────────────────
#
# Sending is the one irreversible action here, so `compose` never sends and
# the CLI asks before calling `fill_and_send`. Gmail enforces Trusted Types:
# the body is set with textContent, since innerHTML throws.

COMPOSE_URL = "https://mail.google.com/mail/u/0/#inbox?compose=new"

FILL_JS = r"""((args) => {
  const set = (el, value) => {
    if (!el) return false;
    el.focus();
    if (el.isContentEditable) {
      el.textContent = value;
    } else {
      el.value = value;
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
    }
    return true;
  };
  const to = document.querySelector('input[peoplekit-id], textarea[name="to"], input[aria-label="To recipients"]');
  const subject = document.querySelector('input[name="subjectbox"]');
  const body = document.querySelector('div[aria-label="Message Body"], div[role="textbox"][contenteditable="true"]');
  return {to: set(to, args.to), subject: set(subject, args.subject), body: set(body, args.body)};
})"""


def compose(tab, to: str, subject: str, body: str) -> dict[str, Any]:
    """Open a compose window and fill it in. Does NOT send."""
    import json as _json

    tab.navigate(COMPOSE_URL, wait=5)
    tab.wait_for("""document.querySelector('input[name="subjectbox"]')""", timeout=20)
    filled = tab.js(f"({FILL_JS})({_json.dumps({'to': to, 'subject': subject, 'body': body})})")
    if not (filled or {}).get("to"):
        raise SessionError("could not fill the To field (compose layout changed?)")
    return {"to": to, "subject": subject, "body": body, "filled": filled}


def fill_and_send(tab, to: str, subject: str, body: str, *, wait_after: float = 4.0) -> dict[str, Any]:
    info = compose(tab, to, subject, body)
    if not _real_click(tab, "Send"):
        raise SessionError("filled the message but could not find the Send button")
    time.sleep(wait_after)
    # A sent message closes its compose window; an open one means it didn't go.
    if tab.js("""!!document.querySelector('input[name="subjectbox"]')"""):
        raise SessionError("Send was clicked but the compose window is still open; not sent")
    return {**info, "sent": True}
