"""IBKR from its Flex Web Service, the 3a's proxies from Yahoo, `--refresh`.

The statement below is invented, in the shape the Flex Web Service serves
(sections Net Asset Value in Base, Open Positions, Prior Period Positions,
Cash Report, Cash Transactions, Trades, Conversion Rates).
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from pms import benchmarks, cli, flex

D = dt.date

STATEMENT = """<FlexQueryResponse queryName="pms" type="AF">
 <FlexStatements count="1">
  <FlexStatement accountId="U0000000" fromDate="20260929" toDate="20261007"
                 period="Last7CalendarDays" whenGenerated="20261008;101530">
   <AccountInformation accountId="U0000000" currency="CHF"/>
   <EquitySummaryInBase>
    <EquitySummaryByReportDateInBase reportDate="20260929" total="990.00"/>
    <EquitySummaryByReportDateInBase reportDate="20260930" total="1000.00"/>
    <EquitySummaryByReportDateInBase reportDate="20261006" total="1510.00"/>
    <EquitySummaryByReportDateInBase reportDate="20261007" total="1525.50"/>
   </EquitySummaryInBase>
   <CashReport>
    <CashReportCurrency currency="BASE_SUMMARY" endingCash="12.30"/>
    <CashReportCurrency currency="CHF" endingCash="2.30"/>
    <CashReportCurrency currency="USD" endingCash="12.50"/>
   </CashReport>
   <OpenPositions>
    <OpenPosition currency="USD" fxRateToBase="0.8" assetCategory="STK" symbol="FUND"
                  position="60" markPrice="31.5" positionValue="1890"
                  fifoPnlUnrealized="90" levelOfDetail="SUMMARY"/>
   </OpenPositions>
   <PriorPeriodPositions>
    <PriorPeriodPosition symbol="FUND" date="20261006" price="31.0"/>
   </PriorPeriodPositions>
   <CashTransactions>
    <CashTransaction currency="CHF" fxRateToBase="1" type="Deposits/Withdrawals"
                     dateTime="20260930;120000" amount="500" levelOfDetail="DETAIL"/>
    <CashTransaction currency="CHF" fxRateToBase="1" type="Deposits/Withdrawals"
                     dateTime="20261005;120000" amount="500" levelOfDetail="DETAIL"/>
    <CashTransaction currency="USD" fxRateToBase="0.8" type="Dividends" symbol="FUND"
                     dateTime="20261006" amount="10" levelOfDetail="DETAIL"/>
    <CashTransaction currency="USD" fxRateToBase="0.8" type="Withholding Tax" symbol="FUND"
                     dateTime="20261006" amount="-1.5" levelOfDetail="DETAIL"/>
    <CashTransaction currency="USD" fxRateToBase="0.8" type="Dividends" symbol="FUND"
                     dateTime="20261006" amount="10" levelOfDetail="SUMMARY"/>
   </CashTransactions>
   <Trades>
    <Trade currency="USD" fxRateToBase="0.8" assetCategory="STK" symbol="FUND"
           tradeDate="20261005" quantity="20" tradePrice="30" ibCommission="-0.35"
           ibCommissionCurrency="USD" buySell="BUY" levelOfDetail="EXECUTION"/>
    <Trade currency="CHF" fxRateToBase="1" assetCategory="CASH" symbol="USD.CHF"
           tradeDate="20261005" quantity="600" tradePrice="0.8" ibCommission="-2"
           ibCommissionCurrency="CHF" buySell="BUY" levelOfDetail="EXECUTION"/>
   </Trades>
   <ConversionRates>
    <ConversionRate reportDate="20261007" fromCurrency="USD" toCurrency="CHF" rate="0.79"/>
   </ConversionRates>
  </FlexStatement>
 </FlexStatements>
