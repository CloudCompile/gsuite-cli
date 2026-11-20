# gsuite

[![tests](https://github.com/CloudCompile/gsuite-cli/actions/workflows/tests.yml/badge.svg)](https://github.com/CloudCompile/gsuite-cli/actions/workflows/tests.yml)

Four CLIs for your **school Google account** — Gmail, Drive, Docs and
Calendar. The school won't let you create OAuth clients, so these don't use
OAuth at all: they reuse the Chrome profile that is already signed in.

```
gmail list [-n N] [--unread]      # inbox via the Atom feed
gmail search QUERY                # full Gmail search syntax
gmail read ID [--link]            # message text
gmail send TO -s SUBJ [-b BODY]   # asks; --yes to send immediately
gmail archive ID                  # out of the inbox
gmail mark-read ID [--unread]

gdrive ls [-p my-drive|shared-with-me|starred|recent|FOLDER_ID]
gdrive find NAME
gdrive cat FILE_ID                # Docs/PDFs/text — full text extraction

gdocs recent                      # recently modified documents
gdocs find NAME                   # documents only (no sheets/PDFs)
gdocs cat FILE_ID

gcal agenda [--start YYYY-MM-DD] [--days N]
gcal today

gmail clean | gdrive clean | gdocs clean | gcal clean   # close leaked tabs
```

Every read command takes `--json`. Ids are always printed in full, since an
id is what you paste back into `read`/`cat` — a shortened id is a trap. An id
that genuinely can't be resolved prints as `—` rather than a plausible-looking
fake, and `--json` carries each message's permalink for `read --link`.

## One session, not four logins

All four share [classroom-cli](https://github.com/CloudCompile/classroom-cli)'s
Chrome profile, CDP driver and identity guard (checkout at `~/classroom` by
default, or set `CLASSROOM_HOME`).
A session is verified as the pinned school account (`~/.config/classroom/config`)
**before any service is read**. If the personal Gmail is in that profile, every
command stops rather than showing the wrong account's mail.

Each run opens its own tab and closes it again. Gmail/Drive/Calendar redirect
so often that classroom's "find the one work tab by its URL marker" approach
loses track, and a leaked tab per run eventually starves the CDP connection —
hence `clean`, which sweeps leftover mail/drive/calendar tabs.

If Chrome isn't running, a headless one starts automatically. First sign-in is
still `classroom login`.

## How each one works

- **Gmail listing** — `/mail/u/0/feed/atom/`, a documented Atom feed: XML with
  title/sender/date, no DOM scraping. Its `message_id` is not a thread id, so
  `read` resolves it back through the feed's permalink.
- **Gmail search** — the UI, because the feed only covers the inbox. Result
  rows carry the real thread id inside a base64 `jslog` blob (field `41:`).
- **Gmail send** — fills compose and asks before sending; `--yes` skips the
  prompt. A send that leaves the compose window open is reported as a failure.
- **Gmail archive** — removes the thread's Inbox label, then proves it by
  searching `in:inbox` for the thread; a click that silently didn't take is
  reported as a failure rather than "archived".
- **Gmail mark-read** — done from the search list, where Gmail exposes the
  state as a row class (`zE` = unread) and a selected row enables the toolbar
  button, so the change can be verified. It is idempotent: if the thread is
  already in the wanted state, nothing is clicked.
- **Drive** — `drive.google.com/file/<id>/view` renders view-only files as real
  text. Google's own `/export?format=txt` and `/preview` return an empty model
  for teacher files, which is why this route matters.
- **Docs** — the Docs home page is a JS grid with no stable ids, so documents
  are found through Drive search (`type:document`), reusing the Drive rows.
- **Calendar** — the rendered agenda view. If the calendar is nearly empty
  the reader reports that honestly rather than inventing a school timetable. The agenda exposes it twice (short chip + detailed card),
  so the two are merged into one row with the short name and the real date.

## Why this works when the API doesn't

OAuth isn't available to you, and Classroom's internal API uses opaque RPC
ids. The browser already has a valid session for all four services, so driving
it avoids both. The trade-off: UI-based reads break when Google changes a
layout, which is why the feed/XML path is preferred wherever it exists.

Four Gmail behaviours are encoded in the code because each one silently
returns the wrong answer otherwise:

1. A fragment-only navigation doesn't re-run a search; the query box updates
   before the rows swap, so `search` waits for both to agree.
2. The page holds a second, hidden copy of the message list and toolbar —
   selectors are scoped to `[role="main"]` and require visibility.
3. Gmail ignores programmatic `element.click()` on its toolbar; mutations
   dispatch real CDP mouse events.
4. Google enforces Trusted Types here, so injected scripts use
   `textContent` rather than `innerHTML`.

## Tests

37 offline tests: Atom feed parsing, the `jslog` thread-id decoder, search
settling (including the stale-results regression), Drive name cleanup,
calendar label/date parsing and event merging, CLI wiring, and early input
validation.

## Install

```console
$ ./install.sh
```

Installs into `~/.venv-gsuite` and symlinks `gmail`, `gdrive`, `gdocs` and
`gcal` into `~/.local/bin`.

## See also

- [skyward-cli](https://github.com/CloudCompile/skyward-cli) — grades and assignments from the gradebook
- [msl-cli](https://github.com/CloudCompile/msl-cli) — the MyStudyLife planner, including the sync that fills it
- [classroom-cli](https://github.com/CloudCompile/classroom-cli) — Classroom posts, classwork and attachments
- [agenda-cli](https://github.com/CloudCompile/agenda-cli) — all of the above in one view
- [gsuite-cli](https://github.com/CloudCompile/gsuite-cli) — the school Google account's mail, drive, docs and calendar

## License

MIT — see [LICENSE](LICENSE).
