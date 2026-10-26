"""Python values as JSON: dates as ISO strings, transactions as flat rows.

The analysis layer returns dicts of dates, Counters, tuples and dataclasses;
`jsonable` turns any of them into what `json.dumps` takes, so an endpoint
can hand the front end what the analysis computed without a serializer per
shape. A float that is not a number (a ratio over nothing) becomes null:
JSON has no NaN, and the browser's parser refuses the whole payload over one.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
from collections.abc import Mapping

from ...models import Statement, Transaction
from ...overrides import key_of


def tx(t: Transaction) -> dict:
    """One row as every table of the front end reads it."""
    return {
        "key": key_of(t),
        "date": t.date.isoformat(),
        "seq": t.seq,
        "label": t.label,
        "merchant": t.merchant,
        "location": t.location,
        "kind": t.kind,
        "detail": t.detail,
        "category": t.category,
        "subcategory": t.subcategory,
        "bucket": t.bucket,
        "amount": t.amount,
        "currency": t.currency,
        "chf": round(t.amount_chf, 2),
        "account": t.account,
        "overridden": t.overridden,
    }


def jsonable(value):
    if isinstance(value, Transaction):
        return tx(value)
    if isinstance(value, Statement):
        # Never shipped whole: thousands of rows nobody asked for.
        return {"start": value.period_start.isoformat(),
                "end": value.period_end.isoformat(),
                "count": len(value.transactions)}
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {_key(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return jsonable(dataclasses.asdict(value))
    return value


def _key(key) -> str:
    if isinstance(key, (dt.date, dt.datetime)):
        return key.isoformat()
    return str(key)
