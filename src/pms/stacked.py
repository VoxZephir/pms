"""Is the stacked fund doing its job? (RSST, `docs/epargne.md`).

RSST promises, for each franc, a franc of US stocks *and* a franc of
managed futures (trend following). What it should return is therefore the
S&P 500 plus a managed-futures fund minus the cash rate that finances the
second franc:

    replica = r(S&P 500) + r(managed futures) - r(T-bills)

All three are read in francs, and the weights sum to one, so the franc's
move cancels exactly: (1+f)(1+a) + (1+f)(1+b) - (1+f)(1+c) - 1 equals
(1+f)(1+a+b-c) - 1, the USD replica converted. The same goes for the trend
leg the fund actually delivered, r(RSST) - r(S&P 500) + r(T-bills): the
fund with its stock franc taken out, back to a plain trend fund.

The managed-futures fund is a proxy (DBMF replicates the large CTAs; RSST
runs ReSolve's own trend model): a gap to the replica is the fund's fees
and its own model, not only a fault. The regression says which: a stock
beta near 1 says the stock franc is there, a trend beta and the trend leg's
correlation say how close its trend is to the industry's.

Daily US closes, all four, so a day's returns are the same moment.
"""

from __future__ import annotations

import datetime as dt
import math

FUND, STOCKS, TREND, CASH = "rsst", "sp500", "managed_futures", "tbill"
NEEDED = (FUND, STOCKS, TREND, CASH)
# Below this many daily returns, a volatility or a regression says nothing.
MIN_DAYS = 40
TRADING_DAYS = 252


def _returns(levels: list[float]) -> list[float]:
    return [b / a - 1 for a, b in zip(levels, levels[1:])]


def _cumulate(returns: list[float]) -> list[float]:
    out, level = [100.0], 100.0
    for r in returns:
        level *= 1 + r
        out.append(level)
    return out


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _std(xs: list[float]) -> float:
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _corr(xs: list[float], ys: list[float]) -> float | None:
    mx, my = _mean(xs), _mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    return cov / math.sqrt(vx * vy) if vx and vy else None


def _drawdown(levels: list[float]) -> float:
    peak, worst = levels[0], 0.0
    for v in levels:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def _annual(total: float, days: int) -> float | None:
    """A rate per year, only past a year: below, it extrapolates."""
    return (1 + total) ** (365.25 / days) - 1 if days >= 365 else None


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting, for the 3x3 normal
    equations; None when the system is singular."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-18:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in reversed(range(n)):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def regression(y: list[float], x1: list[float], x2: list[float]) -> dict | None:
    """y = alpha + b1·x1 + b2·x2 by least squares: the fund's excess return on
    the stocks' and the trend fund's. alpha is per year; r2 the share of the
    fund's daily moves the two explain."""
    n = len(y)
    rows = [(1.0, a, b) for a, b in zip(x1, x2)]
    xtx = [[sum(r[i] * r[j] for r in rows) for j in range(3)] for i in range(3)]
    xty = [sum(r[i] * v for r, v in zip(rows, y)) for i in range(3)]
    coef = _solve(xtx, xty)
    if coef is None:
        return None
    fitted = [coef[0] + coef[1] * a + coef[2] * b for a, b in zip(x1, x2)]
    my = _mean(y)
    total = sum((v - my) ** 2 for v in y)
    resid = sum((v - f) ** 2 for v, f in zip(y, fitted))
    return {"alpha_pa": coef[0] * TRADING_DAYS, "beta_stocks": coef[1], "beta_trend": coef[2],
            "r2": 1 - resid / total if total else None, "days": n}


def _months(days: list[dt.date], returns: dict[str, list[float]],
            start: dt.date, end: dt.date) -> list[dict]:
    """Each calendar month wholly inside the window, every series chained
    over it. `days[i + 1]` is the day of `returns[k][i]`."""
    by_month: dict[tuple[int, int], dict[str, float]] = {}
    for i, day in enumerate(days[1:]):
        key = (day.year, day.month)
        acc = by_month.setdefault(key, {k: 1.0 for k in returns})
        for k, rs in returns.items():
            acc[k] *= 1 + rs[i]
    out = []
    for (y, m), acc in sorted(by_month.items()):
        first = dt.date(y, m, 1)
        last = (dt.date(y + (m == 12), m % 12 + 1, 1)) - dt.timedelta(days=1)
        if first < start or last > end:
            continue
        out.append({"month": f"{y:04d}-{m:02d}", **{k: v - 1 for k, v in acc.items()}})
    return out


