"""The dashboard: drill-down, panels, the timeline and its brush, the charts'
geometry and their twin tables, budgets."""

from __future__ import annotations

import datetime as dt
import re

import pytest
from webhelpers import chart_data, row_count, text

from pms import analysis, buckets

# --- routes -----------------------------------------------------------------

def test_dashboard_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Relevé Swissquote" in text(response)


def test_fragment_and_full_page_agree(client):
    """The JavaScript path and the no-JavaScript path must render the same
    markup, or the two drift apart silently."""
    query = "from=2025-05-01&to=2025-05-31"
    full = text(client.get(f"/?{query}"))
    fragment = text(client.get(f"/?{query}&fragment=1"))
    assert fragment.strip() in full


def test_window_shown_is_the_window_asked_for(client):
    response = client.get("/?from=2025-05-01&to=2025-05-31")
    body = text(response)
    assert "01.05.2025" in body and "31.05.2025" in body
    assert "Mai 2025" in body


def test_drill_links_stay_inside_the_current_window(client):
    body = text(client.get("/?from=2025-01-01&to=2025-12-31&grain=month"))
    # Only the chart's own links: the breadcrumb legitimately points outside the
    # window (that is how you climb back out). url_for sorts query parameters,
    # so parse each href rather than assuming from and to sit next to each other.
    hrefs = re.findall(r'href="/\?([^"]+)"[^>]*>\s*<g class="col-group', body)
    assert hrefs
    seen = 0
    for href in hrefs:
        params = dict(p.split("=", 1) for p in href.replace("&amp;", "&").split("&")
                      if "=" in p)
        if "from" not in params or "to" not in params:
            continue
        seen += 1
        assert dt.date.fromisoformat(params["from"]) >= dt.date(2025, 1, 1)
        assert dt.date.fromisoformat(params["to"]) <= dt.date(2025, 12, 31)
    assert seen, "the monthly view must offer drill-down links"


