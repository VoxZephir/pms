"""The forecast's net worth: the two sides of the wealth tax, the band and
its volatility, the measured half joined to the projected one."""

from __future__ import annotations

import json

import pytest
from webhelpers import api, plans_path, savings_snapshots

from pms import plans


@pytest.fixture
def pockets(client):
    paths = savings_snapshots(client)
    plan = plans_path(client)
    plan.unlink(missing_ok=True)
    yield plan
    plan.unlink(missing_ok=True)
    for p in paths:
        p.unlink(missing_ok=True)


def _wealth(client, query: str = "") -> dict:
    return api(client, f"/api/previsions{'?' + query if query else ''}")


def test_no_net_worth_without_the_pockets(client):
    """Without them the curve would just be the cash line above it."""
    assert _wealth(client)["wealth"] is None


def test_the_net_worth_splits_on_the_wealth_tax(client, pockets):
    """A pillar 3a sits outside taxable wealth until it is drawn: the same
    money has two honest readings, chosen in the URL."""
    views = {v["id"]: v for v in _wealth(client)["wealth_views"]}
    assert set(views) == {"all", "taxable", "sheltered"}
    every = _wealth(client)["wealth"]
    taxable = _wealth(client, "wealth=taxable")["wealth"]
    sheltered = _wealth(client, "wealth=sheltered")["wealth"]
    # The sheltered pocket holds no current account: if the cash leaked in,
    # the two curves would match.
    assert sheltered["observed"] != taxable["observed"]
    assert sheltered["include_cash"] is False and taxable["include_cash"] is True
    assert every["observed"][-1]["total"] > sheltered["observed"][-1]["total"]
    assert _wealth(client, "wealth=nonsense")["wealth_view"] == "all"


def test_the_measured_half_joins_the_projection(client, pockets):
    """The last measured level is where the projection starts: one quantity,
    measured then assumed."""
    wealth = _wealth(client)["wealth"]
    assert len(wealth["observed"]) >= 2
    assert wealth["start"] == pytest.approx(wealth["observed"][-1]["total"], abs=1)
    assert len(wealth["rows"]) == len(_wealth(client)["projection"]["rows"])


def test_the_band_holds_each_projected_month(client, pockets):
    _edit_vol(client, "12")
    rows = _wealth(client)["wealth"]["rows"]
    assert all(r["low"] <= r["total"] <= r["high"] for r in rows)
    assert rows[-1]["high"] - rows[-1]["low"] > rows[0]["high"] - rows[0]["low"]  # widens in √t


def test_a_declared_zero_volatility_draws_no_band(client, pockets):
    _edit_vol(client, "0")
    wealth = _wealth(client)["wealth"]
    assert wealth["vol"] == 0.0 and wealth["vol_source"] == "declared"
    assert all(r["low"] == r["high"] for r in wealth["rows"])


def test_the_declared_volatility_replaces_the_measured_one(client, pockets):
    _edit_vol(client, "12")
    assert plans.Plan.load(pockets).vol == 0.12
    wealth = _wealth(client)["wealth"]
    assert (wealth["vol"], wealth["vol_source"]) == (0.12, "declared")
    _edit_vol(client, "")
    assert plans.Plan.load(pockets).vol is None
    assert _wealth(client)["wealth"]["vol_source"] == "measured"


def test_a_bad_volatility_is_refused(client):
    path = plans_path(client)
    path.unlink(missing_ok=True)
    assert "en %" in _edit_vol(client, "beaucoup")["errors"]["plan-vol"]
    assert _edit_vol(client, "-5")["errors"]["plan-vol"] == "La volatilité est entre 0 % et 100 %."
    assert _edit_vol(client, "150")["errors"]["plan-vol"] == "La volatilité est entre 0 % et 100 %."
    assert not path.exists()


def test_a_legacy_rate_file_still_compounds(client, pockets):
    """A pre-schedule plans.json carrying only `rate` compounds at that rate:
    the page must not say the pockets are frozen while the curve rises."""
    pockets.write_text(json.dumps({"version": plans.VERSION, "rate": 0.05}), encoding="utf-8")
    assert _wealth(client)["wealth"]["rate"] == pytest.approx(0.05)


def test_the_log_axis_is_asked_for_in_the_url(client, pockets):
    """The browser falls back to linear when a value is not positive; the
    server only carries the choice, validated."""
    assert _wealth(client, "yscale=log")["yscale"] == "log"
    assert _wealth(client, "yscale=nonsense")["yscale"] == "linear"


