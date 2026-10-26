"""What a new statement brought, and where to look first.

The routine is monthly: drop a PDF in inbox/, run run.bat, look. The app opens
on the month in progress; for a week after an import that added movements, the
dashboard says a new statement came in and links to the last whole month it
covers -- where the monthly review says what changed.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from .. import analysis, banks, plans

FRESH_DAYS = 7          # how long the dashboard mentions the new statement
# When a bank's newest statement is old enough to ask for the next one. The
# routine is monthly; two weeks is half a month nobody has looked at.
LATE_DAYS = 14


def late(sources: list[dict], today: dt.date) -> list[dict]:
    """Each bank whose newest statement stopped more than LATE_DAYS ago.

    Read from the import log, by the account each import fed, and from the
    period the statement covers -- not the date of its last movement: a quiet
    week is not a late statement. An export that prints no period (Revolut's
    CSV) covers at least up to the day it was imported: its account had
    simply not moved since its last row. A bank never imported is not late
    either: it is not one the user has.
    """
    def day(value):
        return dt.date.fromisoformat(value[:10]) if value else None

    out = []
    for pattern, bank in banks.BANKS.items():
        ends = []
        for s in sources:
            if (s.get("account") or "") != bank.account:
                continue
            # Several banks feed the primary account: the import says which
            # (`bank`, UBS); else its file's extension does, read as the first
            # bank of the account taking it (Swissquote for a PDF, camt.053
            # for XML). An import that names no file is the account's first.
            if s.get("bank"):
                if s["bank"] != bank.name:
                    continue
            else:
                suffix = Path(s.get("file") or "").suffix.lower()
                first = next(p for p, b in banks.BANKS.items() if b.account == bank.account)
                suffix = suffix or Path(first).suffix.lower()
                owner = next((p for p, b in banks.BANKS.items()
                              if b.account == bank.account and Path(p).suffix.lower() == suffix), None)
                if owner != pattern:
                    continue
            covered = [day(s.get("period_end"))]
            if not bank.prints_period:
                covered.append(day(s.get("ingested_at")))
            ends += [d for d in covered if d]
        if not ends:
            continue
        until = max(ends)
        days = (today - until).days
        if days > LATE_DAYS:
            out.append({"bank": bank.name, "until": until, "days": days, "url": bank.url})
    return out


def latest_import(sources: list[dict]) -> dict | None:
    dated = [s for s in sources if s.get("ingested_at")]
    return max(dated, key=lambda s: s["ingested_at"]) if dated else None


def last_whole_month(high: dt.date) -> tuple[dt.date, dt.date]:
    """The last calendar month the ledger covers entirely: the review of a
    month in progress would be about a third of a month."""
    first, last = analysis.bucket_bounds(high, "month")
    if high == last:
        return first, last
    return analysis.bucket_bounds(first - dt.timedelta(days=1), "month")


def news(sources: list[dict], high: dt.date,
         now: dt.datetime | None = None) -> dict | None:
    """The newest import, when it is fresh and brought something.

    A re-read of a known file (`--reparse`) refreshes its log entry and keeps
    the rows it first added; it is maintenance, not news, so an entry that
    says `reimported` does not count.
    """
    latest = latest_import(sources)
    if not latest or not latest.get("added") or latest.get("reimported"):
        return None
    when = dt.datetime.fromisoformat(latest["ingested_at"])
    now = now or dt.datetime.now()
    if now - when > dt.timedelta(days=FRESH_DAYS):
        return None
    start, end = last_whole_month(high)
    return {
        "file": latest.get("file", ""),
        # What a dismissal remembers: the import itself. The digest, or its
        # timestamp when the import had no file behind it.
        "id": latest.get("sha256") or latest["ingested_at"],
        "added": latest["added"], "when": when, "until": high,
        "start": start, "end": end,
        "label": plans.month_label(start.strftime("%Y-%m")),
    }