def test_drill_chain_reaches_a_single_day(client):
    """Full history -> ... -> a day detail page, following only real links."""
    url = "/?preset=all"
    for _ in range(5):
        body = text(client.get(url))
        links = re.findall(r'href="(/\?from=[^"]+|/day/[^"]+)"', body)
        assert links, "every level must offer a way down"
        if any(link.startswith("/day/") for link in links):
            day = next(link for link in links if link.startswith("/day/"))
            response = client.get(day.replace("&amp;", "&"))
            assert response.status_code == 200
            assert "Mouvements de la journée" in text(response)
            return
        url = links[len(links) // 2].replace("&amp;", "&")
    pytest.fail("the drill-down never reached a single day")


def test_day_page_lists_movements_in_statement_order(client, statement):
    target = statement.transactions[500].date
    body = text(client.get(f"/day/{target.isoformat()}"))
    assert target.strftime("%d.%m.%Y") in body
    assert "Solde après" in body


def test_unknown_day_is_a_404(client):
    assert client.get("/day/pas-une-date").status_code == 404


def test_kpis_compare_against_the_preceding_window(client):
    body = text(client.get("/?from=2025-07-01&to=2025-07-31"))
    assert "vs période précédente" in body
    assert "30.06.2025" in body  # the previous window's end


def test_window_totals_match_a_direct_computation(client, statement):
    """The page must not invent numbers: check one window against the model."""
    start, end = dt.date(2025, 5, 1), dt.date(2025, 5, 31)
    window = analysis.slice_period(statement, start, end)
    expected = sum(abs(t.amount_chf) for t in analysis.spending(window))
    body = text(client.get(f"/?from={start}&to={end}"))
    assert analysis.chf(expected, 0) in body


# --- panel parity with the static report ------------------------------------

PANELS = ["p-balance", "p-highlights", "p-fixed", "p-calendar",
          "p-years", "p-profiles", "p-country", "p-custodian",
          "p-monthly"]


def test_full_history_shows_every_panel(client):
    """The app must not be a reduced version of the static report."""
    body = text(client.get("/?preset=all"))
    missing = [p for p in PANELS if f'id="{p}"' not in body]
    assert not missing, f"panels missing from the app: {missing}"


def test_short_window_hides_panels_that_cannot_say_anything(client):
    """A seasonality chart over ten days would be noise dressed as a finding."""
    body = text(client.get("/?from=2026-07-01&to=2026-07-10"))
    for panel in ("p-fixed", "p-calendar", "p-years"):
        assert f'id="{panel}"' not in body
    assert 'id="p-balance"' in body   # this one always has something to show


def test_balance_chart_covers_only_the_window(client):
    body = text(client.get("/?from=2025-05-01&to=2025-05-31"))
    assert 'id="balChart"' in body
    assert "01.05.2025" in body and "31.05.2025" in body


def test_year_series_has_no_data_outside_the_days_observed(statement):
    """Padding the ends would claim a total that was never reached."""
    from pms.web import charts
    analysis.annotate_chf(statement)  # idempotent; needed when run alone
    series = charts.year_chart(
        analysis.year_cumulative(analysis.spending(statement)))
    for line in series["series"].values():
        points = series["series"][line["slot"]]["pts"]
        assert any(p is None for p in points), \
            "a partial year must stop instead of being padded"
        # Everything present must be a real, non-decreasing cumulative value.
        seen = [p[2] for p in points if p]
        assert seen == sorted(seen)
        assert seen[0] > 0


# --- drilling into a bucket -------------------------------------------------

def test_bucket_blocks_link_to_their_transactions(client):
    """Need/Want/Save must be explorable like the category bars are."""
    body = text(client.get("/?preset=all"))
    for name in ("Need", "Want", "Save"):
        assert f"bucket={name}" in body, f"{name} is not clickable"


def test_each_bucket_filter_narrows_to_that_bucket(client, statement):
    """Checked against the model rather than by re-deriving the mapping from the
    category chips: a subcategory can sit in a different bucket from its parent
    (streaming inside Télécom), and a manual correction can move a single row."""
    from pms import buckets as buckets_module
    from pms.categories import classify_all

    classify_all(statement.transactions)
    analysis.annotate_chf(statement)
    buckets_module.annotate(statement.transactions)

    for name in ("Need", "Want", "Non classé"):
        expected = sum(1 for t in statement.transactions if t.bucket == name)
        body = text(client.get(
            f"/transactions?preset=all&bucket={name}&fragment=1"))
        assert row_count(body) == expected, name


def test_the_buckets_partition_the_transactions(client):
    """Every spending row lands in exactly one bucket, so the four filters add
    up to the whole statement."""
    total = row_count(text(client.get("/transactions?preset=all&dir=out&fragment=1")))
    parts = sum(
        row_count(text(client.get(
            f"/transactions?preset=all&dir=out&bucket={name}&fragment=1")))
        for name in ("Need", "Want", "Save", "Non classé")
    )
    assert parts == total


def test_the_save_bucket_reports_its_two_halves_separately(client, statement):
    """`Save` holds a decision (money moved to a placement) and an outcome (money
    that never left). Their sum is not "saved", so the panel has to show the seam
    -- and the halves must still add up to the row, or the bar stops totalling
    100% of income."""
    from pms import buckets as buckets_module
    from pms.categories import classify_all

    classify_all(statement.transactions)
    analysis.annotate_chf(statement)
    summary = buckets_module.summarise(statement)
    save = next(r for r in summary["rows"] if r["name"] == buckets_module.SAVE)

    assert save["parts"], "the Save row must expose its split"
    assert sum(p["amount"] for p in save["parts"]) == pytest.approx(save["amount"])
    assert sum(p["share"] for p in save["parts"]) == pytest.approx(save["share"])
    # No other bucket is two things at once.
    assert all(not r["parts"] for r in summary["rows"]
               if r["name"] != buckets_module.SAVE)

    body = text(client.get("/?preset=all"))
    for part in save["parts"]:
        assert part["name"] in body, f"{part['name']} is missing from the panel"


def test_the_unspent_half_of_save_is_not_clickable(client):
    """It has no transaction of its own, so a link would land on an empty table
    and read as a bug. Drawn hollow instead, like an empty calendar tile."""
    body = text(client.get("/?preset=all"))
    hollow = re.findall(r"<(\w+)[^>]*class=\"bucket-seg hollow\"[^>]*>", body)
    assert hollow, "the unspent half is not drawn"
    assert all(tag == "span" for tag in hollow), hollow


def test_timeline_ships_the_geometry_a_brush_needs(client):
    data = chart_data(text(client.get("/?preset=all")))
    timeline = data["timeline"]
    assert timeline["bands"]
    assert timeline["plot"]["w"] > 0
    for band in timeline["bands"]:
        assert band["w"] > 0
        assert band["from"] <= band["to"]


def test_the_bands_tile_the_axis_without_gaps(client):
    """A gap between two bands is a pixel range that maps to no date, so a
    brush released there would silently select the wrong window."""
    bands = chart_data(text(client.get("/?preset=all")))["timeline"]["bands"]
    for previous, current in zip(bands, bands[1:]):
        assert abs((previous["x"] + previous["w"]) - current["x"]) < 0.01


def test_the_bands_cover_the_window_end_to_end(client):
    body = text(client.get("/?from=2025-01-01&to=2025-12-31&grain=month"))
    bands = chart_data(body)["timeline"]["bands"]
    assert bands[0]["from"] == "2025-01-01"
    assert bands[-1]["to"] == "2025-12-31"


def test_a_brushed_range_resolves_to_that_window(client):
    """What the brush produces is a plain URL; check it lands where it says."""
    bands = chart_data(text(client.get("/?preset=all")))["timeline"]["bands"]
    start, end = bands[3]["from"], bands[7]["to"]
    body = text(client.get(f"/?from={start}&to={end}&grain=auto"))
    assert dt.date.fromisoformat(start).strftime("%d.%m.%Y") in body
    assert dt.date.fromisoformat(end).strftime("%d.%m.%Y") in body


def test_the_columns_stay_plain_links(client):
    """The brush overlay is injected by JavaScript. If it were in the markup it
    would swallow the clicks that make drill-down work without JavaScript."""
    body = text(client.get("/?preset=all"))
    assert "brushlayer" not in body
    assert re.search(r'href="/\?[^"]+"[^>]*>\s*<g class="col-group', body)


def test_the_daily_kpi_shows_a_median_beside_the_mean(client):
    body = text(client.get("/?preset=all"))
    assert "Par jour" in body
    assert "médiane" in body


# --- stacking the timeline two ways -----------------------------------------

def test_the_timeline_stacks_by_category_by_default(client):
    """The accessible name of the columns moved from the SVG onto the column
    links themselves; the switch still says which breakdown is active, and
    the categories are the default."""
    body = text(client.get("/?preset=all"))
    assert 'aria-label="Découpage des colonnes"' in body
    assert re.search(r'class="on" data-nav\s+href="[^"]*">Catégories</a>', body)


def test_the_switch_restacks_the_same_columns_by_bucket(client):
    """Same money, sliced the other way: the column totals must not move."""
    query = "from=2025-01-01&to=2025-12-31&grain=month"
    by_category = text(client.get(f"/?{query}"))
    by_bucket = text(client.get(f"/?{query}&stack=bucket"))

    assert re.search(r'class="on" data-nav\s+href="[^"]*">Besoins / envies</a>',
                     by_bucket)
    assert "Need" in by_bucket and "Want" in by_bucket

    totals = lambda body: re.findall(r'data-total="([^"]+)"', body)
    assert totals(by_category) == totals(by_bucket)
    assert totals(by_category)  # the assertion above is worthless if both are empty


def test_the_bucket_stack_uses_the_same_colours_as_the_bucket_panel(client):
    """A hue that means Need in one panel cannot mean Want in the next."""
    body = text(client.get("/?preset=all&stack=bucket"))
    legend = re.search(r'<div class="legend">(.*?)</div>', body, re.S).group(1)
    assert 'background:var(--s0)"></i>Need' in legend
    assert 'background:var(--s1)"></i>Want' in legend


def test_the_chosen_stack_survives_a_drill_down(client):
    """Zooming into a column must not silently flip the chart back."""
    body = text(client.get("/?from=2025-01-01&to=2025-12-31&grain=month&stack=bucket"))
    drills = re.findall(r'href="(/\?[^"]+)"[^>]*>\s*<g class="col-group', body)
    assert drills
    assert all("stack=bucket" in href for href in drills)

    deeper = client.get(drills[0].replace("&amp;", "&"))
    assert re.search(r'class="on" data-nav\s+href="[^"]*">Besoins / envies</a>',
                     text(deeper))


def test_the_default_stack_is_left_out_of_the_links(client):
    """`stack=category` in every URL would be noise that says nothing."""
    body = text(client.get("/?preset=all"))
    assert "stack=category" not in body


def test_an_unknown_stack_falls_back_instead_of_failing(client):
    body = text(client.get("/?preset=all&stack=pas-un-mode"))
    assert re.search(r'class="on" data-nav\s+href="[^"]*">Catégories</a>', body)


def test_the_panel_appears_only_when_it_has_something_to_say(client):
    """A subscription stops in May 2026 and never comes back; nothing is
    missing in the first half of 2025."""
    assert 'id="p-missing"' in text(client.get("/?preset=all"))
    assert 'id="p-missing"' not in text(client.get("/?from=2025-01-01&to=2025-06-30"))


def test_the_panel_dates_itself_against_the_window_shown(client):
    body = text(client.get("/?preset=all"))
    panel = body[body.index('id="p-missing"'):]
    assert "au 30.07.2026" in panel[:600]


# --- merchant medians -------------------------------------------------------

def test_the_merchant_tooltip_shows_a_median_next_to_the_mean(client):
    body = text(client.get("/?preset=all"))
    # The <h3>, not the mini-header of the same name inside every unfolded
    # category -- that one appears first and belongs to a different block.
    section = body[body.index("<h3>Principaux bénéficiaires</h3>"):]
    assert "Médiane" in section[:6000]


# --- who was paying, and when -----------------------------------------------

def test_the_income_panel_names_the_payers_and_their_span(client):
    body = text(client.get("/?preset=all"))
    assert 'id="p-income"' in body
    panel = body[body.index('id="p-income"'):]
    panel = panel[:panel.index("</section>")]
    assert "payeur" in panel
    # Every payer row carries the window it covers -- that is the whole story.
    assert panel.count("<tr>") >= 3


def test_the_income_panel_needs_more_than_one_payer(client):
    """One payer says nothing the "Encaissé" KPI does not already say."""
    body = text(client.get("/?from=2026-06-01&to=2026-06-30"))
    assert 'id="p-income"' not in body


# --- categories fold open again ---------------------------------------------

def test_the_app_shows_subcategories_like_the_report_does(client):
    """`by_category` computes them; the app used to throw them away."""
    body = text(client.get("/?preset=all"))
    block = body[body.index('class="cat-list"'):]
    assert "Sous-postes" in block
    assert "Principaux bénéficiaires" in block


def test_folding_a_category_open_does_not_cost_the_drop_target(client):
    """The row is where a dragged transaction lands; making it a disclosure
    must not take that away."""
    body = text(client.get("/?preset=all"))
    rows = re.findall(r'<summary class="cat-row"[^>]*>', body)
    assert rows
    assert all("data-drop-category=" in row for row in rows)


def test_the_category_still_links_to_its_transactions(client):
    body = text(client.get("/?preset=all"))
    block = body[body.index('class="cat-list"'):]
    assert re.search(r'href="/transactions\?[^"]*category=', block)


# --- geometry actually reaches the markup -----------------------------------
# Ported from the static report's own tests when it was deleted: these caught
# real breakage there, and the app renders the same charts.

def test_no_chart_paints_with_an_unresolved_colour(client):
    """`var(--s)` is what an unresolved slot renders as, and it paints nothing.
    Same for `var(--h)` on the calendar ramp."""
    body = text(client.get("/?preset=all"))
    assert "var(--s)" not in body
    assert "var(--h)" not in body


def test_no_coordinate_reaches_the_page_empty(client):
    """Jinja renders Undefined as an empty string, so a missing geometry key
    becomes x="" -- valid markup that draws nothing."""
    body = text(client.get("/?preset=all"))
    assert not re.search(r'\b(x|y|cx|cy|x1|y1|x2|y2|width|height)=""', body)


def test_the_calendar_still_marks_its_empty_days(client):
    """With the ramp running light to dark, a filled empty tile would sit at
    the same luminance as the busiest day."""
    body = text(client.get("/?preset=all"))
    assert 'class="cell empty"' in body


# --- hover-only panels carry a twin table ------------------------------------

def _twin_tables(body: str) -> list[list[list[str]]]:
    """Cells of every twin <details> table, in page order: one list of rows
    per table, one list of cell texts per row."""
    tables = []
    for block in re.findall(
            r"<details[^>]*>\s*<summary[^>]*>Voir le détail en table</summary>"
            r"(.*?)</details>", body, re.S):
        tbody = re.search(r"<tbody>(.*?)</tbody>", block, re.S)
        if tbody is None:
            continue  # built on demand (the calendar's): no table yet
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody.group(1), re.S):
            rows.append([re.sub(r"<[^>]+>", "", c).strip()
                         for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)])
        tables.append(rows)
    return tables


