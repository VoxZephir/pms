"""/analyse: the monthly profile, its year modes, the category drill, export."""

from __future__ import annotations

import re

from webhelpers import chart_data, nav_block, text


def test_the_analysis_page_renders(client):
    """/analyse is the historical half of the same arithmetic, on its own
    page: the monthly profile and the per-category stats."""
    body = text(client.get("/analyse"))
    assert "Analyse historique" in body
    assert 'id="p-profile"' in body
    assert 'id="p-categories"' in body
    for probe in ("Médiane brute", "Médiane mensuelle", "Mois de pointe",
                  "Saisonnier"):
        assert probe in body
    # Au moins une catégorie détectée saisonnière est annoncée comme telle.
    start = body.index('id="p-categories"')
    categories = body[start:body.index("</section>", start)]
    assert "chaque " in categories and 'class="chip"' in categories
    # La nav marque la page courante.
    nav = nav_block(body)
    marked = re.search(r'<a[^>]*aria-current="page"[^>]*>(.*?)</a>', nav, re.S)
    assert marked is not None
    assert re.sub(r"<[^>]+>", "", marked.group(1)).strip() == "Analyse"


def test_analysis_fragment_and_full_page_agree(client):
    """The nav swaps /analyse in place like the dashboard and the previsions,
    so the fragment must be exactly the full page's main content."""
    full = text(client.get("/analyse"))
    fragment = text(client.get("/analyse?fragment=1"))
    assert fragment.strip() in full


def test_analysis_page_has_no_empty_coordinates(client):
    for url in ("/analyse", "/analyse?cat=Impôts", "/analyse?year=2025"):
        body = text(client.get(url))
        assert not re.search(
            r'\b(x|y|cx|cy|x1|y1|x2|y2|width|height)=""', body), url


def test_the_monthly_chart_ships_a_hover_payload(client):
    """The crosshair rides the same chartData mechanism as the projection:
    one point per bar, at its top, for the full and the stripped medians."""
    data = chart_data(text(client.get("/analyse")))
    monthly = data["monthly"]
    assert monthly["geom"]["plotW"] > 0
    assert len(monthly["series"]) == 2
    names = {s["name"] for s in monthly["series"]}
    assert names == {"Médiane brute", "Médiane hors saisonnier"}
    for s in monthly["series"]:
        assert s["pts"] and len(s["pts"][0]) == 3
    assert len(monthly["labels"]) == len(monthly["series"][0]["pts"])
    # Le même payload sert le panneau des prévisions, qui partage le SVG.
    previsions = chart_data(text(client.get("/previsions")))
    assert previsions["monthly"]["geom"] == monthly["geom"]
    # Le lien du chip saisonnier est un data-nav vers une page fragment-capable.
    body = text(client.get("/analyse"))
    assert 'href="/previsions" data-nav' in body


def test_analysis_year_modes_switch_the_profile(client):
    """?year= picks one observed year instead of the median, so a rise from
    one year to the next shows raw -- and the pick is view state, links in
    the seg, like the stack or the wealth view."""
    body = text(client.get("/analyse?year=2025"))
    assert 'id="p-profile"' in body
    # Le markup met un saut de ligne entre href et data-nav.
    assert re.search(r'href="/analyse\?year=2024"\s+data-nav', body)
    assert re.search(r'href="/analyse"\s+data-nav', body)  # Médiane drops its key
    seg = body[body.index('aria-label="Année du profil"'):]
    marked = re.search(r'<a[^>]*aria-current="page"[^>]*>([^<]+)</a>', seg)
    assert marked and marked.group(1) == "2025"
    # Une année inconnue retombe sur la médiane, jamais écho brut.
    fallback = text(client.get("/analyse?year=9999"))
    seg = fallback[fallback.index('aria-label="Année du profil"'):]
    marked = re.search(r'<a[^>]*aria-current="page"[^>]*>([^<]+)</a>', seg)
    assert marked and marked.group(1) == "Médiane"
    # Une chaîne de milliers de chiffres ferait exploser int() (limite de
    # 4300 digits de Python) avant le repli : la page doit répondre 200.
    giant = text(client.get("/analyse?year=" + "9" * 5000))
    assert 'id="p-profile"' in giant
    assert "Médiane" in giant


def test_analysis_export_links_carry_the_year(client):
    """The export follows the year on screen -- the file holds what the
    page showed, so the buttons must carry the pick."""
    body = text(client.get("/analyse?year=2025"))
    assert 'href="/analyse/export.csv?year=2025"' in body
    assert 'href="/analyse/export.xlsx?year=2025"' in body
    plain = text(client.get("/analyse"))
    assert 'href="/analyse/export.csv"' in plain
    assert "?year=" not in plain[plain.index("Exporter l'analyse"):plain.index("</span>", plain.index("Exporter l'analyse"))]


def test_analysis_drills_into_a_category(client):
    """Clicking a category replaces the profile with its real monthly series,
    and the way back drops only the ?cat= key."""
    body = text(client.get("/analyse",
                           query_string={"cat": "Impôts & administration"}))
    assert 'id="categoryChart"' in body
    assert "Impôts & administration — mois par mois" in body
    assert re.search(r'href="/analyse"\s+data-nav', body)  # le retour
    # La ligne ouverte cesse d'être un lien, les autres le sont.
    start = body.index('id="p-categories"')
    section = body[start:body.index("</section>", start)]
    assert re.search(r"<tr class=\"hl-row\">", section)
    assert 'href="/analyse?cat=' in section


def test_the_drill_obeys_the_year_in_the_url(client):
    """?year=2025&cat=X must show 2025's months only, like the profile --
    an URL that declares a year must not silently mix three."""
    data = chart_data(text(client.get(
        "/analyse", query_string={"year": "2025",
                                  "cat": "Impôts & administration"})))
    labels = data["category"]["labels"]
    assert labels, "le drill doit rendre au moins un mois"
    assert all(label.endswith(" 25") for label in labels)
    # Le retour au mois ordinaire préserve l'année.
    body = text(client.get("/analyse", query_string={"year": "2025",
                                                     "cat": "Alimentation"}))
    assert 'href="/analyse?year=2025" data-nav' in body or \
        re.search(r'href="/analyse\?year=2025"\s+data-nav', body)


def test_analysis_export_csv_holds_the_tables(client):
    response = client.get("/analyse/export.csv")
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/csv")
    body = response.get_data(as_text=True)
    assert body.startswith("\ufeff")
    for probe in ("Médiane brute", "Médiane hors saisonnier",
                  "Tendance", "Saisonnier"):
        assert probe in body


def test_analysis_export_xlsx_has_two_sheets(client):
    import io
    import zipfile

    response = client.get("/analyse/export.xlsx")
    assert response.status_code == 200
    assert "spreadsheetml" in response.headers["Content-Type"]
    archive = zipfile.ZipFile(io.BytesIO(response.data))
    names = archive.namelist()
    assert "xl/worksheets/sheet1.xml" in names
    assert "xl/worksheets/sheet2.xml" in names
    workbook = archive.read("xl/workbook.xml").decode("utf-8")
    assert "Profil mensuel" in workbook
    assert "Par catégorie" in workbook
    assert workbook.count("_xlnm._FilterDatabase") == 2


def test_analysis_export_unknown_format_is_a_404(client):
    assert client.get("/analyse/export.txt").status_code == 404