</FlexQueryResponse>"""

SENT = """<FlexStatementResponse><Status>Success</Status>
<ReferenceCode>42</ReferenceCode><Url>https://flex.invalid/GetStatement</Url>
</FlexStatementResponse>"""
BUSY = """<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019</ErrorCode>
<ErrorMessage>Statement generation in progress.</ErrorMessage></FlexStatementResponse>"""
TOKEN = "SECRET-TOKEN-123"


def _snapshot(tmp_path, last="2026-09-30"):
    path = tmp_path / "ibkr.json"
    path.write_text(json.dumps({
        "account": {"net_liquidation": 1000.0, "buying_power": 5.0},
        "nav": [["2026-09-30", 1000.0]], "nav_daily": [["2026-09-30", 20.0]],
        "positions": [{"name": "FUND", "market_value": 50.0,
                       "asset_split": {"Actions": 100}},
                      {"name": "OLD", "market_value": 10.0}],
        "costs": [],
        "journal": {"source": "export.csv", "first": "2025-01-01", "last": last,
                    "flows": [["2026-09-01", 500.0]], "income": [], "positions": []},
    }), encoding="utf-8")
    return path


def test_the_statement_reads_in_francs_detail_rows_only():
    s = flex.parse(STATEMENT)
    assert s["end"] == D(2026, 10, 7) and s["base"] == "CHF"
    assert s["nav"][-1] == (D(2026, 10, 7), 1525.5)
    fund = s["positions"][0]
    assert fund["market_value_chf"] == 1512.0 and fund["unrealized_pnl_pct"] == 5.0
    assert s["cash"] == [{"currency": "CHF", "amount": 2.3}, {"currency": "USD", "amount": 12.5}]
    assert s["base_cash"] == 12.3 and s["fx_usd"] == 0.79
    assert s["flows"] == [(D(2026, 9, 30), 500.0), (D(2026, 10, 5), 500.0)]
    # The summary row repeats the detail: one dividend, not two.
    assert [e["amount_chf"] for e in s["income"]] == [8.0]
    costs = {c["label"]: c for c in s["costs"]}
    assert costs["Retenue sur dividende FUND"]["amount_chf"] == 1.2
    assert costs["Achat 20 FUND"]["amount_chf"] == 0.28
    assert costs["Conversion USD.CHF 600.00"]["kind"] == "commission de change"
    assert s["prices"] == [(D(2026, 10, 6), 31.0), (D(2026, 10, 7), 31.5)]
    assert s["holding"]["shares"] == {"FUND": 60.0}


def test_folding_appends_only_what_is_new(tmp_path):
    path = _snapshot(tmp_path)
    report = flex.fold(flex.parse(STATEMENT), path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert report["nav"] == 2 and report["nav_daily"] == 2 and report["costs"] == 3
    assert [p[0] for p in raw["nav"]][-2:] == ["2026-10-06", "2026-10-07"]
    # The declared split survives the update; the fund sold is gone.
    assert raw["positions"][0]["asset_split"] == {"Actions": 100}
    assert report["sold"] == ["OLD"] and len(raw["positions"]) == 1
    assert raw["account"] == {"net_liquidation": 1525.5, "buying_power": 5.0,
                              "total_cash": 12.3}
    # The 30.09 deposit is already in the journal; the 05.10 one is new.
    assert raw["journal"]["flows"] == [["2026-09-01", 500.0], ["2026-10-05", 500.0]]
    assert raw["journal"]["last"] == "2026-10-07" and report["journal"]["gap"] is None
    assert raw["journal"]["positions"][-1]["date"] == "2026-10-07"
    again = flex.fold(flex.parse(STATEMENT), path)
    assert again["nav"] == 0 and again["costs"] == 0 and again["journal"]["flows"] == 0


def test_days_nobody_read_are_said(tmp_path):
    path = _snapshot(tmp_path, last="2026-09-01")
    report = flex.fold(flex.parse(STATEMENT), path)
    assert report["journal"]["gap"] == ["2026-09-01", "2026-09-29"]


def test_the_download_waits_for_the_statement_and_never_shows_the_token():
    replies = iter([SENT, BUSY, STATEMENT])
    asked, waited = [], []

    def http(url):
        asked.append(url)
        return next(replies)
    assert flex.download(TOKEN, "7", http=http, wait=waited.append) == STATEMENT
    assert len(asked) == 3 and waited == [5]
    assert asked[1].startswith("https://flex.invalid/GetStatement?t=SECRET-TOKEN-123&q=42")

    refused = "<FlexStatementResponse><Status>Fail</Status><ErrorCode>1015</ErrorCode>" \
              "<ErrorMessage>Token is invalid.</ErrorMessage></FlexStatementResponse>"
    with pytest.raises(flex.FlexError) as error:
        flex.download(TOKEN, "7", http=lambda url: refused, wait=waited.append)
    assert "1015" in str(error.value) and TOKEN not in str(error.value)

    def down(url):
        raise OSError("refused " + url)
    with pytest.raises(flex.FlexError) as error:
        flex.download(TOKEN, "7", http=down, wait=waited.append)
    assert TOKEN not in str(error.value)


def test_a_missing_or_template_config_is_said(tmp_path):
    with pytest.raises(flex.FlexError, match="pas configuré"):
        flex.load_config(tmp_path / "ibkr_flex.json")
    template = tmp_path / "ibkr_flex.json"
    template.write_text('{"token": "<jeton>", "query_id": "<numéro>"}', encoding="utf-8")
    with pytest.raises(flex.FlexError, match="manquant"):
        flex.load_config(template)


def test_the_3a_proxies_come_from_plain_closes():
    days = [int(dt.datetime(2026, 10, d, 12, tzinfo=dt.timezone.utc).timestamp()) for d in (5, 6)]
    closes = {"^SSMI": [100.0, 101.0], "URTH": [50.0, 51.0], "CHF=X": [None, 0.8],
              "EEM": [60.0, None]}

    def chart(ticker, start, end):
        return {"timestamp": days, "indicators": {"quote": [{"close": closes[ticker]}]}}
    points = benchmarks.proxies(D(2026, 10, 1), D(2026, 10, 7), chart=chart)
    assert points["SMI"] == [["2026-10-05", 100.0], ["2026-10-06", 101.0]]
    assert points["URTHxCHF"] == [["2026-10-06", 40.8]]   # no rate on the 5th
    assert points["EEM"] == [["2026-10-05", 60.0]]


def test_refresh_runs_once_a_day_and_retries_what_failed(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setattr(cli, "INBOX", tmp_path / "inbox")
    outcome = {"code": 1}
    monkeypatch.setattr(cli, "_benchmarks", lambda path: outcome["code"])
    assert cli.main(["--ledger", str(ledger), "--refresh", "--daily"]) == 0
    from pms import refresh
    assert refresh.due(tmp_path)                            # failed: retried next time
    assert "réessayer" in capsys.readouterr().err
    outcome["code"] = 0
    cli.main(["--ledger", str(ledger), "--refresh", "--daily"])
    assert not refresh.due(tmp_path)
    outcome["code"] = 1                                     # would fail, but is not run
    cli.main(["--ledger", str(ledger), "--refresh", "--daily"])
    assert "rien à faire" in capsys.readouterr().out
