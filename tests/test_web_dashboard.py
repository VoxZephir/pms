"""The dashboard's data (`/api/dashboard`): the window, the drill-down, the
panels and their gates, the timeline and its two stackings, budgets."""

from __future__ import annotations

import datetime as dt
import json
import re

import pytest
from webhelpers import api

from conftest import ROOT
from pms import analysis, buckets

D = dt.date.fromisoformat


def _dash(client, query: str) -> dict:
    return api(client, f"/api/dashboard?{query}")


# --- the window ---------------------------------------------------------------

def test_the_window_shown_is_the_window_asked_for(client):
    data = _dash(client, "from=2025-05-01&to=2025-05-31")
    assert (data["period"]["start"], data["period"]["end"]) == ("2025-05-01", "2025-05-31")
    assert data["period"]["title"] == "Mai 2025"


def test_kpis_compare_against_the_preceding_window(client):
    """The equally long window just before: 31 days back from 30 June."""
    data = _dash(client, "from=2025-07-01&to=2025-07-31")
    assert data["previous"] == {"start": "2025-05-31", "end": "2025-06-30", "exists": True,
                                "label": "31.05.25 → 30.06.25"}
    assert data["kpis"]["previous"]["spend"] > 0


def test_the_median_day_compares_against_the_preceding_window(client, statement):
    """Its variation reads the same window as the mean's: 31 days before."""
    start, end = dt.date(2025, 5, 31), dt.date(2025, 6, 30)
    analysis.annotate_chf(statement)
    rows = analysis.spending(analysis.slice_period(statement, start, end))
    expected = analysis.median_daily(rows, start, end)
    assert expected > 0
    kpis = _dash(client, "from=2025-07-01&to=2025-07-31")["kpis"]
    assert kpis["previous"]["median_day"] == pytest.approx(expected)


def test_window_totals_match_a_direct_computation(client, statement):
    """The API must not invent numbers: one window against the model."""
    start, end = dt.date(2025, 5, 1), dt.date(2025, 5, 31)
    analysis.annotate_chf(statement)
    window = analysis.slice_period(statement, start, end)
    expected = sum(abs(t.amount_chf) for t in analysis.spending(window))
    assert _dash(client, f"from={start}&to={end}")["kpis"]["spend"] == pytest.approx(expected)


def test_the_daily_kpi_gives_a_median_beside_the_mean(client):
    """The mean is dragged up by rent and tax days; the median says what an
    ordinary day costs."""
    kpis = _dash(client, "preset=all")["kpis"]
    assert 0 < kpis["median_day"] < kpis["per_day"]


# --- drilling down --------------------------------------------------------------

def test_the_columns_tile_the_window_end_to_end(client):
    """A gap between two columns is a range a brush would map to no date."""
    rows = _dash(client, "from=2025-01-01&to=2025-12-31&grain=month")["timeline"]["rows"]
    assert (rows[0]["start"], rows[-1]["end"]) == ("2025-01-01", "2025-12-31")
    for before, after in zip(rows, rows[1:]):
        assert D(before["end"]) + dt.timedelta(days=1) == D(after["start"])


def test_a_column_opens_one_level_deeper(client):
    """The hint is derived from the same call as the destination: a month
    goes straight to days, and a day opens the day itself."""
    months = _dash(client, "from=2025-01-01&to=2025-12-31&grain=month")["timeline"]
    assert months["drill"] == "day" and "jour" in months["hint"]
    days = _dash(client, "from=2025-05-01&to=2025-05-31&grain=day")["timeline"]
    assert days["drill"] == "detail" and "journée" in days["hint"]


