"""Google Calendar for the school account.

Calendar has no public read endpoint available to this session (no iCal link
without visiting settings, and the CalDAV/API routes need OAuth), so events
are read from the rendered UI.

The useful, testable shape is the *agenda list* rather than a pixel grid: the
week view lists events per day, and the DOM exposes each event's summary and
time. Where Google renders nothing, this reports that plainly instead of
inventing an empty agenda.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .session import SessionError

CAL = "https://calendar.google.com/calendar/u/0/r"

# The agenda/schedule view is a plain list — far more stable than the grid.
JS_AGENDA = r"""(() => {
  const out = [];
  const nodes = [...document.querySelectorAll('[data-eventid], [data-eventchip]')];
  for (const el of nodes) {
    const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
    if (!text || /^Add location$/.test(text)) continue;
    out.push({
      id: el.getAttribute('data-eventid') || el.getAttribute('data-eventchip') || '',
      text: text.slice(0, 200),
      label: el.getAttribute('aria-label') || '',
    });
  }
  return out;
})()"""

JS_CALENDARS = r"""(() => {
  const out = new Set();
  for (const el of document.querySelectorAll('[data-calendar-id]')) {
    const id = el.getAttribute('data-calendar-id');
    if (id) out.add(id);
  }
  return [...out];
})()"""


@dataclass
class Event:
    summary: str
    when: str = ""
    day: date | None = None
    calendar: str = ""
    event_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"summary": self.summary, "when": self.when,
                "day": self.day.isoformat() if self.day else "",
                "calendar": self.calendar, "id": self.event_id}


_LEAD = re.compile(r"^(?:All[ -]day|\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*(?:to|[–-])\s*[\d:]+\s*(?:am|pm)?)[,:]?\s*", re.I)
_TRAIL = re.compile(r"\s*,?\s*(?:No location|Accepted|Declined|Tentative|Busy|Free)\b.*$", re.I)


def _clean_summary(label: str, text: str) -> str:
    """The aria-label is "All day, Dentist, Sam Doe, No location, ...".

    Take the first segment that isn't a status/date/name echo.
    """
    src = (label or text or "").strip()
    src = _LEAD.sub("", src)
    parts = [p.strip() for p in src.split(",")]
    skip = re.compile(r"^(?:no location|accepted|declined|tentative|busy|free|"
                      r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d|"
                      r"\d{4})$", re.I)
    for part in parts:
        if part and not skip.match(part):
            # A chip rendered without a label reads "All day Dentist
            # Sam Doe, Accepted": keep just the short event title
            # and drop the trailing person/status detail.
            words = part.split()
            if not label and len(words) > 3:
                part = " ".join(words[:2])
            return part[:160]
    return (parts[0] if parts else "")[:160]


def agenda(tab, day: date | None = None, *, days: int = 7) -> list[Event]:
    """Events for a date range, read from the schedule view."""
    start = day or date.today()
    url = f"{CAL}/agenda?src=&dates={start.strftime('%Y%m%d')}"
    if days > 1:
        url += f"/{_ymd(start + timedelta(days=days - 1))}"
    tab.navigate(url, wait=6)
    tab.wait_for("""document.body && document.body.innerText.length > 100""", timeout=25)
    body = tab.js("document.body.innerText") or ""
    if "Calendar" not in body:
        raise SessionError("calendar did not render (session expired? wrong account?)")
    raw = tab.js(JS_AGENDA) or []
    out = []
    for r in raw:
        summary = _clean_summary(r.get("label", ""), r.get("text", ""))
        if not summary or summary.lower() == "add location":
            continue
        when, when_day = _when(r.get("label", ""), r.get("text", ""))
        out.append(Event(summary=summary, when=when, day=when_day,
                         event_id=r.get("id", "")))
    out.sort(key=lambda e: (e.day is None, e.day or date.max, len(e.summary), e.summary.lower()))
    # The agenda exposes one event twice: a short chip ("Dentist") and a
    # detailed card ("Dentist Sam Doe, ..., December 16, 2026").
    # Merge them so an event prints once, with whichever fields the richer
    # representation supplied.
    final: list[Event] = []
    for e in out:
        norm = re.sub(r"\W+", "", e.summary.lower())[:8]
        twin = None
        for kept in final:
            kn = re.sub(r"\W+", "", kept.summary.lower())[:8]
            if kn.startswith(norm) or norm.startswith(kn):
                twin = kept
                break
        if twin is None:
            final.append(e)
        else:
            if twin.day is None and e.day:
                twin.day = e.day
            if twin.when in ("", "All day") and e.when and not e.when.startswith("All day"):
                twin.when = e.when
    return final


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _when(label: str, text: str) -> tuple[str, date | None]:
    """Pull a human time and a date out of the event's label/text."""
    src = f"{label} {text}"
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2}),?\s*(\d{4})", src, re.I)
    if m:
        try:
            d = date(int(m.group(3)), _MONTHS[m.group(1).lower()[:3]], int(m.group(2)))
        except ValueError:
            d = None
        return m.group(0), d
    t = re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*(?:to|[–-])\s*\d{1,2}(?::\d{2})?\s*(?:am|pm))", src, re.I)
    return (t.group(1) if t else ("All day" if re.search(r"all.day", src, re.I) else "")), None


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def calendars(tab) -> list[str]:
    tab.navigate(f"{CAL}/week", wait=8)
    return tab.js(JS_CALENDARS) or []


def today(tab) -> list[Event]:
    return agenda(tab, date.today(), days=1)
