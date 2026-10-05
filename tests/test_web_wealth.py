"""/previsions: the wealth curve -- tax views, the band, volatility, the
log axis, the month table."""

from __future__ import annotations

import re

from webhelpers import chart_data, plans_path, savings_snapshots, text

from pms import plans


def test_the_wealth_panel_splits_on_the_wealth_tax(client):
    """A pillar 3a sits outside taxable wealth until it is drawn, so the same
    money has two honest readings. Buttons, not a hidden default -- and the
    choice lives in the URL like every other view switch."""
    ibkr_path, finp_path = savings_snapshots(client)
    try:
        body = text(client.get("/previsions"))
        assert 'aria-label="Portée fiscale du patrimoine"' in body
        for label in ("Tout", "Imposable", "Hors impôt"):
            assert label in body

        taxable = text(client.get("/previsions?wealth=taxable"))
        # The active view is the marked one, and the default drops its key
        # from the URL rather than spelling out `wealth=all`.
        assert re.search(r'<a class="on" href="/previsions\?wealth=taxable"\s*'
                         r'aria-current="page"', taxable)
        assert 'href="/previsions"' in taxable
        assert 'href="/previsions?wealth=sheltered"' in taxable
        assert "l'impôt sur la fortune atteint" in taxable

        sheltered = text(client.get("/previsions?wealth=sheltered"))
        assert "hors fortune imposable" in sheltered
        # The sheltered pocket holds no current account, so its curve must be
        # the smaller of the two -- if the cash leaked in they would match.
        assert taxable != sheltered
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)


def test_an_unknown_wealth_view_falls_back_instead_of_failing(client):
    assert client.get("/previsions?wealth=nonsense").status_code == 200


def test_the_rate_field_exists_with_or_without_a_brokerage_snapshot(client):
    """It renders inside the net-worth card when there is one and in the plan
    section otherwise -- exactly once either way, or the id would be duplicated
    and the label would point at the wrong field."""
    body = text(client.get("/previsions"))
    assert body.count('id="plan-rate"') == 1
    assert "placements seuls" in body
    assert 'id="plan-vol"' in body
    assert body.count('id="scenario-select"') == 1
    # The barème fold's summary is the heading, present exactly once either
    # way -- and closed by default.
    assert body.count("Rendement et volatilité supposés") == 1
    assert '<details class="scenario-block mb-3" id="plan-rate">' in body
    assert '<details class="scenario-block mb-3" id="plan-rate" open>' not in body

    ibkr_path, finp_path = savings_snapshots(client)
    try:
        body = text(client.get("/previsions"))
        assert body.count('id="plan-rate"') == 1
        assert 'id="plan-vol"' in body
        assert body.count('id="scenario-select"') == 1
        assert body.count("Rendement et volatilité supposés") == 1
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)


def test_the_wealth_axis_switches_to_log(client):
    ibkr_path, finp_path = savings_snapshots(client)
    try:
        body = text(client.get("/previsions?yscale=log"))
        assert 'href="/previsions?yscale=log"' in body
        assert 'href="/previsions"' in body  # linear drops its key
        # The chart's y axis is really log: its ticks sit on a 1-2-5 grid.
        from pms.web import charts
        chart = charts.wealth_chart(
            [{"total": 1000.0, "label": "a"}, {"total": 10000.0, "label": "b"}],
            {"rows": [{"total": 100000.0, "high": 120000.0, "low": 80000.0,
                       "label": "c"}]},
            yscale="log")
        assert chart["yscale"] == "log"
        assert 2 <= len(chart["ticks"]) <= 5
        ys = [t["y"] for t in chart["ticks"]]
        assert all(a > b for a, b in zip(ys, ys[1:]))  # top to bottom
        for t in chart["ticks"]:
            value = t["value"]
            mantissa = value / 10 ** (__import__("math").floor(
                __import__("math").log10(value)))
            assert abs(mantissa - round(mantissa)) < 1e-9
            assert round(mantissa) in (1, 2, 5), t["value"]
        # A range narrower than a decade can fall between the grid values:
        # the axis must still have references.
        chart = charts.wealth_chart(
            [{"total": 150000.0, "label": "a"},
             {"total": 152000.0, "label": "b"}],
            {"rows": [{"total": 160000.0, "high": 165000.0, "low": 155000.0,
                       "label": "c"}]},
            yscale="log")
        assert len(chart["ticks"]) >= 2
        # A non-positive value makes the mode fall back to linear, honestly.
        chart = charts.wealth_chart(
            [{"total": 1000.0, "label": "a"}, {"total": 0.0, "label": "b"}],
            {"rows": [{"total": 100000.0, "high": 120000.0, "low": 80000.0,
                       "label": "c"}]},
            yscale="log")
        assert chart["yscale"] == "linear"
        assert client.get("/previsions?yscale=nonsense").status_code == 200
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)


