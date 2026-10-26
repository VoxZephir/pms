"""The transactions table (`/api/transactions`): filters, search, paging,
server-side sorting, and the export that holds exactly what was listed."""

from __future__ import annotations

import csv
import io
import zipfile

from webhelpers import api


def _rows(client, query: str) -> dict:
    return api(client, f"/api/transactions?{query}")


def _count(client, q: str) -> int:
    return _rows(client, f"preset=all&q={q}")["total"]


def test_the_category_filter_keeps_that_category(client):
    rows = _rows(client, "preset=all&category=Alimentation&per=60")["rows"]
    assert rows and {r["category"] for r in rows} == {"Alimentation"}


def test_a_search_narrows_the_result(client):
    assert 0 < _count(client, "coop") < _count(client, "")


# --- the search ----------------------------------------------------------------

def test_one_word_finds_what_the_whole_phrase_finds(client):
    """"twint" alone must find the Twint payments, not only "paiement twint"."""
    assert _count(client, "twint") >= _count(client, "paiement+twint") > 0


def test_every_word_must_match_in_any_order(client):
    both = _count(client, "coop+alimentation")
    assert both == _count(client, "alimentation+coop") > 0
    assert both <= min(_count(client, "coop"), _count(client, "alimentation"))
    assert _count(client, "coop+zzzz") == 0


def test_case_and_accents_do_not_matter(client):
    assert _count(client, "sante") == _count(client, "Sant%C3%A9") > 0


def test_an_amount_or_a_date_is_searchable(client):
    row = next(r for r in _rows(client, "preset=all")["rows"] if r["amount"] < 0)
    assert _count(client, f"{abs(row['amount']):.2f}") > 0
    y, m, d = row["date"].split("-")
    assert _count(client, f"{d}.{m}.{y}") > 0


def test_a_bare_number_is_a_figure_not_a_fragment(client):
    """"20" matched as text would find every row dated 2025 or 2026."""
    row = next(r for r in _rows(client, "preset=all&sort=chf")["rows"]
               if r["amount"] < 0 and abs(r["amount"]) >= 40)
    whole = int(abs(row["amount"]))
    assert 0 < _count(client, str(whole)) < _count(client, "")
    assert _count(client, "twint+20") < _count(client, "twint")


# --- paging and sorting ---------------------------------------------------------

def test_paging_does_not_lose_or_repeat_rows(client):
    first = _rows(client, "preset=all&page=1")
    second = _rows(client, "preset=all&page=2")
    assert first["total"] == second["total"]
    assert {r["key"] for r in first["rows"]}.isdisjoint(r["key"] for r in second["rows"])


def test_the_page_holds_sixty_rows_and_twenty_on_request(client):
    """The dashboard's short list asks for twenty; anything else falls back."""
    assert len(_rows(client, "preset=all")["rows"]) == 60
    assert len(_rows(client, "preset=all&per=20")["rows"]) == 20
    assert len(_rows(client, "preset=all&per=33")["rows"]) == 60


def test_every_column_sorts_both_ways(client):
    for column in ("date", "label", "category", "amount", "chf"):
        down = [r["key"] for r in _rows(client, f"preset=all&sort={column}&dir_sort=desc")["rows"]]
        up = [r["key"] for r in _rows(client, f"preset=all&sort={column}&dir_sort=asc")["rows"]]
        assert down and up and down != up, column


def test_sorting_is_server_side_across_pages(client):
    """A client-side sort would only reorder the rows already loaded, which
    looks right and is wrong."""
    page1 = [abs(r["chf"]) for r in _rows(client, "preset=all&sort=chf&dir_sort=desc&page=1")["rows"]]
    page2 = [abs(r["chf"]) for r in _rows(client, "preset=all&sort=chf&dir_sort=desc&page=2")["rows"]]
    assert min(page1) >= max(page2)


def test_amount_sorts_by_magnitude_not_sign(client):
    """Sorting a statement by signed value buries every large debit."""
    amounts = [abs(r["chf"]) for r in _rows(client, "preset=all&sort=chf&dir_sort=desc")["rows"]]
    assert amounts == sorted(amounts, reverse=True)


