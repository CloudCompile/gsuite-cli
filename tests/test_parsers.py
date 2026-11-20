"""Parser tests: feed XML, Drive row text, calendar labels, event dates.

All offline. The samples are captured shapes from the live pages.
"""
from datetime import date

import pytest

from gsuite import calendar as gcal
from gsuite import drive, mail

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed version="0.3" xmlns="http://purl.org/atom/ns#">
 <title>Gmail - Inbox for student@school.example</title>
 <entry>
  <title>Science Quiz question</title>
  <summary>Dear Ms. Rivera, Ill be gone next week</summary>
  <link rel="alternate" type="text/html"
        href="https://mail.google.com/mail/u/0?account_id=x&amp;message_id=1a1f09a0ff1d80ef&amp;view=conv&amp;extsrc=atom"
        title="Science Quiz question"/>
  <author><name>Sam Doe</name><email>student@school.example</email></author>
  <issued>2026-11-18T22:19:07Z</issued>
 </entry>
 <entry>
  <title>Week 13 schedule posted</title>
  <link rel="alternate" href="https://mail.google.com/mail/u/0?message_id=abc123&amp;view=conv" />
  <author><name>Rivera, Alex</name><email>rivera@school.example</email></author>
  <issued>2026-11-16T14:02:00Z</issued>
 </entry>