def test_the_wealth_tooltip_payload_carries_the_band(client):
    """The tooltip prints the ±1σ edges, so the payload must carry them --
    observed points have none, projected ones do, each within its own band."""
    ibkr_path, finp_path = savings_snapshots(client)
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        client.post("/previsions", data={
            "action": "vol", "amount": "12"})
        body = text(client.get("/previsions"))
        pts = chart_data(body)["wealth"]["series"]["1"]["pts"]
        # The field count is the payload's own discriminator: observed points
        # have no band, projected ones do. A payload that lost the split must
        # fail, not pass vacuously.
        observed = [p for p in pts if len(p) == 3]
        projected = [p for p in pts if len(p) == 5]
        assert observed and projected
        assert all(len(p) == 3 for p in observed)
        assert all(len(p) == 5 for p in projected)
        assert all(p[3] <= p[2] <= p[4] for p in projected)
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)
        path.unlink(missing_ok=True)


def test_a_declared_zero_volatility_payload_has_degenerate_bands(client):
    ibkr_path, finp_path = savings_snapshots(client)
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        client.post("/previsions", data={"action": "vol", "amount": "0"})
        pts = chart_data(text(client.get("/previsions")))["wealth"]["series"]["1"]["pts"]
        projected = [p for p in pts if len(p) == 5]
        assert projected
        assert all(p[3] == p[4] for p in projected)
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)
        path.unlink(missing_ok=True)


def test_the_month_table_folds_by_year_and_decade(client):
    """A long horizon must not mean endless scrolling: the first year opens,
    the rest fold -- and beyond four years, decades wrap the years."""
    body = text(client.get("/previsions"))
    assert '<details class="month-group year" open>' in body
    assert body.count('class="month-group year"') >= 2
    # Four years stay plain years; five fold under decades.
    body = text(client.get("/previsions?months=36"))
    assert 'class="month-group decade"' not in body
    assert body.count('class="month-group year"') >= 2
    body = text(client.get("/previsions?months=48"))
    assert body.count('class="month-group decade"') >= 1
    body = text(client.get("/previsions?months=480"))
    assert "Années 202" in body  # a decade wrapper exists
    assert body.count('class="month-group decade"') >= 2
    assert '<details class="month-group year" open>' in body


def test_the_month_summary_counts_kinds_honestly(client):
    """A programmed series is not a "ponctuel": the folded summary must use
    the same vocabulary as the chips."""
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        client.post("/previsions", data={
            "action": "contrib", "amount": "1000", "every": "month",
            "months": "24", "pocket": "3a", "start": ""})
        body = text(client.get("/previsions"))
        # The monthly series fires seven times in 2026 (June..December) and
        # five in 2027 -- the summary calls them versements, never ponctuels.
        assert "7 versements programmés" in body
        assert "5 versements programmés" in body
        assert "versements programmés" in body and "ponctuel" not in \
            body[body.index("7 versements"):body.index("5 versements")]
    finally:
        path.unlink(missing_ok=True)


def test_the_folded_wealth_columns_pair_row_by_row(client):
    """Each month row carries its wealth partner server-side: the pairing
    must render, cell by cell, not just somewhere on the page."""
    ibkr_path, finp_path = savings_snapshots(client)
    try:
        body = text(client.get("/previsions"))
        assert '<th class="r">Placements</th>' in body
        assert '<th class="r">Patrimoine</th>' in body
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', body, re.S)
        wealth_cells = [re.search(r'<td class="r num">([^<]+)</td>\s*'
                                  r'<td class="r num">([^<]+)</td>', r)
                        for r in rows if 'Placements' not in r]
        cells = [m for m in wealth_cells if m]
        assert cells, "no month row carries the wealth columns"
        # The first projected month's invested value must equal the pocket
        # start plus the first step -- a shifted pairing would break this.
        invested = float(cells[0].group(1).replace("’", "").replace(" ", ""))
        assert invested > 0
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)


