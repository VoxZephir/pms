"""The transactions table: filters, paging, server-side sorting, export."""

from __future__ import annotations

import re

from webhelpers import row_count, text


def test_transactions_filter_by_category(client):
    body = text(client.get("/transactions?preset=all&category=Alimentation&fragment=1"))
    assert "Alimentation" in body
    assert "Santé &amp; assurance" not in body


def test_transactions_search_narrows_the_result(client):
    wide = text(client.get("/transactions?preset=all&fragment=1"))
    narrow = text(client.get("/transactions?preset=all&q=coop&fragment=1"))
    assert row_count(narrow) < row_count(wide)


def test_paging_does_not_lose_or_repeat_rows(client):
    first = text(client.get("/transactions?preset=all&page=1&fragment=1"))
    second = text(client.get("/transactions?preset=all&page=2&fragment=1"))
    assert first != second
    assert row_count(first) == row_count(second)  # the total is the same on both pages


# --- sorting ----------------------------------------------------------------

def _labels(body: str) -> list[str]:
    return re.findall(r'<div class="t-lab">([^<]*)</div>', body)


def test_every_column_sorts_both_ways(client):
    for column in ("date", "label", "category", "amount", "chf"):
        down = _labels(text(client.get(
            f"/transactions?preset=all&sort={column}&dir_sort=desc&fragment=1")))
        up = _labels(text(client.get(
            f"/transactions?preset=all&sort={column}&dir_sort=asc&fragment=1")))
        assert down and up
        assert down != up, f"{column} sorts the same in both directions"


def test_sorting_is_server_side_across_pages(client):
    """A client-side sort would only reorder the rows already on screen, which
    looks right and is wrong."""
    page1 = text(client.get(
        "/transactions?preset=all&sort=chf&dir_sort=desc&page=1&fragment=1"))
    page2 = text(client.get(
        "/transactions?preset=all&sort=chf&dir_sort=desc&page=2&fragment=1"))
    first = _amounts(page1)
    second = _amounts(page2)
    assert first and second
    assert min(first) >= max(second), "page 2 must continue page 1's ordering"


def _amounts(body: str) -> list[float]:
    """The "En CHF" column only -- the "Montant" cell carries a currency suffix,
    and the two differ on foreign-currency rows."""
    out = []
    for cell in re.findall(r'<td class="r num">([-\d’.]+)</td>\s*</tr>', body):
        try:
            out.append(abs(float(cell.replace("’", ""))))
        except ValueError:
            pass
    return out


def test_amount_sorts_by_magnitude_not_sign(client):
    """Sorting a statement by signed value buries every large debit."""
    body = text(client.get(
        "/transactions?preset=all&sort=chf&dir_sort=desc&fragment=1"))
    amounts = _amounts(body)
    assert amounts
    assert amounts == sorted(amounts, reverse=True)


def test_sort_survives_filtering_and_paging(client):
    body = text(client.get(
        "/transactions?preset=all&sort=label&dir_sort=asc&category=Alimentation&fragment=1"))
    assert 'name="sort" value="label"' in body
    assert 'sort=label' in body and 'dir_sort=asc' in body


def test_sort_headers_are_real_links(client):
    """Sorting has to work with JavaScript off."""
    body = text(client.get("/transactions?preset=all&fragment=1"))
    assert body.count("data-tx-sort") == 5
    assert 'aria-sort=' in body


def test_sorting_works_on_the_standalone_transactions_page(client):
    """The page reached by clicking a category needs the panel the sort swaps,
    or the click is cancelled and nothing happens."""
    body = text(client.get("/transactions?preset=all&category=Alimentation"))
    assert 'id="txPanel"' in body
    assert "data-tx-sort" in body


def test_the_other_tables_are_sortable(client):
    """The day's movements and the dashboard's detail tables sort client-side;
    they are not paged, so there is nothing off-screen to get wrong."""
    for url in ("/day/2025-05-15", "/?preset=all"):
        assert "sortable-table" in text(client.get(url)), url


# --- export ------------------------------------------------------------------

def test_export_carries_the_window_in_the_filename(client):
    response = client.get("/export.csv?from=2025-05-01&to=2025-05-31")
    assert response.status_code == 200
    assert 'filename="pms-2025-05-01_2025-05-31.csv"' in \
        response.headers["Content-Disposition"]


def test_export_holds_exactly_the_rows_the_table_showed(client):
    """The file is the filter, not the page: all of it, not the first sixty."""
    import csv as _csv
    import io as _io

    query = "from=2025-01-01&to=2025-12-31&category=Alimentation"
    listing = text(client.get(f"/transactions?{query}&fragment=1"))
    payload = client.get(f"/export.csv?{query}").get_data()
    table = list(_csv.reader(_io.StringIO(payload.decode("utf-8-sig"), newline="")))

    assert len(table) - 1 == row_count(listing) > 60
    assert {row[2] for row in table[1:]} == {"Alimentation"}


def test_export_follows_the_sort_that_was_on_screen(client):
    import csv as _csv
    import io as _io

    query = "from=2025-01-01&to=2025-12-31&sort=amount&dir_sort=desc"
    payload = client.get(f"/export.csv?{query}").get_data()
    table = list(_csv.reader(_io.StringIO(payload.decode("utf-8-sig"), newline="")))
    amounts = [abs(float(row[5])) for row in table[1:]]
    assert amounts == sorted(amounts, reverse=True)


def test_the_xlsx_route_serves_a_real_workbook(client):
    import io as _io
    import zipfile as _zipfile

    response = client.get("/export.xlsx?from=2025-05-01&to=2025-05-31")
    assert response.status_code == 200
    assert "spreadsheetml" in response.headers["Content-Type"]
    archive = _zipfile.ZipFile(_io.BytesIO(response.get_data()))
    assert "xl/worksheets/sheet1.xml" in archive.namelist()


def test_an_unknown_export_format_is_a_404(client):
    assert client.get("/export.pdf?preset=all").status_code == 404


def test_the_transactions_panel_offers_the_export(client):
    body = text(client.get("/transactions?preset=all&fragment=1"))
    assert "/export.csv?" in body and "/export.xlsx?" in body
    # It downloads a file; swapping <main> with a spreadsheet would be a bug.
    for href in re.findall(r'href="(/export\.[^"]+)"[^>]*>', body):
        anchor = re.search(r'<a[^>]*href="' + re.escape(href) + r'"[^>]*>', body)
        assert "data-nav" not in anchor.group(0)


# --- a shorter table on the dashboard ---------------------------------------------

def _data_rows(body: str) -> int:
    return len(re.findall(r"<tr draggable", body))


def test_the_dashboard_table_shows_twenty_rows_and_pages_on_at_twenty(client):
    """It is the last of fifteen panels; at 60 rows it was a third of the page.
    Its pager must carry the size, or page 2 would restart at row 61."""
    body = text(client.get("/?preset=all"))
    panel = body[body.index('id="txPanel"'):]
    assert _data_rows(panel) == 20
    following = re.search(r'href="(/transactions\?[^"]*page=2[^"]*)"', panel).group(1)
    assert "per=20" in following
    page_two = text(client.get(following.replace("&amp;", "&") + "&fragment=1"))
    assert _data_rows(page_two) == 20
    assert re.search(r"21–40\s+sur", page_two)


def test_the_transactions_page_keeps_sixty_rows(client):
    body = text(client.get("/transactions?preset=all&fragment=1"))
    assert _data_rows(body) == 60
    assert "per=" not in body


def test_an_unknown_page_size_falls_back(client):
    body = text(client.get("/transactions?preset=all&per=33&fragment=1"))
    assert _data_rows(body) == 60