def test_each_hover_only_panel_gains_a_twin_table(client):
    """Six panels only say their figures on hover. Each carries a plain
    <details>/<table> pair with the same data -- native elements, so the
    no-JavaScript path keeps working."""
    body = text(client.get("/?preset=all"))
    assert body.count("Voir le détail en table") == 6
    for rows in _twin_tables(body):
        assert rows and len(rows[0]) >= 2, "a twin table is not an empty shell"
    for panel_id in ("p-shares", "p-calendar", "p-years", "p-country"):
        start = body.find(f'id="{panel_id}"')
        section = body[start:body.find("</section>", start)]
        assert "Voir le détail en table" in section
    start = body.find('id="p-profiles"')
    profiles = body[start:body.find("</section>", start)]
    assert profiles.count("Voir le détail en table") == 2


def test_the_calendar_table_lists_every_spending_day(client, statement):
    """The calendar's grid only speaks on hover; the table is its twin, one
    row per day that spent anything, in the same chronological order."""
    analysis.annotate_chf(statement)
    # The no-JavaScript path: asked for, the table is rendered, unfolded.
    body = text(client.get("/?preset=all&table=calendar"))
    table = next(r for r in _twin_tables(body)
                 if re.match(r"^\d{2}\.\d{2}\.\d{4}$", r[0][0]))
    days = analysis.daily_totals(analysis.spending(statement))
    assert [row[0] for row in table] == \
        [d.strftime("%d.%m.%Y") for d in sorted(days)]
    assert len(table) > 100  # the whole point is a long, complete table