def analyse(series: dict[str, list[tuple[dt.date, float]]], start: dt.date,
            end: dt.date) -> dict | None:
    """The fund against its replica over [start, end], or None when a series
    is missing. A window too short for statistics says so (`short`) and
    gives the date the comparison can start from (`since`)."""
    if any(not series.get(k) for k in NEEDED):
        return None
    maps = {k: dict(series[k]) for k in NEEDED}
    common = sorted(set.intersection(*(set(m) for m in maps.values())))
    if not common:
        return None
    since = common[0]
    upto = [d for d in common if d <= end]
    first = next((i for i, d in enumerate(upto) if d >= start), None)
    if first is None:
        return {"short": True, "since": since, "days": 0}
    base = max(first - 1, 0)
    days = upto[base:]
    if len(days) - 1 < MIN_DAYS:
        return {"short": True, "since": since, "days": max(len(days) - 1, 0)}

    r = {k: _returns([maps[k][d] for d in days]) for k in NEEDED}
    replica = [s + t - c for s, t, c in zip(r[STOCKS], r[TREND], r[CASH])]
    leg = [f - s + c for f, s, c in zip(r[FUND], r[STOCKS], r[CASH])]
    lines = {"fund": r[FUND], "replica": replica, "stocks": r[STOCKS],
             "trend": r[TREND], "leg": leg}
    levels = {k: _cumulate(v) for k, v in lines.items()}
    span = (days[-1] - days[0]).days

    stats = {}
    for k, rs in lines.items():
        total = levels[k][-1] / 100 - 1
        stats[k] = {"total": total, "annual": _annual(total, span),
                    "vol": _std(rs) * math.sqrt(TRADING_DAYS),
                    "drawdown": _drawdown(levels[k]),
                    "corr_stocks": _corr(rs, r[STOCKS])}

    gap = [f - p for f, p in zip(r[FUND], replica)]
    fund_a, rep_a = stats["fund"]["annual"], stats["replica"]["annual"]
    tracking = {
        "difference": stats["fund"]["total"] - stats["replica"]["total"],
        "difference_pa": fund_a - rep_a if fund_a is not None and rep_a is not None else None,
        "error_pa": _std(gap) * math.sqrt(TRADING_DAYS),
        "corr": _corr(r[FUND], replica),
        "leg_corr_trend": _corr(leg, r[TREND]),
    }
    excess = lambda k: [x - c for x, c in zip(r[k], r[CASH])]  # noqa: E731
    fit = regression(excess(FUND), excess(STOCKS), excess(TREND))

    months = _months(days, {"fund": r[FUND], "stocks": r[STOCKS], "leg": leg}, start, end)
    down = [m for m in months if m["stocks"] < 0]
    falls = ({"months": len(down), "of": len(months),
              "stocks": _mean([m["stocks"] for m in down]),
              "fund": _mean([m["fund"] for m in down]),
              "leg": _mean([m["leg"] for m in down]),
              "leg_up": sum(1 for m in down if m["leg"] > 0)} if down else None)

    # At most ~260 points on screen: every n-th day, the last kept.
    step = max(1, len(days) // 260)
    keep = [i for i in range(len(days)) if i % step == 0 or i == len(days) - 1]
    out = {
        "short": False, "since": since, "from": days[0], "to": days[-1],
        "days": len(days) - 1, "span_days": span,
        "rows": [{"date": days[i], **{k: round(levels[k][i], 3) for k in lines}} for i in keep],
        "stats": stats, "tracking": tracking, "regression": fit, "falls": falls,
    }
    out["verdict"] = verdict(out)
    return out


INDEX_KEYS = ("sg_trend", "sg_cta", "dbmf")


def pocket(rsst: float, sptr: float) -> float:
    """RSST's trend pocket over a period, in %, net of all its fees: the
    fund with the S&P 500 taken out, the mean of the multiplicative and the
    additive readings (they part a little in a big year)."""
    mult = ((1 + rsst / 100) / (1 + sptr / 100) - 1) * 100
    return (mult + (rsst - sptr)) / 2


def excess(x: float, cash: float) -> float:
    """A return above cash, in %: what a trend index adds over its T-bills."""
    return ((1 + x / 100) / (1 + cash / 100) - 1) * 100


def periods(path) -> dict | None:
    """The trend pocket against the SG Trend Index, and DBMF against the SG
    CTA Index (its own index), period by period and cumulated, from
    `data/trend_periods.json` -- returns gathered by hand (the
    `analyse-poche-trend-rsst` skill): SG keeps its histories private, so no
    daily series exists to compute this from. Each row keeps its sources."""
    import json
    from pathlib import Path
    path = Path(path)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    rows = sorted(raw.get("rows") or [], key=lambda r: r.get("ordre", 0))
    if not rows:
        return None
    cum = {k: 1.0 for k in ("pocket", *INDEX_KEYS)}
    out = []
    for r in rows:
        read = {"pocket": pocket(r["rsst"], r["sptr"]),
                **{k: excess(r[k], r["cash"]) for k in INDEX_KEYS}}
        for k in cum:
            cum[k] *= 1 + read[k] / 100
        out.append({"period": r["periode"], **{k: round(v, 2) for k, v in read.items()},
                    "gap_trend": round(read["pocket"] - read["sg_trend"], 2),
                    "gap_cta": round(read["dbmf"] - read["sg_cta"], 2),
                    "sources": r.get("sources", "")})
    total = {k: round((v - 1) * 100, 2) for k, v in cum.items()}
    total["gap_trend"] = round(total["pocket"] - total["sg_trend"], 2)
    total["gap_cta"] = round(total["dbmf"] - total["sg_cta"], 2)
    note = next((m["value"] for m in raw.get("meta") or [] if m.get("label") == "Collecte"), "")
    return {"rows": out, "total": total, "note": note,
            "estimated": any("est." in r.get("sources", "") or "déduit" in r.get("sources", "")
                             for r in rows)}


def _pct(v: float, signed: bool = True) -> str:
    text = f"{abs(v) * 100:.1f}"
    return (("+" if v >= 0 else "−") if signed else "") + text + " %"


def verdict(read: dict) -> list[dict]:
    """Three plain answers, each with its tone: is the stock franc there, is
    the trend franc there, and what the fund cost against its replica."""
    out = []
    fit, st, tr = read["regression"], read["stats"], read["tracking"]
    yearly = st["fund"]["annual"] is not None
    key = "annual" if yearly else "total"
    unit = " par an" if yearly else " sur la période"
    if fit:
        b = fit["beta_stocks"]
        ok = 0.85 <= b <= 1.2
        out.append({"tone": "good" if ok else "warn",
                    "text": (f"Le franc d'actions est là : bêta de {b:.2f} sur le S&P 500 (1 visé)."
                             if ok else f"Bêta de {b:.2f} sur le S&P 500, loin du 1 visé.")})
    leg, trend = st["leg"][key], st["trend"][key]
    gap = leg - trend
    corr = tr["leg_corr_trend"]
    out.append({"tone": "good" if gap >= -0.02 else "warn" if gap >= -0.05 else "bad",
                "text": f"Sa jambe trend a rendu {_pct(leg)}{unit}, contre {_pct(trend)} pour un fonds "
                        f"managed futures, DBMF" + (f" (corrélation {corr:.2f})." if corr is not None else ".")})
    diff = tr["difference_pa"] if yearly else tr["difference"]
    out.append({"tone": "good" if diff >= -0.015 else "warn" if diff >= -0.04 else "bad",
                "text": f"Contre sa réplique (S&P 500 + managed futures − bons du Trésor) : "
                        f"{_pct(diff)}{unit}, frais du fonds compris."})
    return out