def _edit_vol(client, amount: str) -> dict:
    return client.post("/api/previsions", json={"action": "vol", "amount": amount}).get_json()


def _post(client, body: dict) -> None:
    assert client.post("/api/previsions", json=body).status_code == 200


@pytest.mark.parametrize("view", ["all", "taxable", "sheltered"])
def test_the_pockets_add_up_to_the_curve(client, pockets, view):
    """Split by pocket and by asset class, the projection is the same net
    worth, month by month; the flows explain the change to the centime."""
    _post(client, {"action": "rate", "months": ["12"], "rates": ["6"]})
    _post(client, {"action": "contrib", "amount": "500", "every": "month",
                   "months": "12", "pocket": "3a", "start": ""})
    _post(client, {"action": "contrib", "amount": "300", "every": "month",
                   "months": "12", "pocket": "taxable", "start": ""})
    wealth = _wealth(client, "" if view == "all" else f"wealth={view}")["wealth"]
    parts = wealth["parts"]
    for row, by_pocket, by_class in zip(wealth["rows"], parts["pockets"]["projected"],
                                        parts["classes"]["projected"]):
        assert sum(by_pocket.values()) == pytest.approx(row["total"], abs=0.05)
        assert sum(by_class.values()) == pytest.approx(row["total"], abs=0.05)
    for seen, by_pocket in zip(wealth["observed"], parts["pockets"]["observed"]):
        assert sum(by_pocket.values()) == pytest.approx(seen["total"], abs=0.05)
    assert parts["start"] == pytest.approx(wealth["start"], abs=0.05)
    assert parts["end"] == pytest.approx(wealth["final"]["total"], abs=0.05)
    assert parts["start"] + sum(f["amount"] for f in parts["flows"]) == \
        pytest.approx(parts["end"], abs=0.05)
    table = {t["key"]: t for t in parts["table"]}
    for t in table.values():
        assert t["start"] + t["paid"] + t["growth"] == pytest.approx(t["end"], abs=0.05) \
            or t["key"] == "swiss"
    if view != "sheltered":
        # The cash pays both series; only the one heading for a pocket of the
        # view stays in it.
        assert table["swiss"]["paid"] == pytest.approx(-9_600 if view == "all" else -3_600, abs=0.05)
    if view == "taxable":
        assert any(f["key"] == "left" and f["amount"] == pytest.approx(-6_000) for f in parts["flows"])
    if view == "sheltered":
        assert table["finp"]["paid"] == pytest.approx(6_000)


# --- unlisted shares and a barème per pocket ------------------------------------------

SHARE = {"holdings": [{"id": "s1", "name": "Port Exemple SA", "quantity": 1, "payer": "Club Nautique Exemple",
                       "withholding": True, "since": 2025, "values": {"2025": 1000, "2026": 1250}}]}


@pytest.fixture
def share(client, pockets):
    path = client.application.extensions["pms_store"].path.with_name("holdings.json")
    path.write_text(json.dumps(SHARE), encoding="utf-8")
    yield path
    path.unlink(missing_ok=True)


def _edit(client, body: dict) -> dict:
    return client.post("/api/previsions", json=body).get_json()


def _pocket_rates(wealth: dict, key: str) -> dict | None:
    return next((p for p in wealth["pockets_rates"] if p["id"] == key), None)


def test_an_unlisted_share_counts_in_the_net_worth_at_its_declared_value(client, share):
    on, off = _wealth(client)["wealth"], _wealth(client, "titres=0")["wealth"]
    assert on["observed"][-1]["total"] == pytest.approx(off["observed"][-1]["total"] + 1250, abs=0.01)
    assert on["pockets_start"]["titres"] == 1250 and "titres" not in off["pockets_start"]
    taxable = _wealth(client, "wealth=taxable")["wealth"]
    assert taxable["pockets_start"]["titres"] == 1250
    assert "titres" not in _wealth(client, "wealth=sheltered")["wealth"]["pockets_start"]
    # Held at its value, even under a common return: nobody chose one for it.
    _edit(client, {"action": "rate", "months": ["12"], "rates": ["10"]})
    grown = _wealth(client)["wealth"]
    titres = _pocket_rates(grown, "titres")
    assert titres["own"] and titres["rate_segments"] == [] and titres["vol_effective"] == 0.0
    assert grown["parts"]["table"][-1]["key"] == "titres"
    row = next(t for t in grown["parts"]["table"] if t["key"] == "titres")
    assert (row["start"], row["growth"], row["end"]) == (1250, 0.0, 1250)