def test_the_weekday_table_twins_the_bars(client):
    body = text(client.get("/?preset=all"))
    table = next(r for r in _twin_tables(body) if r[0][0] == "Lundi")
    assert [row[0] for row in table] == \
        ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    assert all(len(row) == 4 for row in table)


def test_the_season_table_twins_the_month_bars(client):
    body = text(client.get("/?preset=all"))
    table = next(r for r in _twin_tables(body) if r[0][0] == "janv.")
    assert [row[0] for row in table] == analysis.MONTH_SHORT
    assert len(table) == 12


def test_the_year_table_twins_the_legend(client, statement):
    """A partial year says so here too, like the legend it twins."""
    analysis.annotate_chf(statement)
    body = text(client.get("/?preset=all"))
    table = next(r for r in _twin_tables(body) if re.match(r"^\d{4}\b", r[0][0]))
    series = analysis.year_cumulative(analysis.spending(statement))
    assert [row[0].split()[0] for row in table] == \
        [str(s["year"]) for s in series]
    assert any("année partielle" in row[0] for row in table)


def test_the_country_table_twins_the_bars(client, statement):
    """Same countries as the bars, in the same order, and the amounts are the
    chart's own numbers down to the centime."""
    analysis.annotate_chf(statement)
    body = text(client.get("/?preset=all"))
    start = body.index('id="p-country"')
    (table,) = _twin_tables(body[start:body.index("</section>", start)])
    geo = analysis.by_country(analysis.spending(statement))
    chart = geo["rows"][:10]  # country_chart caps at ten rows
    assert [row[0] for row in table] == [r["country"] for r in chart]
    expected = sum(r["amount"] for r in chart)
    rendered = sum(float(row[1].replace("’", "")) for row in table)
    assert rendered == pytest.approx(expected, abs=0.05)