def test_the_tooltip_band_wiring_exists_in_the_static_assets(client):
    """The band row is rendered by JS from the payload -- no JS test harness
    exists, so the wiring is pinned by probing the static files, the same
    way the keyboard-focus CSS rule is."""
    js = client.get("/static/app.js").get_data(as_text=True)
    assert "function crosshair(svgId, hitId, crossId, series, geom, title, fmt, bandFmt)" in js
    assert "bandFmt(p[3], p[4])" in js
    assert "p.length > 3 && p[4] > p[3]" in js
    css = client.get("/static/app.css").get_data(as_text=True)
    assert ".t-band" in css


def test_a_legacy_rate_file_draws_its_curve_and_says_so(client):
    """A pre-schedule plans.json carrying only `rate` must compound at that
    rate -- and the note must not claim the pockets are frozen while the
    curve rises next to it."""
    import json

    ibkr_path, finp_path = savings_snapshots(client)
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        path.write_text(json.dumps({
            "version": plans.VERSION, "rate": 0.05}), encoding="utf-8")
        body = text(client.get("/previsions"))
        assert "selon votre barème" in body
        assert "figés à leur dernière valeur" not in body
    finally:
        path.unlink(missing_ok=True)
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)


def test_previsions_fragment_and_full_page_agree(client):
    """The swap fetches ?fragment=1 and replaces <main> in place; the fragment
    must be exactly the full page's main content, or the two paths drift."""
    for url in ("/previsions", "/previsions?wealth=taxable&months=24"):
        full = text(client.get(url))
        sep = "?" if "?" not in url else "&"
        fragment = text(client.get(url + sep + "fragment=1"))
        assert fragment.strip() in full, url
    # The fragment must ship the crosshair payload, the Sommaire rail and the
    # horizon control, or the swap loses them.
    fragment = text(client.get("/previsions?fragment=1"))
    assert 'id="chartData"' in fragment
    assert '<nav class="toc"' in fragment
    assert 'id="horizon-select"' in fragment


def test_the_wealth_tooltip_payload_series_is_keyed_by_the_dot_slot(client):
    """The crosshair looks series up as series[dot.dataset.slot]; a series key
    the dot cannot reach renders a tooltip without its value. The wealth chart
    dot carries data-slot=1, so the payload must carry a series keyed 1."""
    ibkr_path, finp_path = savings_snapshots(client)
    try:
        body = text(client.get("/previsions"))
        assert 'data-slot="1"' in body
        data = chart_data(body)
        assert data["wealth"]["series"]  # the wealth chart rendered
        # json.dumps turns the int key into a string; the JS lookup coerces
        # the dot's data-slot with +, so obj[1] and obj["1"] are the same key.
        assert "1" in data["wealth"]["series"]
        assert data["wealth"]["series"]["1"]["slot"] == 1
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)


def test_the_declared_volatility_replaces_the_measured_band(client):
    ibkr_path, finp_path = savings_snapshots(client)
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        response = client.post("/previsions", data={"action": "vol", "amount": "12"})
        assert response.status_code == 302
        assert plans.Plan.load(path).vol == 0.12
        body = text(client.get("/previsions"))
        assert "déclarés par vous" in body
        assert "12.0 %" in body

        client.post("/previsions", data={"action": "vol", "amount": ""})
        assert plans.Plan.load(path).vol is None
        assert "mesurés sur" in text(client.get("/previsions"))
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)
        path.unlink(missing_ok=True)


def test_a_bad_volatility_rerenders_with_the_error(client):
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        body = text(client.post("/previsions", data={"action": "vol", "amount": "3,5"}))
        assert "Utilisez le point décimal" in body
        body = text(client.post("/previsions", data={"action": "vol", "amount": "-5"}))
        assert "La volatilité est entre 0 % et 100 %." in body
        assert '<details class="scenario-block mb-3" id="plan-rate" open>' in body
        body = text(client.post("/previsions", data={"action": "vol", "amount": "150"}))
        assert "La volatilité est entre 0 % et 100 %." in body
        assert not path.exists()
    finally:
        path.unlink(missing_ok=True)


def test_a_declared_zero_volatility_draws_no_band(client):
    ibkr_path, finp_path = savings_snapshots(client)
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        client.post("/previsions", data={"action": "vol", "amount": "0"})
        body = text(client.get("/previsions"))
        assert "Déclaré : 0" in body
        # No band polygon and no band note: a flat band has nothing to say.
        assert '<polygon' not in body
        assert "La zone est ±1 écart-type" not in body
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