def test_the_drill_chain_reaches_a_single_day(client):
    """Full history -> ... -> a day, following only what the columns open."""
    query = "preset=all"
    for _ in range(5):
        timeline = _dash(client, query)["timeline"]
        busy = [r for r in timeline["rows"] if r["count"]]
        assert busy, "every level must offer a way down"
        row = busy[len(busy) // 2]
        if timeline["drill"] == "detail":
            day = api(client, f"/api/day/{row['start']}")
            assert day["rows"]
            return
        query = f"from={row['start']}&to={row['end']}&grain=auto"
    pytest.fail("the drill-down never reached a single day")


def test_an_unknown_day_is_a_404(client):
    assert client.get("/api/day/pas-une-date").status_code == 404


def test_a_brushed_range_resolves_to_that_window(client):
    """What the brush produces is a plain URL; it lands where it says."""
    rows = _dash(client, "preset=all")["timeline"]["rows"]
    start, end = rows[3]["start"], rows[7]["end"]
    period = api(client, f"/api/period?from={start}&to={end}&grain=auto")
    assert (period["start"], period["end"]) == (start, end)


# --- panels that need a span to say anything ---------------------------------------

PANELS = ["balance", "highlights", "fixed", "calendar", "years", "season", "country",
          "custodian", "monthly", "income", "missing", "shares"]


def test_full_history_shows_every_panel(client):
    panels = _dash(client, "preset=all")["panels"]
    assert not [p for p in PANELS if not panels[p]]


def test_a_short_window_hides_panels_that_cannot_say_anything(client):
    """A seasonality chart over ten days would be noise dressed as a finding."""
    panels = _dash(client, "from=2026-07-01&to=2026-07-10")["panels"]
    for panel in ("fixed", "calendar", "years", "monthly", "income", "season"):
        assert not panels[panel], panel
    assert panels["balance"]   # this one always has something to show


def test_the_balance_covers_only_the_window(client):
    points = _dash(client, "from=2025-05-01&to=2025-05-31")["balance"]
    assert points and all("2025-05-01" <= day <= "2025-05-31" for day, _ in points)


def test_a_year_series_says_where_its_data_stops(client):
    """Padding the ends would claim a total that was never reached: each
    year carries the days it covers, and its points stay inside them."""
    years = _dash(client, "preset=all")["years"]
    assert len(years) >= 2
    assert any(y["first_day"] > 15 or y["last_day"] < 350 for y in years)
    for year in years:
        days = [d for d, _ in year["points"]]
        values = [v for _, v in year["points"]]
        assert year["first_day"] <= min(days) and max(days) <= year["last_day"]
        assert values == sorted(values) and values[0] > 0


def test_the_missing_commitments_appear_only_when_there_are_some(client):
    """A subscription stops in May 2026 and never comes back; nothing is
    missing in the first half of 2025."""
    assert _dash(client, "preset=all")["missing"]
    assert _dash(client, "from=2025-01-01&to=2025-06-30")["missing"] == []


def test_the_income_panel_names_the_payers_and_their_span(client):
    income = _dash(client, "preset=all")["income"]
    assert income["payers"] >= 2 and len(income["table"]) >= 3
    for row in income["table"]:
        assert row["first"] <= row["last"]
    # One payer says nothing the "Encaissé" KPI does not already say.
    assert _dash(client, "from=2026-06-01&to=2026-06-30")["income"] is None


def test_the_merchants_carry_a_median_next_to_the_mean(client):
    merchants = _dash(client, "preset=all")["top_merchants"]
    assert merchants and all("median" in m and "average" in m for m in merchants)


def test_a_category_unfolds_on_its_subcategories_and_payees(client):
    categories = _dash(client, "preset=all")["categories"]
    assert any(c["subcategories"] for c in categories)
    assert all(c["top_merchants"] for c in categories if c["amount"] > 0)


def test_the_monthly_panel_needs_two_months(client):
    monthly = _dash(client, "preset=all")["monthly"]
    assert "Autres" in [r["name"] for r in monthly]
    assert all(len(r["months"]) >= 2 for r in monthly)
    assert _dash(client, "from=2026-07-01&to=2026-07-30")["monthly"] == []


def test_the_custodian_is_compared_with_dated_reference_rates(client):
    """The 0.97 % finding means nothing until it is held against what the same
    conversion would cost elsewhere -- dated, because FX markups move."""
    custodian = _dash(client, "preset=all")["custodian"]
    names = " ".join(r["name"] for r in custodian["references"])
    for name in ("Wise", "neon", "Revolut"):
        assert name in names
    assert custodian["references_as_of"]


# --- the buckets -------------------------------------------------------------------

def test_each_bucket_filter_narrows_to_that_bucket(client, statement):
    """Checked against the model rather than re-derived from categories: a
    subcategory can sit in another bucket than its parent, and a correction
    can move a single row."""
    from pms.categories import classify_all
    classify_all(statement.transactions, holder=statement.holder)
    analysis.annotate_chf(statement)
    buckets.annotate(statement.transactions)
    for name in ("Need", "Want", "Non classé"):
        expected = sum(1 for t in statement.transactions if t.bucket == name)
        assert api(client, f"/api/transactions?preset=all&bucket={name}")["total"] == expected, name


def test_the_buckets_partition_the_spending(client):
    """Every spending row lands in exactly one bucket -- money moved to
    one's own account is not spending, and has none."""
    held = client.application.extensions["pms_store"].statement
    moved = sum(1 for t in held.transactions if t.amount < 0 and t.category == "Virement interne")
    total = api(client, "/api/transactions?preset=all&dir=out")["total"] - moved
    parts = sum(api(client, f"/api/transactions?preset=all&dir=out&bucket={name}")["total"]
                for name in buckets.ORDER)
    assert parts == total


def test_the_save_bucket_reports_its_two_halves(client):
    """`Save` holds a decision (money moved to a placement) and an outcome
    (money that never left): the halves add up to the row, and only the one
    with transactions behind it can be opened."""
    summary = _dash(client, "preset=all")["buckets"]
    save = next(r for r in summary["rows"] if r["name"] == buckets.SAVE)
    assert sum(p["amount"] for p in save["parts"]) == pytest.approx(save["amount"])
    assert sum(p["share"] for p in save["parts"]) == pytest.approx(save["share"])
    hollow = [p for p in save["parts"] if p["hollow"]]
    assert [p["name"] for p in hollow] == [buckets.UNSPENT]
    assert all(not r["parts"] for r in summary["rows"] if r["name"] != buckets.SAVE)


# --- the timeline, stacked two ways ---------------------------------------------------

def test_the_two_stackings_slice_the_same_columns(client):
    """Same money, sliced the other way: the column totals must not move."""
    rows = _dash(client, "from=2025-01-01&to=2025-12-31&grain=month&stack=bucket")["timeline"]["rows"]
    for row in rows:
        assert sum(row["categories"].values()) == pytest.approx(row["spending"])
        assert sum(row["buckets"].values()) == pytest.approx(row["spending"])


def test_the_stack_is_read_from_the_url_and_validated(client):
    assert _dash(client, "preset=all")["timeline"]["stack"] == "category"
    assert _dash(client, "preset=all&stack=bucket")["timeline"]["stack"] == "bucket"
    assert _dash(client, "preset=all&stack=pas-un-mode")["timeline"]["stack"] == "category"


def test_a_bucket_keeps_its_colour_everywhere(client):
    """A hue that means Need in one panel cannot mean Want in the next."""
    fill = _dash(client, "preset=all")["bucket_fill"]
    assert fill["Need"] == "var(--s0)" and fill["Want"] == "var(--s1)"
    assert fill["Non classé"] == "var(--unsorted)"


def test_no_category_takes_a_ninth_hue(client):
    data = _dash(client, "preset=all")
    assert {c["slot"] for c in data["categories"]} <= set(range(8))
    assert [entry["name"] for entry in data["legend"]][-1] == "Autres"


# --- the shares over time ------------------------------------------------------------

def test_the_shares_default_to_the_income_base(client):
    shares = _dash(client, "preset=all")["shares"]
    assert shares["base"] == "income" and shares["smooth"] == 1
    assert "Save" in shares["names"]


def test_the_spending_base_has_no_save(client):
    """What was not spent is not a spending."""
    assert "Save" not in _dash(client, "preset=all&shares=spending")["shares"]["names"]


def test_smoothing_keeps_the_raw_months(client):
    rows = _dash(client, "preset=all&shares=income&smooth=6")["shares"]["rows"]
    assert any(r["raw"]["Need"] != r["smooth"]["Need"] for r in rows)
    assert _dash(client, "preset=all&shares=income&smooth=7")["shares"]["smooth"] == 1


def test_the_shares_need_two_whole_months(client):
    assert not _dash(client, "from=2025-05-01&to=2025-05-31")["panels"]["shares"]
    assert _dash(client, "from=2025-05-01&to=2025-06-30")["panels"]["shares"]


# --- budgets -----------------------------------------------------------------------

def _budgets(client):
    return client.application.extensions["pms_store"].path.with_name("budgets.json")


def test_a_budget_is_set_shown_and_removed(client):
    path = _budgets(client)
    path.unlink(missing_ok=True)
    try:
        assert client.post("/api/budgets", json={"category": "Alimentation",
                                                 "amount": "400"}).status_code == 200
        assert json.loads(path.read_text(encoding="utf-8"))["budgets"] == {"Alimentation": 400.0}
        row = next(r for r in _dash(client, "preset=all")["monthly"] if r["name"] == "Alimentation")
        assert row["budget"] == 400.0
        client.post("/api/budgets", json={"category": "Alimentation", "action": "delete"})
        assert json.loads(path.read_text(encoding="utf-8"))["budgets"] == {}
    finally:
        path.unlink(missing_ok=True)


def test_a_budget_that_does_not_parse_is_refused_and_not_written(client):
    path = _budgets(client)
    path.unlink(missing_ok=True)
    zero = client.post("/api/budgets", json={"category": "Alimentation", "amount": "0"})
    assert zero.status_code == 400 and zero.get_json()["error"] == "Montant invalide."
    comma = client.post("/api/budgets", json={"category": "Alimentation", "amount": "12,50"})
    assert comma.status_code == 400 and "point décimal" in comma.get_json()["error"]
    assert not path.exists()


# --- colour you can see --------------------------------------------------------------

def _contrast(a: str, b: str) -> float:
    def lum(hex_colour: str) -> float:
        channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
                  for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    high, low = sorted((lum(a), lum(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_non_classe_is_a_mark_you_can_see_in_both_themes():
    """It once borrowed the axis grey: 1.75:1 in light, 1.48:1 in dark -- a
    line nobody could see. A mark needs 3:1 against its surface (WCAG 1.4.11)."""
    css = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    light = css[css.index(":root {"):]
    dark = css[css.index(':root[data-theme="dark"] {'):]
    for block in (light, dark):
        block = block[:block.index("}")]
        unsorted = re.search(r"--unsorted:\s*(#[0-9a-f]{6})", block).group(1)
        surface = re.search(r"--surface:\s*(#[0-9a-f]{6})", block).group(1)
        assert _contrast(unsorted, surface) >= 3, (unsorted, surface)


def test_the_validated_surfaces_have_not_moved():
    """The eight hues were validated against these surfaces; a new surface
    is a new validation, not a tweak."""
    css = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    light = css[css.index(":root {"):]
    dark = css[css.index(':root[data-theme="dark"] {'):]
    assert "--surface: #fcfcfb;" in light[:light.index("}")]
    assert "--surface: #1a1a19;" in dark[:dark.index("}")]


def test_the_per_day_fact_agrees_with_the_per_day_tile(client):
    """Both divide by the same span, both ends counted: a month read 134 on
    the tile and 138 in the facts."""
    d = api(client, "/api/dashboard?from=2026-06-01&to=2026-06-30")
    fact = next(h for h in d["highlights"] if h["label"] == "Dépense moyenne par jour")
    assert fact["value"] == f"{d['kpis']['per_day']:,.0f} CHF".replace(",", "’") \
        or fact["value"].split()[0].replace("’", "").replace("'", "") == f"{d['kpis']['per_day']:.0f}"
    assert "sur 30 jours" in fact["detail"]


def test_the_top_payee_paid_once_is_not_the_biggest_expense_twice(client):
    d = api(client, "/api/dashboard?from=2026-07-01&to=2026-07-30")
    labels = [h["label"] for h in d["highlights"]]
    biggest = next(h for h in d["highlights"] if h["label"] == "Plus grosse dépense")
    top = next((h for h in d["highlights"] if h["label"] == "Premier bénéficiaire"), None)
    assert top is None or top["detail"].split(" — ")[0] != biggest["detail"].split(" — ")[0] \
        or "paiements" in top["detail"]
    assert len(labels) == len(set(labels))


def test_the_month_in_progress_against_an_ordinary_one(client):
    """The latest month: what is gone, an ordinary month at the same day,
    where it would end, and each budget against the days gone."""
    data = api(client, "/api/dashboard")
    p = data["pace"]
    assert p and len(p["values"]) == p["day"] and p["values"][-1] == p["spent"]
    assert p["projected"] >= p["spent"]
    assert abs(p["vs_ordinary"] - (p["spent"] - p["ordinary_now"])) < 0.05
    assert api(client, "/api/dashboard?preset=12m")["pace"] is None


def test_each_category_against_the_window_before(client):
    data = api(client, "/api/dashboard?from=2026-06-01&to=2026-06-30")
    assert data["previous"]["label"] and data["versus"]
    rows = data["versus"]
    assert [abs(r["delta"]) for r in rows] == sorted((abs(r["delta"]) for r in rows), reverse=True)
    spent = data["kpis"]["spend"]
    assert abs(sum(r["now"] for r in rows) - spent) < 1.0 or all(abs(r["delta"]) >= 0.5 for r in rows)


def test_the_timeline_median_counts_complete_periods_only(client):
    body = api(client, "/api/dashboard?preset=all")
    t = body["timeline"]
    rows, median = t["rows"], t["median"]
    assert median is not None and median["periods"] + median["partial"] == len(rows)
    # The statement opens and closes mid-month: those two are left out.
    whole = sorted(r["spending"] for r in rows[1:-1])
    mid = len(whole) // 2
    expected = whole[mid] if len(whole) % 2 else (whole[mid - 1] + whole[mid]) / 2
    assert median["amount"] == pytest.approx(expected, abs=0.01)
    # At the grain on screen: two months are drawn by week, the median is
    # a week's, the weeks the window cuts left out.
    weeks = api(client, "/api/dashboard?from=2025-03-01&to=2025-04-30")
    assert weeks["period"]["grain"] == "week" and weeks["timeline"]["median"]["partial"] >= 1