def test_monthly_panel_shows_two_months_of_categories(client):
    body = text(client.get("/?preset=all"))
    assert 'id="p-monthly"' in body
    assert "Dépenses par mois" in body
    # one bar per observed month, scaled to the category's own peak
    assert 'class="m-bars"' in body
    assert 'class="m-bar"' in body
    assert "Autres" in body


def test_monthly_panel_absent_below_two_months(client):
    body = text(client.get("/?from=2026-07-01&to=2026-07-30"))
    assert 'id="p-monthly"' not in body


def test_custodian_panel_compares_reference_rates(client):
    """The 0.97 % finding means nothing until it is held against what the same
    conversion would cost elsewhere -- dated, because FX markups move."""
    body = text(client.get("/?preset=all"))
    assert "La même chose ailleurs" in body
    for name in ("Wise", "neon", "Revolut"):
        assert name in body
    assert "taux publiés vérifiés le" in body


def test_budget_gauge_appears_with_a_budget(client):
    """A declared budget turns the monthly rows into gauges: median month vs
    the goal, red when the median overshoots."""
    import json

    store_ = client.application.extensions["pms_store"]
    path = store_.path.with_name("budgets.json")
    path.write_text(json.dumps({"version": 1, "budgets": {"Logement": 1.0}}),
                    encoding="utf-8")
    try:
        body = text(client.get("/?preset=all"))
        assert "m-budget" in body
        assert "Définir un budget" in body
        assert "var(--critical)" in body  # a 1 CHF budget is always overshot
    finally:
        path.unlink(missing_ok=True)