def test_a_bucket_opens_on_the_rows_it_counts(client):
    """The bucket panel counts spending; its link opened every row of the
    bucket, income included (income has no bucket of its own): "10" on the
    row, 157 in the list. Hence `dir=out` on the link."""
    summary = api(client, "/api/dashboard?preset=all")["buckets"]
    row = next(r for r in summary["rows"] if r["name"] == "Non classé")
    assert _rows(client, "preset=all&bucket=Non classé&dir=out")["total"] == row["count"]


# --- the export --------------------------------------------------------------------

def test_the_export_carries_the_window_in_its_name(client):
    response = client.get("/export.csv?from=2025-05-01&to=2025-05-31")
    assert response.status_code == 200
    assert 'filename="pms-2025-05-01_2025-05-31.csv"' in response.headers["Content-Disposition"]


def test_the_export_holds_exactly_the_rows_the_table_listed(client):
    """The file is the filter, not the page: all of it, not the first sixty."""
    query = "from=2025-01-01&to=2025-12-31&category=Alimentation"
    listed = _rows(client, query)["total"]
    payload = client.get(f"/export.csv?{query}").get_data()
    table = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"), newline="")))
    assert len(table) - 1 == listed > 60
    assert {row[2] for row in table[1:]} == {"Alimentation"}


def test_the_export_follows_the_sort_that_was_on_screen(client):
    payload = client.get("/export.csv?from=2025-01-01&to=2025-12-31&sort=amount&dir_sort=desc").get_data()
    table = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"), newline="")))
    amounts = [abs(float(row[5])) for row in table[1:]]
    assert amounts == sorted(amounts, reverse=True)


def test_the_xlsx_export_is_a_real_workbook(client):
    response = client.get("/export.xlsx?from=2025-05-01&to=2025-05-31")
    assert response.status_code == 200
    assert "spreadsheetml" in response.headers["Content-Type"]
    assert "xl/worksheets/sheet1.xml" in zipfile.ZipFile(io.BytesIO(response.data)).namelist()


def test_an_unknown_export_format_is_a_404(client):
    assert client.get("/export.pdf?preset=all").status_code == 404


# --- a row -----------------------------------------------------------------------

def test_a_row_carries_its_identity_and_both_amounts(client):
    row = _rows(client, "preset=all&per=20")["rows"][0]
    assert row["key"].count(":") == 1
    assert {"date", "label", "category", "bucket", "amount", "currency", "chf"} <= row.keys()


def test_a_day_lists_its_movements_in_statement_order(client):
    first = _rows(client, "preset=all&sort=date&dir_sort=asc&per=20")["rows"][0]
    day = api(client, f"/api/day/{first['date']}")
    assert [r["seq"] for r in day["rows"]] == sorted(r["seq"] for r in day["rows"])
    assert day["spending"] >= 0


def test_the_filter_in_brief_and_the_new_filters(client):
    """The summary adds up the rows the filter keeps; the amount bounds, the
    corrected and the to-classify filters narrow the same rows the export
    and the bulk edit see."""
    data = api(client, "/api/transactions?preset=all&q=coop")
    s = data["summary"]
    assert s["count"] == data["total"]
    assert abs(sum(p["amount"] for p in s["parts"]) - s["out"]) < 0.05
    assert abs(sum(p["out"] for p in s["series"]) - s["out"]) < 0.05
    big = api(client, "/api/transactions?preset=all&amin=100&per=500")
    assert big["rows"] and all(abs(r["chf"]) >= 100 for r in big["rows"])
    small = api(client, "/api/transactions?preset=all&amax=5&per=500")
    assert all(abs(r["chf"]) <= 5 for r in small["rows"])
    todo = api(client, "/api/transactions?preset=all&todo=1&per=500")
    assert todo["rows"] and {r["category"] for r in todo["rows"]} <= {"Non catégorisé", "Twint non identifié"}
    assert api(client, "/api/transactions?preset=all&fix=1")["total"] == 0
    assert api(client, "/api/transactions?preset=all&amin=abc")["total"] == api(client, "/api/transactions?preset=all")["total"]
