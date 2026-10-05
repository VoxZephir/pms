"""The exported IBKR transaction history: flows, costs, holdings, value.

An invented export in the real file's shape (three tables in one CSV,
newest first, base-currency amounts) -- never the real one.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from pms import ibkr, ibkr_history, snapshots

HEADER = ("Transaction History,Header,Date,Account,Description,Transaction Type,"
          "Symbol,Quantity,Price,Price Currency,Gross Amount ,Commission,Net Amount\n")


def _export(tmp_path):
    rows = [
        # newest first, as IBKR writes it
        "2025-12-30,U***1,FUND dividend - US Taxes,Foreign Tax Withholding,FUND,-,-,-,-3.0,-,-3.0",
        "2025-12-30,U***1,FUND dividend,Dividend,FUND,-,-,-,20.0,-,20.0",
        "2025-06-27,U***1,Montant net: -1'000 USD.CHF,Forex Trade Component,USD.CHF,-1000.0,0.80,CHF,-1.4,-,-1.4",
        "2025-06-27,U***1,Montant net: 1'000 USD.CHF,Forex Trade Component,USD.CHF,1000.0,0.8014,CHF,-1.1,-,-1.1",
        "2025-01-10,U***1,Withdrawal,Withdrawal,-,-,-,-,-1000.0,-,-1000.0",
        "2025-01-10,U***1,FUND,Sell,FUND,-50.0,22.0,USD,1000.0,-1.0,999.0",
        "2024-07-05,U***1,FUND,Buy,FUND,200.0,20.0,USD,-3600.0,-1.2,-3601.2",
        "2024-07-05,U***1,Montant net: -3'600 CHF.USD,Forex Trade Component,CHF.USD,-3600.0,1.1111,USD,-0.5,-1.8,-0.5",
        "2024-07-01,U***1,Transfert,Deposit,-,-,-,-,3600.0,-,3600.0",
        # the oldest, a tax refund line next to its charges
        "2023-12-29,U***1,OLD - US Taxes,Foreign Tax Withholding,OLD,-,-,-,3.0,-,3.0",
        "2023-12-29,U***1,OLD - US Taxes,Foreign Tax Withholding,OLD,-,-,-,-2.0,-,-2.0",
        "2023-12-29,U***1,OLD - US Taxes,Foreign Tax Withholding,OLD,-,-,-,-2.5,-,-2.5",
    ]
    path = tmp_path / "U1.TRANSACTIONS.20230101.20260101.csv"
    path.write_text("Statement,Header,Nom champ,Valeur champ\n"
                    "Summary,Data,Trésorerie finale,0.0\n"
                    + HEADER + "".join(f"Transaction History,Data,{r}\n" for r in rows),
                    encoding="utf-8")
    return path


def test_flows_costs_and_income_from_the_export(tmp_path):
    rows = ibkr_history.parse(_export(tmp_path))
    assert rows[0]["date"] == dt.date(2023, 12, 29)          # oldest first
    assert ibkr_history.flows(rows) == [(dt.date(2024, 7, 1), 3600.0),
                                        (dt.date(2025, 1, 10), -1000.0)]
    costs = {(c["kind"], c["date"]): c["amount_chf"] for c in ibkr_history.costs(rows)}
    # A withholding nets with its refund: 1.50, not the 4.50 of the charges.
    assert costs[("impôt à la source US", dt.date(2023, 12, 29))] == 1.5
    assert costs[("impôt à la source US", dt.date(2025, 12, 30))] == 3.0
    assert costs[("commission d'achat", dt.date(2024, 7, 5))] == 1.2
    assert costs[("commission de vente", dt.date(2025, 1, 10))] == 1.0
    assert costs[("commission de change", dt.date(2024, 7, 5))] == 1.8
    # Paired conversions without commission cost their spread; a lone
    # conversion's gross is a currency result, not a fee.
    assert costs[("écart de change automatique", dt.date(2025, 6, 27))] == 2.5
    assert sum(i["amount_chf"] for i in ibkr_history.income(rows)) == 20.0


def test_holdings_and_cash_follow_the_trades(tmp_path):
    rows = ibkr_history.parse(_export(tmp_path))
    pos = {p["date"]: p for p in ibkr_history.positions(rows)}
    after_buy = pos[dt.date(2024, 7, 5)]
    assert after_buy["shares"] == {"FUND": 200.0}
    # 3'600 CHF converted at 1.1111 → 3'999.96 USD, 4'000 spent on the fund.
    assert after_buy["cash"]["USD"] == pytest.approx(3600 * 1.1111 - 4000.0)
    assert pos[dt.date(2025, 1, 10)]["shares"] == {"FUND": 150.0}


def test_the_value_is_rebuilt_weekly_before_the_brokers_daily_nav(tmp_path):
    journal = ibkr_history.journal(_export(tmp_path))
    prices = {"FUND": [["2024-07-08", 21.0], ["2024-07-15", 19.0]],
              "USD.CHF": [["2024-07-08", 0.9], ["2024-07-15", 0.9]]}
    points = ibkr_history.rebuild(journal["positions"], prices, dt.date(2024, 7, 16))
    # Friday of each week: 200 × close × rate, plus the cash -- the dollars
    # left from the conversion, and in francs the commissions and the 2023
    # net withholding (−1.50).
    assert [d for d, _ in points] == [dt.date(2024, 7, 12)]
    assert points[0][1] == pytest.approx(200 * 21.0 * 0.9 + (3600 * 1.1111 - 4000) * 0.9
                                         - 1.2 - 1.8 - 1.5, abs=0.05)


def test_the_snapshot_reads_the_journal_and_dates_each_flow_where_it_shows(tmp_path):
    """The broker books a deposit on one day, the NAV moves the next: the
    flow goes to the point that shows it, or it reads as a crash and a jump.
    Flows before the first value point are already inside it."""
    path = tmp_path / "ibkr.json"
    path.write_text(json.dumps({
        "account": {"net_liquidation": 13000.0},
        "nav": [["2026-09-01", 10000.0], ["2026-09-23", 10050.0],
                ["2026-09-24", 12600.0], ["2026-09-30", 12650.0]],
    }), encoding="utf-8")
    journal = {"first": "2023-09-13", "source": "x.csv",
               "flows": [["2023-09-13", 300.0], ["2026-09-23", 2000.0]],
               "costs": [], "income": [], "positions": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["journal"] = journal
    path.write_text(json.dumps(raw), encoding="utf-8")
    snap = ibkr.load(path)
    assert snap["opened"] == dt.date(2023, 9, 13)
    # The journal wins over the ledger: the Swissquote transfer is not
    # counted a second time.
    from types import SimpleNamespace
    ledger = [SimpleNamespace(date=dt.date(2026, 9, 24), kind="Versement pour Interactive Brokers LLC",
                              merchant="", detail=[], amount_chf=-2000.0)]
    assert ibkr.flows(snap, ledger) == [(dt.date(2026, 9, 24), 2000.0)]


def test_merge_journal_replaces_the_costs_with_the_full_record(tmp_path):
    ibkr_path = tmp_path / "ibkr.json"
    ibkr_path.write_text(json.dumps({"account": {"net_liquidation": 1.0},
                                     "nav": [["2026-01-01", 1.0]],
                                     "costs": [{"date": "2026-01-01", "kind": "x",
                                                "label": "partial", "amount_chf": 9.0}]}),
                         encoding="utf-8")
    snapshots.merge_journal(_export(tmp_path), ibkr_path)
    raw = json.loads(ibkr_path.read_text(encoding="utf-8"))
    assert raw["costs_known_from"] == "2023-12-29"
    assert all(c["label"] != "partial" for c in raw["costs"])
    assert raw["journal"]["flows"] == [["2024-07-01", 3600.0], ["2025-01-10", -1000.0]]


def test_money_back_from_the_brokerage_is_not_income():
    """The line names the owner as sender; only the BIC says Interactive
    Brokers. A withdrawal read as a month's salary until this."""
    from pms.categories import classify
    from pms.models import Transaction
    back = Transaction(date=dt.date(2024, 12, 20), reference="1", currency="CHF",
                       amount=4800.0, value_date=None, balance=0.0,
                       kind="Paiement entrant", merchant="ALEX EXEMPLE",
                       detail=["Paiement entrant", "ALEX EXEMPLE",
                               "BIC/SWIFT : IBKRUS33XXX"])
    assert classify(back, rules=[]) == ("Épargne & investissement", "Retrait de courtage")
    salary = Transaction(date=dt.date(2024, 12, 25), reference="2", currency="CHF",
                         amount=5000.0, value_date=None, balance=0.0,
                         kind="Paiement entrant", merchant="EMPLOYEUR SA",
                         detail=["Paiement entrant", "BIC/SWIFT : UBSWCHZH80A"])
    assert classify(salary, rules=[])[0] == "Revenus"