def test_budget_post_writes_the_file(client):
    store_ = client.application.extensions["pms_store"]
    path = store_.path.with_name("budgets.json")
    if path.exists():
        path.unlink()

    response = client.post("/budgets", data={
        "action": "add", "category": "Alimentation", "amount": "400"})
    assert response.status_code == 302

    import json as _json
    payload = _json.loads(path.read_text(encoding="utf-8"))
    assert payload["budgets"] == {"Alimentation": 400.0}

    client.post("/budgets", data={
        "action": "delete", "category": "Alimentation"})
    assert _json.loads(path.read_text(encoding="utf-8"))["budgets"] == {}
    path.unlink(missing_ok=True)


def test_budget_amount_error_rerenders_the_dashboard(client):
    """A budget that cannot be set re-renders the dashboard with the error:
    the failed amount is not silently dropped, and nothing is written."""
    store_ = client.application.extensions["pms_store"]
    path = store_.path.with_name("budgets.json")
    path.unlink(missing_ok=True)

    # Posted from the page that shows the form: the monthly panel needs two
    # months, and the default view is now the month in progress.
    page = {"Referer": "http://localhost/?preset=12m"}
    body = text(client.post("/budgets", headers=page, data={
        "action": "add", "category": "Alimentation", "amount": "0"}))
    assert "Montant invalide." in body
    assert "Vérifiez les champs suivants" in body
    field = re.search(r'<input[^>]*id="budget-amount"[^>]*>', body).group(0)
    assert 'aria-invalid="true"' in field
    assert 'value="0"' in field

    body = text(client.post("/budgets", headers=page, data={
        "action": "add", "category": "Alimentation", "amount": "x"}))
    assert "Utilisez le point décimal" in body
    assert not path.exists()


# --- the bucket shares over time -----------------------------------------------

def _shares_section(body: str) -> str:
    start = body.index('id="p-shares"')
    return body[start:body.index("</section>", start)]


def test_the_shares_panel_is_folded_until_asked_for(client):
    """It answers a question the reader has to ask; until then it is one line."""
    folded = _shares_section(text(client.get("/?preset=all")))
    assert '<details class="fold">' in folded
    unfolded = _shares_section(text(client.get("/?preset=all&shares=income")))
    assert '<details class="fold" open>' in unfolded
    # A value nobody offered is not an answer: folded, default base.
    bogus = _shares_section(text(client.get("/?preset=all&shares=everything")))
    assert '<details class="fold">' in bogus


def test_every_option_keeps_the_panel_unfolded(client):
    """The options are data-nav links: a swap that re-rendered the panel folded
    would close it under the reader's pointer."""
    section = _shares_section(text(client.get("/?preset=all&shares=spending&smooth=6")))
    links = re.findall(r'<a class="[^"]*" data-nav\s+href="([^"]+)"', section)
    assert len(links) == len(buckets.SHARE_BASES) + len(buckets.SMOOTHING)
    for href in links:
        query = dict(p.split("=", 1) for p in href.replace("&amp;", "&")
                     .split("?", 1)[1].split("&"))
        assert query["shares"] in buckets.SHARE_BASES
        assert query["from"] and query["to"]
    # "Brut" is the default and is left out, like every default.
    assert any("smooth" not in href for href in links)


def test_the_unfolded_state_rides_along_the_other_links(client):
    body = text(client.get("/?preset=all&shares=income&smooth=3"))
    stack_links = re.findall(r'href="([^"]*stack=bucket[^"]*)"', body)
    assert stack_links and all("shares=income" in h and "smooth=3" in h
                               for h in stack_links)


def test_smoothing_keeps_the_raw_months_in_view(client):
    raw = _shares_section(text(client.get("/?preset=all&shares=income")))
    smooth = _shares_section(text(client.get("/?preset=all&shares=income&smooth=6")))
    assert 'class="raw-line"' not in raw
    assert 'class="raw-line"' in smooth
    assert "Brut, mois par mois" in smooth and "6 mois glissants" in smooth