def test_a_pocket_can_follow_the_common_barème_or_its_own(client, share):
    _edit(client, {"action": "rate", "months": ["12"], "rates": ["4"]})
    assert _edit(client, {"action": "pocket-common", "rate_pocket": "titres"})["ok"]
    assert not _pocket_rates(_wealth(client)["wealth"], "titres")["own"]
    # The 3a on a barème of its own: the copy starts from the common one.
    _edit(client, {"action": "pocket-own", "rate_pocket": "finp"})
    finp = _pocket_rates(_wealth(client)["wealth"], "finp")
    assert finp["own"] and finp["rate_segments"] == [[12, 0.04]]
    _edit(client, {"action": "rate", "rate_pocket": "finp", "months": ["24"], "rates": ["-20"]})
    _edit(client, {"action": "vol", "rate_pocket": "finp", "amount": "60"})
    wealth = _wealth(client)["wealth"]
    finp = _pocket_rates(wealth, "finp")
    assert finp["rate_segments"] == [[24, -0.2]] and finp["vol_effective"] == 0.6
    plan = plans.Plan.load(plans_path(client))
    assert plan.rate_segments == [(12, 0.04)] and plan.vol is None   # the common one untouched
    table = {t["key"]: t for t in wealth["parts"]["table"]}
    assert table["finp"]["growth"] < 0 < table["ibkr"]["growth"]
    # The curve is the pockets added up, to the centime.
    final = wealth["rows"][-1]
    pockets = sum(t["end"] for k, t in table.items() if k != "swiss")
    assert final["invested"] == pytest.approx(pockets, abs=0.05)
    # Back to the common barème.
    _edit(client, {"action": "pocket-common", "rate_pocket": "finp"})
    assert not _pocket_rates(_wealth(client)["wealth"], "finp")["own"]


def test_a_market_scenario_and_the_years_apply_to_one_pocket(client, share):
    _edit(client, {"action": "scenario-apply", "scenario": "builtin:bad-year", "rate_pocket": "ibkr"})
    ibkr = _pocket_rates(_wealth(client)["wealth"], "ibkr")
    assert ibkr["own"] and ibkr["rate_segments"] == [[12, -0.17], [48, 0.04]]
    assert plans.Plan.load(plans_path(client)).rate_segments == []
    years = ibkr["rate_years"]
    status = client.post("/api/previsions", json={"action": "rate-years", "rate_pocket": "ibkr",
                                                  "rates": ["7,5"] * len(years)}).status_code
    assert status == 200
    assert _pocket_rates(_wealth(client)["wealth"], "ibkr")["rate_segments"] == [[sum(y["months"] for y in years), 0.075]]


def test_an_unknown_pocket_is_refused(client, pockets):
    response = client.post("/api/previsions", json={"action": "rate", "rate_pocket": "maison",
                                                    "months": ["12"], "rates": ["4"]})
    assert response.status_code == 400 and "rate_pocket" in response.get_json()["errors"]


def test_baseline_claude_sets_every_pocket_from_the_common_barème(client, share):
    assert _edit(client, {"action": "scenario-apply", "scenario": "builtin:baseline-claude"})["ok"]
    plan = plans.Plan.load(plans_path(client))
    assert (plan.rate_segments, plan.vol) == ([(12, 0.04)], 0.12)
    assert plan.own_rates("ibkr") == {"rate_segments": [(12, 0.08)], "vol": 0.23}
    assert plan.own_rates("titres")["rate_segments"] == [(12, 0.12)]
    # On one pocket, only that pocket's line.
    _edit(client, {"action": "pocket-common", "rate_pocket": "finp"})
    _edit(client, {"action": "scenario-apply", "scenario": "builtin:baseline-claude", "rate_pocket": "finp"})
    assert plans.Plan.load(plans_path(client)).own_rates("finp") == {"rate_segments": [(12, 0.045)], "vol": 0.14}
    card = next(s for s in _wealth(client)["builtin_scenarios"] if s["key"] == "baseline-claude")
    assert {p["id"] for p in card["pockets"]} == set(plans.POCKET_KEYS)
