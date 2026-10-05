"""Shared navigation and accessibility: labels, focus, the nav, the pager,
the table of contents, links that carry the window."""

from __future__ import annotations

import datetime as dt
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from webhelpers import nav_block, text

# --- form labelling ---------------------------------------------------------

class _Controls(HTMLParser):
    """Every visible form control on a page, and how it is labelled.

    Written against the raw markup rather than a DOM library so the check has
    no dependency of its own -- and because what matters is exactly what the
    template emits.
    """

    SKIP = {"hidden", "submit", "button", "reset", "image"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.controls: list[dict] = []
        self.label_targets: set[str] = set()
        self.label_depth = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "label":
            self.label_depth += 1
            if attributes.get("for"):
                self.label_targets.add(attributes["for"])
        elif tag in ("input", "select", "textarea"):
            if attributes.get("type", "text").lower() in self.SKIP:
                return
            self.controls.append({
                "tag": tag,
                "name": attributes.get("name", "?"),
                "id": attributes.get("id"),
                "aria": attributes.get("aria-label"),
                "wrapped": self.label_depth > 0,
            })

    def handle_endtag(self, tag):
        if tag == "label" and self.label_depth:
            self.label_depth -= 1


#: Controls a visible or hidden <label> cannot reasonably serve: one per table
#: row, where the label would have to repeat the row it sits in. `aria-label`
#: is the accepted pattern there, and these are the only two that use it.
ROW_SCOPED = {"keys", "scope_all"}


@pytest.mark.parametrize("path", [
    "/?preset=all",
    "/transactions?preset=all",
    "/previsions",
    "/rules",
])
def test_every_form_control_has_a_label(client, path):
    """A placeholder is not a label: it disappears the moment you type, it is
    not translated, and it leaves a screen reader announcing "edit, blank".
    Every control must be reachable by a real <label> -- visible where there is
    room, `sr-only` where a filter row has none."""
    parser = _Controls()
    parser.feed(text(client.get(path)))

    unlabelled = [
        c for c in parser.controls
        if not c["wrapped"]
        and (c["id"] or "") not in parser.label_targets
        and not (c["name"] in ROW_SCOPED and c["aria"])
    ]
    assert not unlabelled, f"{path}: {unlabelled}"


def test_a_skip_link_leads_to_the_content(client):
    """Keyboard users tab past the header and the control bar on every page.
    The skip link must be the first focusable element, and every <main> must
    be its target -- a dead anchor would be worse than no link at all."""
    root = Path(__file__).resolve().parents[1] / "src" / "pms" / "web" / "templates"
    for p in sorted(root.rglob("*.j2")):
        s = p.read_text(encoding="utf-8")
        # Ignore Jinja comments: they mention <main> without emitting one.
        s = re.sub(r"{#.*?#}", "", s, flags=re.S)
        if "<main" not in s:
            continue
        m = re.search(r'<main[^>]*>', s)
        assert 'id="main"' in m.group(0), f"{p.name}: <main> without id=main"
    body = text(client.get("/?preset=all"))
    assert re.search(r'<a class="skip-link" href="#main">Aller au contenu</a>', body)
    css = text(client.get("/static/app.css"))
    assert ".skip-link:focus-visible" in css


def test_no_template_carries_a_static_style():
    """W2: a style attribute that is not computed geometry (a width in %, a
    slot colour) is now a mistake. Scanned on the raw templates, not the
    rendered page: the rendered page only reaches a subset of windows, and
    every fragment path has to hold."""
    root = Path(__file__).resolve().parents[1] / "src" / "pms" / "web" / "templates"
    offenders = []
    for p in sorted(root.rglob("*.j2")):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for m in re.finditer(r'style="([^"]*)"', line):
                if "{{" not in m.group(1) and "{%" not in m.group(1):
                    offenders.append(f"{p.name}:{i}: {m.group(1)[:60]}")
    assert not offenders, offenders


def test_no_control_leans_on_aria_label_alone(client):
    """`aria-label` was the old fix here. It serves a screen reader and nobody
    else -- browser translation skips it, and a sighted user who has typed into
    the field has nothing left on screen naming it. The row-scoped checkboxes
    are the documented exception."""
    parser = _Controls()
    for path in ("/?preset=all", "/transactions?preset=all", "/previsions", "/rules"):
        parser.feed(text(client.get(path)))

    leaning = [c for c in parser.controls
               if c["aria"] and not c["wrapped"]
               and (c["id"] or "") not in parser.label_targets
               and c["name"] not in ROW_SCOPED]
    assert not leaning, leaning


def test_explanatory_prose_is_capped_to_a_readable_measure(client):
    """These notes carry the app's reasoning and ran the full width of the
    card -- 158 characters a line, measured at 1280px. The cap is in `ch` so
    it follows the font size."""
    css = text(client.get("/static/app.css"))
    rule = re.search(r'\.card > \.muted,\s*\.callout \{ max-width: (\d+)ch', css)
    assert rule, "the prose measure cap is gone"
    assert 45 <= int(rule.group(1)) <= 78, rule.group(1)


def test_layout_and_type_come_from_the_scale(client):
    """Twenty-one spacing values and thirteen type sizes, several a half-pixel
    apart, because there was no scale to reach for. A literal px on a layout
    property means someone invented a step again.

    Values of 3px and under are exempt: those are mark geometry -- the surface
    gap between stacked segments, the space between colour swatches -- and are
    proportional to the mark, not to the page."""
    css = text(client.get("/static/app.css"))
    body = css.split("--radius: 14px;", 1)[1]

    sizes = set(re.findall(r'font-size:\s*([\d.]+)px', body))
    weights = set(re.findall(r'font-weight:\s*(\d+)', body))
    spacing = {float(v) for v in
               re.findall(r'(?:padding|margin|gap):\s*([\d.]+)px', body)}

    assert not sizes, f"font-size off the scale: {sizes}"
    assert not weights, f"font-weight off the scale: {weights}"
    assert not {v for v in spacing if v > 3}, f"spacing off the scale: {spacing}"


def test_keyboard_focus_is_visible_on_buttons(client):
    """Buttons and icon buttons are most of what there is to click, and they
    had no focus rule at all -- only the browser default, which all but
    disappears on a custom background."""
    css = text(client.get("/static/app.css"))
    for selector in (".btn:focus-visible", ".icon-btn:focus-visible"):
        assert selector in css, selector


def test_data_nav_only_points_at_fragment_capable_pages(client):
    """`data-nav` swaps <main> with a fragment. Pointing it at a page that
    does not serve one lands there stripped of its chrome -- including the
    #txPanel that sorting and paging replace, which silently breaks both.
    Every page that carries a data-nav link must satisfy it."""
    for url in ("/?preset=all", "/previsions", "/reclasser", "/analyse"):
        body = text(client.get(url))
        links = re.findall(r'<a[^>]*\bdata-nav\b[^>]*>', body)
        for tag in links:
            href = re.search(r'href="([^"]*)"', tag)
            if not href:
                continue
            path = href.group(1).split("?")[0]
            assert path in ("/", "/previsions", "/analyse"), \
                f"data-nav must stay on fragment-capable pages, got {href.group(1)}"


def test_cross_page_links_reach_a_sortable_panel(client):
    """Clicking a category, a merchant or a bucket must land on a page whose
    table actually sorts."""
    body = text(client.get("/?preset=all"))
    targets = set(re.findall(r'href="(/transactions\?[^"]+)"', body))
    assert targets
    for target in list(targets)[:5]:
        page = text(client.get(target.replace("&amp;", "&")))
        assert 'id="txPanel"' in page, target
        assert "data-tx-sort" in page, target


def test_page_has_a_table_of_contents(client):
    """The right rail mirrors the page: one link per section on screen."""
    body = text(client.get("/?preset=all"))
    assert 'class="toc"' in body
    for anchor in ('#p-balance', '#p-monthly', '#p-custodian', '#txPanel'):
        assert f'href="{anchor}"' in body
    # The rail mirrors the page: no snapshot, no épargne link.
    assert 'href="#p-ibkr"' not in body
    # A short window drops the sections, and their links with them.
    short = text(client.get("/?from=2026-07-01&to=2026-07-10"))
    assert 'href="#p-calendar"' not in short


def test_back_to_top_link(client):
    body = text(client.get("/?preset=all"))
    assert 'id="top"' in body
    assert 'class="totop"' in body
    assert 'href="#top"' in body


def test_period_neighbours_arrows(client):
    """A window that is exactly one calendar unit gets previous/next arrows;
    a window straddling units gets none -- moving "one month" from a window
    that is not a month would be a guess."""
    body = text(client.get("/?from=2025-05-01&to=2025-05-31"))
    assert 'class="nav-arrow' in body  # prev / next / off variants
    assert "2025-04-01" in body and "2025-06-01" in body
    assert "Période précédente" in body

    # A window that is no calendar unit steps by its own length -- the same
    # window, one length earlier -- rather than having no arrows at all.
    straddling = text(client.get("/?from=2025-05-10&to=2025-06-10"))
    assert "from=2025-04-08" in straddling and "to=2025-05-09" in straddling
    assert "from=2025-06-11" in straddling and "to=2025-07-12" in straddling


def test_the_month_in_progress_steps_back_to_the_whole_previous_month(client):
    """The default view runs from the 1st to the last movement; its left
    arrow is last month, whole, and there is nothing to its right yet."""
    body = text(client.get("/"))
    assert "Juillet 2026" in body
    assert "from=2026-06-01" in body and "to=2026-06-30" in body
    assert 'class="nav-arrow off">›' in body


def _link_href(block: str, label: str) -> str:
    """The href of the first link in `block` whose visible text is `label`."""
    for href, inner in re.findall(r'<a href="([^"]*)"[^>]*>(.*?)</a>', block, re.S):
        if re.sub(r"<[^>]+>", "", inner).strip() == label:
            return href.replace("&amp;", "&")
    raise AssertionError(f"no link named {label!r} in block")


def _query_of(href: str) -> dict:
    return dict(p.split("=", 1) for p in href.split("?", 1)[1].split("&"))


def test_every_page_has_the_shared_nav_with_current_page_marked(client):
    """The five top-level pages share one navigation bar, and exactly one of
    its links says this is the page you are on."""
    expected = {
        "/?preset=all": "Tableau de bord",
        "/analyse": "Analyse",
        "/previsions": "Prévisions",
        "/transactions?preset=all": "Transactions",
        # The corrections page serves at /reclasser (endpoint dashboard.rules).
        "/reclasser": "Corrections",
    }
    for path, current in expected.items():
        nav = nav_block(text(client.get(path)))
        assert len(re.findall(r'aria-current="page"', nav)) == 1, path
        marked = re.search(r'<a[^>]*aria-current="page"[^>]*>(.*?)</a>', nav, re.S)
        assert marked is not None, path
        label = re.sub(r"<[^>]+>", "", marked.group(1)).strip()
        assert label == current, path


def test_page_links_carry_the_window_across_pages(client):
    """Leaving the dashboard for another page and coming back must not reset
    the window: the round trip rides on the query string alone."""
    query = "from=2025-05-01&to=2025-05-31"
    nav = nav_block(text(client.get(f"/?{query}")))
    outbound = _link_href(nav, "Prévisions")
    assert _query_of(outbound) == {"from": "2025-05-01", "to": "2025-05-31"}

    nav = nav_block(text(client.get(outbound)))
    home = _link_href(nav, "Tableau de bord")
    assert _query_of(home) == {"from": "2025-05-01", "to": "2025-05-31"}


def test_breadcrumb_current_step_is_marked(client):
    """The trail's last step is where you are: it carries the page marker,
    and the separators are decoration a screen reader must skip."""
    body = text(client.get("/?from=2025-05-01&to=2025-05-31"))
    start = body.index('<nav class="crumbs"')
    crumbs = body[start:body.index("</nav>", start)]
    assert '<span class="here" aria-current="page">Mai 2025</span>' in crumbs
    separators = re.findall(r"<em[^>]*>", crumbs)
    assert separators
    assert all('aria-hidden="true"' in em for em in separators)


def test_out_of_range_page_redirects_to_page_one(client):
    """A shared URL with ?page=99 for a filter that no longer matches it must
    not render the clamped page behind a lying address bar."""
    base = "from=2025-05-01&to=2025-05-31&page=99"
    response = client.get(f"/transactions?{base}")
    assert response.status_code == 302
    assert "page=1" in response.headers["Location"]

    fragment = client.get(f"/transactions?{base}&fragment=1")
    assert fragment.status_code == 302
    assert "page=1" in fragment.headers["Location"]
    assert "fragment=1" in fragment.headers["Location"]


def _pager_block(body: str) -> str:
    start = body.index('<nav class="pager"')
    return body[start:body.index("</nav>", start)]


def test_pager_never_navigates_itself(client):
    """The pager never links to the page it is on: no Précédent on the first
    page, no Suivant on the last, and the counter says where you are."""
    first = text(client.get("/transactions?preset=all"))
    assert '<nav class="pager" aria-label="Pagination">' in first
    pager = _pager_block(first)
    counter = re.search(r'aria-current="page">Page 1 sur (\d+)<', pager)
    assert counter, "the counter must announce the current page"
    pages = int(counter.group(1))
    assert pages > 1
    assert not re.search(r"<a[^>]*>Précédent</a>", pager)

    last = text(client.get(f"/transactions?preset=all&page={pages}"))
    pager = _pager_block(last)
    assert f'aria-current="page">Page {pages} sur {pages}<' in pager
    assert not re.search(r"<a[^>]*>Suivant</a>", pager)


def test_filter_chips_remove_one_filter_at_a_time(client):
    """Each active filter gets a chip that drops exactly that parameter; the
    "effacer" chip drops them all and keeps only the window."""
    body = text(client.get(
        "/transactions?preset=all&q=Coop&category=Alimentation"))
    start = body.index('<div class="filter-chips">')
    chips = body[start:body.index("</div>", start)]

    def chip_query(prefix: str) -> dict:
        for href, label in re.findall(
                r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', chips, re.S):
            if re.sub(r"<[^>]+>", "", label).strip().startswith(prefix):
                return _query_of(href.replace("&amp;", "&"))
        raise AssertionError(f"no chip named {prefix!r}")

    search = chip_query("Recherche : Coop")
    assert "q" not in search and search["category"] == "Alimentation"

    category = chip_query("Catégorie : Alimentation")
    assert "category" not in category and category["q"] == "Coop"

    cleared = chip_query("Effacer les filtres")
    assert "q" not in cleared and "category" not in cleared
    assert "from" in cleared and "to" in cleared


def test_every_drill_link_names_its_destination(client):
    """A chart link whose destination is not announced is a promise a screen
    reader user cannot take: every drill column and every calendar cell says
    where it goes in its aria-label."""
    body = text(client.get("/?from=2025-01-01&to=2025-12-31&grain=month"))
    columns = re.findall(r'<a[^>]*>\s*<g class="col-group', body)
    assert columns
    for tag in columns:
        label = re.search(r'aria-label="([^"]+)"', tag).group(1)
        assert "zoomer" in label or "journée" in label, label

    body = text(client.get("/?preset=all"))
    cells = re.findall(r'<a[^>]*>\s*<rect class="cell', body)
    assert cells, "the calendar must offer day links"
    for tag in cells:
        label = re.search(r'aria-label="([^"]+)"', tag).group(1)
        assert re.match(r"\d{2}\.\d{2}\.\d{4}", label), label


def test_empty_window_offers_a_way_back(client, statement, bounds):
    """A window with no movements at all must say so -- and offer a way back
    to a window that has some."""
    days = {t.date for t in statement.transactions}
    low, high = bounds
    empty = next((low + dt.timedelta(days=i)
                  for i in range((high - low).days + 1)
                  if low + dt.timedelta(days=i) not in days), None)
    assert empty is not None, "the fixture statement has no empty day"
    body = text(client.get(
        f"/?from={empty.isoformat()}&to={empty.isoformat()}&grain=day"))
    assert "Aucun mouvement sur cette période." in body
    assert 'href="/?preset=12m"' in body
    assert "Revenir aux 12 derniers mois" in body


def test_404_page_offers_a_way_back(client):
    """A bad URL must answer with a page that says what happened and links
    back -- not with Flask's bare error."""
    response = client.get("/day/2025-13-40")
    assert response.status_code == 404
    body = text(response)
    assert "Page introuvable" in body
    assert 'href="/"' in body
    assert "Tableau de bord" in body


def test_previsions_title_is_dated(client):
    """The forecast is a snapshot: the title must name the day it is as of."""
    title = re.search(r"<title>(.*?)</title>",
                      text(client.get("/previsions")), re.S).group(1)
    assert re.search(r"Prévisions de trésorerie · au \d{2}\.\d{2}\.\d{4}", title)


def test_transactions_title_carries_the_page(client):
    """The table is paged, so the title says which page is open -- a bookmark
    on page 4 must not come back as page 1 with no way to tell."""
    title = re.search(r"<title>(.*?)</title>",
                      text(client.get("/transactions?preset=all")), re.S).group(1)
    assert " — page 1 sur " in title
    assert re.search(r"page 1 sur \d+", title)


def test_custom_window_shows_a_custom_badge(client):
    """A window that matches no preset is marked as hand-typed instead of
    leaving every segment looking inactive -- and a preset window gets no
    badge at all."""
    body = text(client.get("/?from=2025-05-15&to=2025-05-20"))
    assert "Personnalisé" in body
    assert "Personnalisé" not in text(client.get("/?preset=12m"))


def _heading_near(body: str, position: int) -> str | None:
    window = body[max(position - 400, 0):position + 400]
    candidates = [
        (abs(m.start() - 400), re.sub(r"<[^>]+>", "", m.group(1)).strip())
        for m in re.finditer(r"<h[23][^>]*>(.*?)</h[23]>", window, re.S)
    ]
    return min(candidates)[1] if candidates else None


def test_toc_labels_mirror_the_heading_text(client):
    """Each Sommaire link names the heading it lands on: a label that drifts
    from its heading would announce one thing and deliver another. Every page
    with a rail must satisfy it -- the dashboard, the previsions, the rules."""
    for url in ("/?preset=all", "/previsions", "/reclasser"):
        body = text(client.get(url))
        start = body.index('<nav class="toc"')
        toc = body[start:body.index("</nav>", start)]
        links = re.findall(r'<a href="#([^"]+)">([^<]+)</a>', toc)
        assert links, url

        for target, label in links:
            heading = _heading_near(body, body.index(f'id="{target}"'))
            assert heading, f"no heading near #{target} on {url}"
            assert heading.startswith(label), (url, target, label, heading)


def test_the_account_holder_name_is_gone_from_the_header_and_footer(
        client, statement):
    """The holder's name crowded the header for nothing -- it is gone from the
    header and the dashboard footer alike. The name comes from the session
    fixture, never hard-coded. (The name can still appear as a counterparty in
    the data itself -- a payment between own accounts -- which is not this.)"""
    body = text(client.get("/"))
    header = re.search(r"<header.*?</header>", body, re.S).group(0)
    footer = re.search(r"<footer.*?</footer>", body, re.S).group(0)
    assert statement.holder not in header
    assert statement.holder not in footer
    assert "Relevé Swissquote" in header


# --- the shortcuts help -------------------------------------------------------

def test_every_page_carries_the_shortcuts_help_behind_a_hidden_button(client):
    """Every gesture it lists is JavaScript, so its button ships hidden and
    app.js reveals it: without JavaScript there is nothing to open."""
    for url in ("/?preset=all", "/transactions", "/previsions", "/analyse", "/reclasser"):
        body = text(client.get(url))
        assert '<dialog class="shortcuts" id="shortcuts"' in body, url
        button = re.search(r'<button[^>]*id="helpBtn"[^>]*>', body).group(0)
        assert " hidden" in button, url


# --- the swap's second request ---------------------------------------------------

def test_the_controls_fragment_is_the_page_s_own_controls(client):
    """The swap refreshes the period bar from this fragment instead of a second
    full dashboard; it must be the very markup the full page carries."""
    query = "from=2025-05-01&to=2025-05-31&stack=bucket"
    full = text(client.get(f"/?{query}"))
    fragment = text(client.get(f"/?{query}&fragment=controls"))
    title, controls = fragment.split("</title>", 1)
    assert "Mai 2025" in title
    assert 'id="controls"' in controls and "p-balance" not in controls
    assert controls.strip() in full