def test_an_unknown_smoothing_falls_back_to_the_raw_months(client):
    section = _shares_section(text(client.get("/?preset=all&shares=income&smooth=7")))
    assert 'class="raw-line"' not in section


def test_the_spending_base_has_no_save_line_and_no_yardstick(client):
    income = _shares_section(text(client.get("/?preset=all&shares=income")))
    spending = _shares_section(text(client.get("/?preset=all&shares=spending")))
    assert ">Save</text>" in income and 'class="target"' in income
    assert ">Save</text>" not in spending and 'class="target"' not in spending


def test_the_shares_hover_payload_matches_the_lines(client):
    body = text(client.get("/?preset=all&shares=income"))
    payload = chart_data(body)["shares"]
    section = _shares_section(body)
    assert len(payload["series"]) == section.count('class="focus-dot"')
    assert len(payload["labels"]) == len(next(iter(payload["series"].values()))["pts"])
    for series in payload["series"].values():
        assert series["fill"].startswith("var(--")


def test_the_shares_panel_needs_two_whole_months(client):
    """A single month is a point, not an evolution."""
    body = text(client.get("/?from=2025-05-01&to=2025-05-31"))
    assert 'id="p-shares"' not in body
    body = text(client.get("/?from=2025-05-01&to=2025-06-30"))
    assert 'id="p-shares"' in body


def test_the_bucket_card_links_to_the_unfolded_chart(client):
    body = text(client.get("/?preset=all"))
    assert re.search(r'href="/\?[^"]*shares=income[^"]*#p-shares"', body)


def test_shares_fragment_and_full_page_agree(client):
    query = "preset=all&shares=income&smooth=3"
    full = text(client.get(f"/?{query}"))
    fragment = text(client.get(f"/?{query}&fragment=1"))
    assert fragment.strip() in full


# --- colour you can see --------------------------------------------------------

def _contrast(a: str, b: str) -> float:
    def lum(hex_colour: str) -> float:
        channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
                  for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    high, low = sorted((lum(a), lum(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_non_classe_is_a_mark_you_can_see_in_both_themes(client):
    """It borrowed the axis grey: 1.75:1 in light, 1.48:1 in dark -- a line
    nobody could see. A mark needs 3:1 against its surface (WCAG 1.4.11)."""
    css = text(client.get("/static/app.css"))
    light = css[css.index(":root {"):]
    dark = css[css.index(':root[data-theme="dark"] {'):]
    for block in (light, dark):
        block = block[:block.index("}")]
        unsorted = re.search(r"--unsorted:\s*(#[0-9a-f]{6})", block).group(1)
        surface = re.search(r"--surface:\s*(#[0-9a-f]{6})", block).group(1)
        assert _contrast(unsorted, surface) >= 3, (unsorted, surface)
    assert "var(--unsorted)" in text(client.get("/?preset=all"))


# --- panels one reads now and then --------------------------------------------------

@pytest.mark.parametrize("panel", ["p-years", "p-profiles", "p-country", "p-custodian"])
def test_a_rarely_read_panel_is_folded_behind_its_heading(client, panel):
    """The dashboard was seventeen screens long. These panels are there, one
    click away; their summary names them, so the sommaire still points at a
    heading."""
    body = text(client.get("/?preset=all"))
    start = body.index(f'id="{panel}"')
    section = body[start:body.index("</section>", start)]
    assert '<details class="fold">' in section
    assert re.search(r"<summary>\s*<span class=\"chev\"[^>]*>▸</span>\s*<h3>", section)


def test_the_calendar_ships_its_figures_once_not_on_every_cell(client):
    """Each of 730 cells used to carry a title, a JSON row list and a hint:
    the calendar was 35-47 % of the page. The figures ride in #chartData,
    and the twin table waits to be asked for."""
    body = text(client.get("/?preset=all"))
    start = body.index('id="p-calendar"')
    section = body[start:body.index("</section>", start)]
    assert "data-rows" not in section and "data-title" not in section
    assert "<tbody>" not in section
    assert 'href="/?' in section and "table=calendar" in section   # no-JS path
    days = chart_data(body)["calendar"]
    assert len(days) > 100 and all(len(v) == 2 for v in days.values())
    # Keyboard and screen-reader users still get each day's figures.
    assert re.search(r'aria-label="\d{2}\.\d{2}\.\d{4} : [\d’.]+ CHF, \d+ transactions?"', section)