</feed>"""


def test_parse_feed_fields():
    msgs = mail.parse_feed(FEED)
    assert len(msgs) == 2
    m = msgs[0]
    assert m.subject == "Science Quiz question"
    assert m.sender == "Sam Doe"
    assert m.email_addr == "student@school.example"
    assert m.when.startswith("2026-11-18T22:19")
    assert "next week" in m.snippet


def test_parse_feed_link_is_a_permalink():
    """The message_id is NOT a thread id; reading must use the link."""
    m = mail.parse_feed(FEED)[1]
    assert "view=conv" in m.link


def test_parse_feed_rejects_non_xml():
    with pytest.raises(mail.SessionError):
        mail.parse_feed("<html>signed out</html")


def test_parse_feed_empty():
    empty = '<feed xmlns="http://purl.org/atom/ns#"><title>x</title></feed>'
    assert mail.parse_feed(empty) == []


# ── drive ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Week 13: 11-16-26 me Nov 16, 2026 More actions (Alt+A)", "Week 13: 11-16-26"),
    ("ORCHESTRA me Sep 9, 2025 — More actions", "ORCHESTRA"),
    ("OBX '25 me Oct 4, 2025 — More actions (Alt+A)", "OBX '25"),
    ("Week 13: 11-16-26 Belongs to a shared drive Nov 16", "Week 13: 11-16-26"),
    ("New folder me Sep 22, 2025 — More actions", "New folder"),
    ("Notes-19-11-2026.txt 8:33 PM", "Notes-19-11-2026.txt"),
    ("Week 13: 11-16-26 9:12 AM", "Week 13: 11-16-26"),
])
def test_clean_name(raw, expected):
    assert drive.clean_name(raw) == expected


def test_clean_name_keeps_dates_in_the_name():
    # a date inside the document's own title must survive
    assert drive.clean_name("Week 8: 10-12-2026 me Oct 12, 2025") == "Week 8: 10-12-2026"


def test_read_rejects_bad_id():
    with pytest.raises(mail.SessionError):
        drive.read(None, "not-an-id")


def test_file_entry_url():
    assert drive.FileEntry(id="abc123def456ghi789", name="x").url.endswith("/abc123def456ghi789/view")


# ── calendar ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label,text,expected", [
    ("All day, Dentist, Sam Doe, No location, December 16, 2026", "Dentist", "Dentist"),
    ("9:30 to 10am, Geometry class, Room 212", "Geometry class", "Geometry class"),
    ("All day, Assembly, Accepted", "Assembly", "Assembly"),
    ("", "All day Dentist appointment Sam Doe, Accepted", "Dentist appointment"),
])
def test_clean_summary(label, text, expected):
    assert gcal._clean_summary(label, text) == expected


def test_clean_summary_handles_junk():
    assert gcal._clean_summary("", "") == ""
    assert gcal._clean_summary("No location", "No location").lower() in ("no location", "")


def test_when_extracts_date():
    when, day = gcal._when(
        "All day, Dentist, Sam Doe, No location, December 16, 2026", "Dentist")
    assert day == date(2026, 12, 16)
    assert "December 16" in when


def test_when_extracts_time_range():
    when, day = gcal._when("9:30 to 10am, Geometry", "")
    assert "9:30" in when
    assert day is None


def test_when_all_day():
    assert gcal._when("All day, Holiday", "")[0] == "All day"


def test_thread_from_jslog():
    # Real value captured from a search row; note the leading `W` is data and
    # the blob ends with `..` which is not base64.
    blob = ("18406; u014N:xr6bB,SYhH9d; 41:W251bGwsbnVsbCxudWxsLG51bGwsW251bGwsIkt0YnhMd0du"
            "TXd3S0ZEdmZyUU1sTEJzbW5NSmpyZHhaR3EiLDEsbnVsbCwiMWExZjBiZjdmYjExMGU5NyJd"
            "LG51bGwsbnVsbCxudWxsLG51bGwsbnVsbCxudWxsLG51bGwsbnVsbCxudWxsLG51bGwsbnVs"
            "bCxudWxsLG51bGwsbnVsbCxudWxsLG51bGwsWzBdXQ..")
    assert mail._thread_from_jslog(blob) == "KtbxLwGnMwwKFDvfrQMlLBsmnMJjrdxZGq"


def test_thread_from_jslog_missing():
    assert mail._thread_from_jslog("") == ""
    assert mail._thread_from_jslog("41:not-base64") == ""


# ── search settling ──────────────────────────────────────────────────────
# Regression tests: Gmail updates the query box before it swaps the result
# rows, and a hash-only navigation doesn't reload. Reading rows too early
# returned the previous query's messages.

class _ScriptedTab:
    """Returns a fixed sequence of search states, one per probe."""

    def __init__(self, states):
        self.states = list(states)
        self.seen = 0

    def js(self, _script):
        state = self.states[min(self.seen, len(self.states) - 1)]
        self.seen += 1
        return state


def test_settle_search_waits_for_matching_rows():
    tab = _ScriptedTab([
        {"query": "subject:old ", "rows": 3, "first": "Old A"},
        {"query": "subject:new ", "rows": 0, "first": ""},
        {"query": "subject:new ", "rows": 2, "first": "New B"},
        {"query": "subject:new ", "rows": 2, "first": "New B"},
        {"query": "subject:new ", "rows": 2, "first": "New B"},
    ])
    state = mail._settle_search(tab, "subject:new", timeout=5)
    assert state["rows"] == 2
    assert state["first"] == "New B"
    # It must not have accepted the stale first state.
    assert tab.seen > 2


def test_settle_search_raises_when_query_never_lands():
    tab = _ScriptedTab([{"query": "subject:old ", "rows": 3, "first": "Old A"}])
    with pytest.raises(mail.SessionError):
        mail._settle_search(tab, "subject:new", timeout=0.6)


def test_settle_search_accepts_no_results():
    tab = _ScriptedTab([{"query": "subject:none", "rows": 0, "matched_nothing": True}])
    state = mail._settle_search(tab, "subject:none", timeout=5)
    assert state["matched_nothing"] is True


def test_search_rows_do_not_invent_ids():
    """A row without a jslog blob must yield an empty id, never a hash.

    A fabricated id is accepted by `read` and `archive` and then silently
    operates on nothing, which is how an earlier archive "succeeded" without
    archiving anything.
    """
    row = {"jslog": "", "subject": "Some subject", "when": "10:23 PM", "sender": "", "snippet": ""}
    assert mail._thread_from_jslog(row["jslog"]) == ""
