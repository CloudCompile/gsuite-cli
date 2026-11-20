"""Google Drive and Docs for the school account.

Reading files reuses the trick that already works for Classroom attachments:
`drive.google.com/file/<id>/view` renders the document as real text, whereas
Docs' own export/preview routes return an empty model for view-only files.

Listing scrapes the Drive grid DOM, which is the weak point. It keys on
`[data-id]` file rows — the same attribute Classroom attachments rely on — and
reports nothing rather than guessing when the layout changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .session import SessionError

DRIVE = "https://drive.google.com/drive"
VIEW = "https://drive.google.com/file/d/{}/view"
DOC = "https://docs.google.com/document/d/{}"
MAX_FILE = 2_000_000                     # chars; a runaway read is a bug

JS_ROWS = r"""(() => {
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('[data-id]')) {
    const id = el.getAttribute('data-id');
    if (!id || seen.has(id) || id.length < 15) continue;
    const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
    if (!text) continue;
    seen.add(id);
    const kind = el.getAttribute('data-tooltip') || '';
    out.push({id, text: text.slice(0, 200), kind});
  }
  return out;
})()"""

JS_TEXT = r"""(() => {
  const blocks = [...document.querySelectorAll('div,span')]
    .map(el => ({n: (el.innerText || '').length, el}))
    .filter(x => x.n > 200)
    .sort((a, b) => b.n - a.n);
  return {
    url: location.href,
    title: (document.title || '').replace(/\s*-\s*Google (Drive|Docs|Sheets|Slides)$/, '').trim(),
    text: blocks.length ? blocks[0].el.innerText : (document.body.innerText || ''),
    signed_out: /accounts\.google\.com/.test(location.href),
  };
})()"""

_NOISE = re.compile(
    r"^(Move|File|View|Tools|Help|More|Open with|Share|Page|/\s*$|"
    r"Printing not yet available|Full screen|Zoom out|Zoom in|Page zoom control|"
    r"Hide file header|Page \d+ of \d+|Skip to main content|Rename|Add shortcut|"
    r"OpenCloudConvert.*|Details|Security limitations.*|"
    r"Open with [A-Za-z ]+)$")


@dataclass
class FileEntry:
    id: str
    name: str
    kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "kind": self.kind}

    @property
    def url(self) -> str:
        return VIEW.format(self.id)


def _clean(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines()]
    out: list[str] = []
    blank = False
    for ln in lines:
        if not ln:
            blank = True
            continue
        if _NOISE.match(ln):
            continue
        if blank and out:
            out.append("")
        blank = False
        out.append(ln)
    return "\n".join(out).strip()


_OWNER_DATE = re.compile(
    r"\s+(?:me|Shared|Belongs to)\b.*$|\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s*\d{0,4}.*$")
_CHROME = re.compile(r"\s*(?:More actions.*|Owner.*|Mine.*)$")
# Recent lists append a bare modified time ("Week 13: 11-16-26 9:12 AM").
_TRAILING_TIME = re.compile(r"\s+\d{1,2}:\d{2}\s*(?:AM|PM)$", re.I)


def clean_name(text: str) -> str:
    """Drive row text is "<name> <owner> <date> More actions"; keep the name."""
    s = (text or "").strip()
    s = _CHROME.sub("", s)
    s = _OWNER_DATE.sub("", s)
    s = _TRAILING_TIME.sub("", s)
    return s.strip()


def list_folder(tab, path: str = "my-drive", limit: int = 100) -> list[FileEntry]:
    tab.navigate(f"{DRIVE}/{path}", wait=5)
    tab.wait_for("""document.querySelectorAll('[data-id]').length > 0
                    || /is empty|No items/.test(document.body.innerText)""", timeout=25)
    rows = tab.js(JS_ROWS) or []
    out, seen = [], set()
    for r in rows:
        if r["id"] in seen:
            continue
        name = clean_name(r.get("text", ""))
        if not name:
            continue
        seen.add(r["id"])
        out.append(FileEntry(id=r["id"], name=name, kind=r.get("kind", "")))
    return out[:limit]


def search(tab, query: str, limit: int = 25) -> list[FileEntry]:
    from urllib.parse import quote

    tab.navigate(f"{DRIVE}/search?q={quote(query)}", wait=5)
    tab.wait_for("""document.querySelectorAll('[data-id]').length > 0
                    || /No items/.test(document.body.innerText)""", timeout=25)
    rows = tab.js(JS_ROWS) or []
    out, seen = [], set()
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        name = clean_name(r.get("text", ""))
        if name:
            out.append(FileEntry(id=r["id"], name=name, kind=r.get("kind", "")))
    return out[:limit]


def read(tab, file_id: str) -> tuple[str, str]:
    """Render a Drive file and return (title, text)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{15,}", file_id or ""):
        raise SessionError(f"{file_id!r} doesn't look like a Drive file id")
    tab.navigate(VIEW.format(file_id), wait=5)
    tab.wait_for("""document.body && document.body.innerText.length > 200""", timeout=25)
    raw = tab.js(JS_TEXT) or {}
    if raw.get("signed_out"):
        raise SessionError("Drive redirected to sign-in while reading the file")
    text = _clean(raw.get("text") or "")
    if not text:
        raise SessionError(f"no text could be read from {file_id} (image-only or unshared?)")
    title = (raw.get("title") or "").strip()
    # The preview renders the filename as a header, so the first line usually
    # repeats the title; drop the echo but keep the real content.
    lines = text.splitlines()
    while lines and title and lines[0].strip() == title:
        lines.pop(0)
    return title, "\n".join(lines).strip()[:MAX_FILE]


def find_by_name(tab, name: str, limit: int = 25) -> list[FileEntry]:
    """Search Drive for files whose name matches."""
    return [f for f in search(tab, name, limit) if name.lower() in f.name.lower()]
