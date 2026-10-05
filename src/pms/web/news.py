"""What a new statement brought, and where to look first.

The routine is monthly: drop a PDF in inbox/, run run.bat, look. The app opens
on the month in progress; for a week after an import that added movements, the
dashboard says a new statement came in and links to the last whole month it
covers -- where the monthly review says what changed.
"""

from __future__ import annotations

import datetime as dt

from .. import analysis, plans

FRESH_DAYS = 7          # how long the dashboard mentions the new statement


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
