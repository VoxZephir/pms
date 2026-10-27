"""The React app in a real browser.

The rest of the suite reads the JSON the server sends; nothing there runs
the code that draws it. These drive the built app (static/spa/) the way a
reader does: on a laptop, and on a phone-sized touch screen.

Playwright steers the Edge or Chrome already installed, so there is no
browser to download. Skipped when Playwright, such a browser, or the build
is missing.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
from urllib.parse import parse_qs, urlsplit

import pytest
from webhelpers import savings_snapshots

from pms.web.api import SPA

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect

PAGES = ["/", "/?preset=all", "/transactions?preset=all", "/epargne", "/analyse",
         "/previsions", "/corrections", "/corrections/tri", "/importer", "/jour/2025-05-15",
         "/a-venir", "/impots", "/projets", "/bilan", "/aide"]


@pytest.fixture(scope="module")
def server(ledger_file, tmp_path_factory):
    """Its own copy of the ledger: the tests here write corrections."""
    if not (SPA / "index.html").exists():
        pytest.skip("front end not built")
    from werkzeug.serving import make_server

    from pms.web import create_app
    workdir = tmp_path_factory.mktemp("browser")
    ledger = workdir / "ledger.json"
    shutil.copy(ledger_file, ledger)
    app = create_app(ledger)
    # The savings pockets, so /epargne draws its panels rather than its
    # empty state.
    savings_snapshots(app.test_client())
    httpd = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as playwright:
        launched = None
        # A Chromium that is not Edge or Chrome (a container's), by path.
        if os.environ.get("PMS_BROWSER"):
            launched = playwright.chromium.launch(executable_path=os.environ["PMS_BROWSER"])
        for channel in () if launched else ("msedge", "chrome"):
            try:
                launched = playwright.chromium.launch(channel=channel)
                break
            except sync_api.Error:
                continue
        if launched is None:
            pytest.skip("no installed Edge or Chrome for Playwright to drive")
        yield launched
        launched.close()


def _context(browser, server, phone: bool = False):
    options = ({"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
               if phone else {"viewport": {"width": 1400, "height": 1000}})
    context = browser.new_context(base_url=server, **options)
    context.set_default_timeout(8000)
    return context


@pytest.fixture
def page(browser, server):
    context = _context(browser, server)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    yield page
    context.close()
    assert not errors, f"uncaught JavaScript errors: {errors}"


@pytest.fixture
def phone(browser, server):
    context = _context(browser, server, phone=True)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    yield page
    context.close()
    assert not errors, f"uncaught JavaScript errors: {errors}"


def _query(page) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(page.url).query).items()}


def _ready(page):
    page.wait_for_load_state("networkidle")
    expect(page.locator("main h1").first).to_be_visible()


def _timeline(page):
    chart = page.get_by_role("img", name=re.compile("^Dépenses par période"))
    chart.scroll_into_view_if_needed()
    return chart


# --- every page -----------------------------------------------------------------

@pytest.mark.parametrize("url", PAGES)
def test_no_page_throws_and_every_control_has_a_name(page, url):
    """The fixture fails the test on any uncaught error. And a placeholder is
    not a label: it disappears the moment you type, and leaves a screen
    reader announcing "edit, blank". One visit per page for both."""
    page.goto(url)
    _ready(page)
    nameless = page.evaluate("""() => [...document.querySelectorAll(
        'input:not([type=hidden]), select, textarea, button')]
      .filter(el => el.offsetParent !== null)
      .filter(el => {
        if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return false;
        if (el.labels && el.labels.length) return false;
        if (el.tagName === 'BUTTON' && el.textContent.trim()) return false;
        return true;
      }).map(el => el.outerHTML.slice(0, 120))""")
    assert not nameless, nameless


@pytest.mark.parametrize("url", PAGES)
def test_no_page_scrolls_sideways_on_a_phone(phone, url):
    """Wide content scrolls in its own box; the page itself never does."""
    phone.goto(url)
    _ready(phone)
    width = phone.evaluate("document.documentElement.scrollWidth")
    assert width <= 390, f"{url}: {width}px wide"


def test_the_skip_link_leads_to_the_content(page):
    page.goto("/")
    _ready(page)
    page.keyboard.press("Tab")
    link = page.get_by_role("link", name="Aller au contenu")
    expect(link).to_be_focused()
    assert link.get_attribute("href") == "#main"
    assert page.locator("main#main").count() == 1


def test_the_current_page_is_marked_in_the_navigation(page):
    page.goto("/analyse")
    _ready(page)
    current = page.locator("nav[aria-label='Navigation principale'] [aria-current='page']")
    expect(current).to_have_count(1)
    expect(current).to_contain_text("Analyse")


# --- the window -----------------------------------------------------------------------

def test_the_arrows_step_the_period(page):
    page.goto("/?from=2025-05-01&to=2025-05-31")
    _ready(page)
    page.keyboard.press("ArrowLeft")
    page.wait_for_url(re.compile(r"from=2025-04-01"))
    assert _query(page)["to"] == "2025-04-30"
    expect(page.locator("main h1").first).to_have_text("Avril 2025")


def test_escape_climbs_one_level(page):
    page.goto("/?from=2025-05-01&to=2025-05-31")
    _ready(page)
    page.keyboard.press("Escape")
    page.wait_for_url(re.compile(r"from=2025-01-01"))
    expect(page.locator("main h1").first).to_have_text("Année 2025")


def test_the_picker_offers_presets_and_months(page):
    page.goto("/?from=2025-05-01&to=2025-05-31")
    _ready(page)
    page.get_by_role("button", name="Changer la période").click()
    page.get_by_role("button", name="12 mois").click()
    page.wait_for_url(re.compile(r"preset=12m"))
    expect(page.locator("main h1").first).to_have_text("12 derniers mois")


def test_the_window_rides_along_to_the_next_page(page):
    page.goto("/?from=2025-05-01&to=2025-05-31")
    _ready(page)
    page.get_by_role("navigation", name="Navigation principale").get_by_role(
        "link", name="Transactions").click()
    page.wait_for_url(re.compile(r"/transactions"))
    assert (_query(page)["from"], _query(page)["to"]) == ("2025-05-01", "2025-05-31")


# --- the timeline -----------------------------------------------------------------------

def test_the_tooltip_reads_francs(page):
    """Amounts with the Swiss apostrophe, never a lost decimal point."""
    page.goto("/?from=2025-01-01&to=2025-12-31&grain=month")
    _ready(page)
    box = _timeline(page).bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5, steps=4)
    tip = page.locator("[data-chart-tip]")
    expect(tip).to_be_visible()
    text = tip.inner_text()
    assert re.search(r"\d+(’\d{3})*\.\d{2} CHF", text), text


def test_a_long_tooltip_stays_on_screen(page):
    """The card used to sit inside the panel, which clips: with more rows than
    the chart was tall, its bottom was cut off at the panel's edge."""
    page.set_viewport_size({"width": 1280, "height": 620})
    page.goto("/?from=2025-01-01&to=2025-12-31&grain=month")
    _ready(page)
    chart = _timeline(page)
    page.evaluate("(y) => window.scrollBy(0, y)",
                  chart.bounding_box()["y"] + chart.bounding_box()["height"] - 600)
    box = chart.bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + box["height"] - 4, steps=4)
    tip = page.locator("[data-chart-tip]")
    expect(tip).to_be_visible()
    card = tip.bounding_box()
    assert 0 <= card["y"] and card["y"] + card["height"] <= 620, card


def test_the_contents_jump_to_a_folded_panel_and_back_to_the_top(page):
    page.goto("/?preset=all")
    _ready(page)
    contents = page.get_by_role("navigation", name="Sur cette page")
    link = contents.get_by_role("link", name="Par jour de semaine et par mois")
    link.click()
    panel = page.locator(link.get_attribute("href"))
    expect(panel.locator("[aria-expanded]").first).to_have_attribute("aria-expanded", "true")
    expect(link).to_have_attribute("aria-current", "location")
    top = page.get_by_role("button", name="Haut de page")
    expect(top).to_be_visible()
    top.click()
    page.wait_for_function("window.scrollY === 0")


def test_the_phone_reaches_the_contents_from_the_dock(phone):
    phone.goto("/?preset=all")
    _ready(phone)
    phone.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    phone.get_by_role("button", name="Sections de la page").tap()
    sheet = phone.get_by_role("dialog")
    sheet.get_by_role("link", name="Calendrier des dépenses").tap()
    expect(sheet).to_be_hidden()
    heading = phone.get_by_role("heading", name="Calendrier des dépenses")
    phone.wait_for_function(
        "(el) => { const t = el.getBoundingClientRect().top; return t > 0 && t < 200; }",
        arg=heading.element_handle())


def test_a_column_zooms_into_its_period(page):
    page.goto("/?from=2025-01-01&to=2025-12-31&grain=month")
    _ready(page)
    box = _timeline(page).bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.5)
    page.wait_for_url(lambda url: "from=2025-01-01" not in url)
    query = _query(page)
    assert query["from"][:7] == query["to"][:7], query     # one month


def test_a_sideways_drag_selects_a_range(page):
    page.goto("/?from=2025-01-01&to=2025-12-31&grain=month")
    _ready(page)
    box = _timeline(page).bounding_box()
    y = box["y"] + box["height"] * 0.5
    page.mouse.move(box["x"] + box["width"] * 0.3, y)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.7, y, steps=8)
    page.mouse.up()
    page.wait_for_url(lambda url: "from=2025-01-01" not in url)
    query = _query(page)
    assert "2025-02-01" <= query["from"] < query["to"] <= "2025-11-30", query


def test_the_stack_switch_restacks_by_bucket(page):
    page.goto("/?preset=all")
    _ready(page)
    page.get_by_role("group", name="Découpage des colonnes").get_by_role("link", name="Besoins / envies").click()
    page.wait_for_url(re.compile(r"stack=bucket"))
    expect(page.get_by_text("Ici « Épargne » ne compte que")).to_be_visible()


# --- transactions ----------------------------------------------------------------------

def test_the_search_filters_as_you_type(page):
    page.goto("/transactions?preset=all")
    _ready(page)
    before = page.locator("main h1 + p").first.inner_text()
    page.get_by_placeholder("Bénéficiaire, lieu, montant, date…").fill("coop")
    page.wait_for_url(re.compile(r"q=coop"))
    expect(page.locator("main h1 + p").first).not_to_have_text(before)
    expect(page.get_by_role("cell", name="Coop").first).to_be_visible()


def test_a_header_sorts_the_table(page):
    page.goto("/transactions?preset=all")
    _ready(page)
    page.get_by_role("button", name="En CHF").click()
    page.wait_for_url(re.compile(r"sort=chf"))
    expect(page.locator("th[aria-sort='descending']")).to_contain_text("En CHF")


def test_a_row_is_reclassified_and_the_correction_undone(page):
    page.goto("/transactions?preset=all&q=coop")
    _ready(page)
    page.locator("tbody tr").first.click()
    sheet = page.get_by_role("dialog")
    expect(sheet).to_be_visible()
    sheet.get_by_role("button", name="Shopping", exact=True).click()
    sheet.get_by_role("button", name="Appliquer", exact=True).click()
    toast = page.get_by_text("Reclassé en Shopping")
    expect(toast).to_be_visible()
    expect(page.get_by_role("cell", name="Shopping").first).to_be_visible()
    page.get_by_role("button", name="Annuler").click()
    expect(page.get_by_text("Correction annulée")).to_be_visible()


# --- the shell --------------------------------------------------------------------------

def test_the_command_palette_goes_anywhere(page):
    """A page that matches comes before the search over the ledger; a word
    no page matches searches the transactions."""
    page.goto("/")
    _ready(page)
    page.keyboard.press("Control+k")
    box = page.get_by_placeholder(re.compile("^Page, période"))
    expect(box).to_be_focused()
    box.fill("prévisions")
    page.keyboard.press("Enter")
    page.wait_for_url(re.compile(r"/previsions"))
    page.keyboard.press("Control+k")
    page.get_by_placeholder(re.compile("^Page, période")).fill("coop")
    expect(page.get_by_text("Chercher « coop »")).to_be_visible()
    page.keyboard.press("Enter")
    page.wait_for_url(re.compile(r"/transactions\?.*q=coop"))


def test_the_theme_switch_is_remembered(page):
    page.goto("/")
    _ready(page)
    before = page.evaluate("getComputedStyle(document.body).backgroundColor")
    page.locator("aside").get_by_role("button", name=re.compile("^Thème")).click()
    after = page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert after != before
    page.reload()
    _ready(page)
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == after


def test_a_calendar_day_opens_in_a_sheet(page):
    page.goto("/?preset=12m")
    _ready(page)
    cell = page.get_by_role("button", name=re.compile(r"CHF, \d+ transaction")).first
    cell.scroll_into_view_if_needed()
    cell.click()
    sheet = page.get_by_role("dialog")
    expect(sheet).to_be_visible()
    expect(sheet.get_by_text(re.compile(r"\d+ mouvements?"))).to_be_visible()


# --- on a phone --------------------------------------------------------------------------

def test_the_phone_has_a_tab_bar_and_no_sidebar(phone):
    phone.goto("/")
    _ready(phone)
    expect(phone.locator("aside")).to_have_count(0)
    tabs = phone.get_by_role("navigation", name="Navigation principale")
    expect(tabs.get_by_role("link", name="Accueil")).to_be_visible()
    tabs.get_by_role("link", name="Épargne").tap()
    phone.wait_for_url(re.compile(r"/epargne"))


def test_the_period_opens_as_a_sheet_on_a_phone(phone):
    phone.goto("/?from=2025-05-01&to=2025-05-31")
    _ready(phone)
    phone.get_by_role("button", name="Changer la période").tap()
    sheet = phone.get_by_role("dialog")
    expect(sheet).to_be_visible()
    sheet.get_by_role("button", name="12 mois", exact=True).tap()
    phone.wait_for_url(re.compile(r"preset=12m"))


def test_a_first_tap_reads_a_column_and_a_second_opens_it(phone):
    phone.goto("/?from=2025-01-01&to=2025-12-31&grain=month")
    _ready(phone)
    box = _timeline(phone).bounding_box()
    x, y = box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.5
    phone.touchscreen.tap(x, y)
    expect(phone.locator("[data-chart-tip]")).to_be_visible()
    assert "from=2025-01-01" in phone.url
    phone.touchscreen.tap(x, y)
    phone.wait_for_url(lambda url: "from=2025-01-01" not in url)


def test_a_scenario_is_created_renamed_deleted_and_brought_back(page):
    page.goto("/previsions")
    _ready(page)
    page.get_by_role("button", name="Nouveau scénario").first.click()
    sheet = page.get_by_role("dialog")
    sheet.get_by_role("button", name="Prudent", exact=True).click()
    sheet.get_by_role("button", name="Créer et modifier").click()
    expect(page.locator("[data-plan-shown]")).to_contain_text("Prudent")

    page.get_by_role("button", name="Renommer").click()
    sheet = page.get_by_role("dialog")
    sheet.get_by_role("textbox").fill("Prudent bis")
    sheet.get_by_role("button", name="Renommer").click()
    expect(page.locator("[data-plan-shown]")).to_contain_text("Prudent bis")

    page.get_by_role("button", name="Actions sur « Prudent bis »").click()
    page.get_by_role("menuitem", name="Supprimer").click()
    expect(page.locator("[data-plan-shown]")).not_to_contain_text("Prudent bis")
    page.get_by_role("button", name="Annuler").click()
    expect(page.get_by_role("button", name="Actions sur « Prudent bis »")).to_be_visible()


def test_the_savings_pockets_open_and_their_months_switch(page):
    page.goto("/epargne?preset=all")
    _ready(page)
    page.get_by_role("link", name="Ouvrir IBKR").click()
    page.wait_for_url(re.compile(r"focus=ibkr"))
    expect(page.locator('[data-pocket="ibkr"] [aria-current="true"]')).to_have_count(1)
    page.get_by_role("link", name="Revenir à toute l'épargne").click()
    page.wait_for_url(lambda url: "focus=" not in url)

    months = page.locator("#p-months")
    expect(months.locator("[data-months=ibkr]")).to_be_visible()
    months.get_by_role("button", name="Tout", exact=True).click()
    expect(months.locator("[data-months=total]")).to_be_visible()

    evolution = page.locator("#p-evolution")
    evolution.get_by_role("button", name="Empilé").click()
    expect(evolution).to_contain_text("chaque bande est une poche")


def test_a_change_opens_its_category_up_close(page):
    page.goto("/analyse")
    _ready(page)
    changes = page.locator("#p-changes")
    first = changes.get_by_role("link").first
    name = first.inner_text().split("\n")[0].strip()
    first.click()
    page.wait_for_url(re.compile(r"cat="))
    detail = page.locator("#p-detail")
    expect(detail).to_contain_text(name)
    expect(detail).to_contain_text("À qui, sur 12 mois")
    detail.get_by_role("link", name="Toutes les catégories").click()
    page.wait_for_url(lambda url: "cat=" not in url)
    expect(page.locator("#p-profile")).to_be_visible()


def test_the_horizon_and_the_plan_are_chosen_beside_the_title(page):
    page.goto("/previsions")
    _ready(page)
    page.get_by_role("button", name=re.compile(r"^Horizon : ")).click()
    page.locator("[data-radix-popper-content-wrapper] a", has_text="2 ans").click()
    page.wait_for_url(re.compile(r"months=24"))
    page.get_by_role("button", name=re.compile(r"^Scénario affiché : ")).click()
    page.locator("[data-radix-popper-content-wrapper] button", has_text="Nouveau scénario").click()
    expect(page.get_by_role("dialog", name="Nouveau scénario")).to_be_visible()


def test_a_series_is_limited_to_some_months_by_clicking_them(page):
    page.goto("/previsions")
    _ready(page)
    series = page.locator("section").filter(has=page.get_by_role("heading", name="Versements programmés")).last
    series.get_by_role("button", name="Ajouter").click()
    page.get_by_label("Montant de chaque versement").fill("800")
    page.get_by_role("radio", name="certains mois seulement").click()
    months = page.get_by_role("group", name="Mois où le versement a lieu")
    # Opens on May to December; one click adds April back.
    expect(months.get_by_role("button", name="avr", exact=True)).to_have_attribute("aria-pressed", "false")
    months.get_by_role("button", name="avr", exact=True).click()
    if os.environ.get("PMS_SHOTS"):
        page.screenshot(path=os.path.join(os.environ["PMS_SHOTS"], "series-form.png"), full_page=True)
    page.get_by_role("button", name="Ajouter la série").click()
    expect(page.get_by_text("d'avril à décembre")).to_be_visible()


def test_the_median_is_drawn_over_the_columns_when_asked(page):
    page.goto("/?preset=all")
    _ready(page)
    page.get_by_role("button", name="Médiane").click()
    page.wait_for_url(re.compile(r"median=1"))
    # The timeline's own panel: another panel may print a median of its own.
    timeline = page.locator("section").filter(has=page.get_by_role("button", name="Médiane")).last
    expect(timeline.locator("svg text").filter(has_text=re.compile(r"^médiane "))).to_be_visible()
    expect(timeline.get_by_text(re.compile(r"sur \d+ périodes complètes"))).to_be_visible()
    if os.environ.get("PMS_SHOTS"):
        page.locator("section").filter(has=page.get_by_role("button", name="Médiane")).last \
            .screenshot(path=os.path.join(os.environ["PMS_SHOTS"], "median.png"))
    # The switch follows the period, like the stack.
    page.get_by_role("button", name="Médiane").click()
    page.wait_for_url(lambda url: "median=1" not in url)


def test_the_sidebar_folds_to_a_rail_and_stays_folded(page):
    page.goto("/")
    _ready(page)
    page.get_by_role("button", name=re.compile("^Replier la barre latérale")).click()
    rail = page.locator("aside")
    assert rail.bounding_box()["width"] < 80
    # Still every destination, by its name.
    rail.get_by_role("link", name="Transactions").click()
    page.wait_for_url(re.compile(r"/transactions"))
    if os.environ.get("PMS_SHOTS"):
        _ready(page)
        page.wait_for_timeout(800)
        page.screenshot(path=os.path.join(os.environ["PMS_SHOTS"], "rail.png"), clip={"x": 0, "y": 0, "width": 700, "height": 600})
    page.reload()
    _ready(page)
    assert page.locator("aside").bounding_box()["width"] < 80
    page.get_by_role("button", name=re.compile("^Déplier la barre latérale")).click()
    assert page.locator("aside").bounding_box()["width"] > 200


def test_the_manual_opens_on_the_page_being_read_and_its_demos_answer(page):
    page.goto("/epargne")
    _ready(page)
    page.keyboard.press("?")
    page.wait_for_url(re.compile(r"/aide#p-epargne$"))
    expect(page.get_by_role("heading", name="Manuel")).to_be_visible()
    card = page.locator("#p-epargne")
    expect(card).to_be_in_viewport()
    # The demo chart is the real one: a click says where it would lead.
    demo = page.locator("#graphiques")
    chart = demo.get_by_role("img", name=re.compile("^Démonstration : dépense"))
    chart.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    box = chart.bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.7, box["y"] + box["height"] * 0.6)
    expect(demo.get_by_text(re.compile(r"^Ce clic ouvrirait \w+ 2025"))).to_be_visible()
    # The period demo moves with the arrows, like the real switcher.
    period = page.get_by_label(re.compile("^Démonstration de la période"))
    period.click(position={"x": 8, "y": 8})
    page.keyboard.press("ArrowRight")
    expect(period.get_by_text("Juin 2025").first).to_be_visible()
    expect(period.get_by_text("from=2025-06-01")).to_be_visible()
    if os.environ.get("PMS_SHOTS"):
        page.wait_for_timeout(600)
        page.screenshot(path=os.path.join(os.environ["PMS_SHOTS"], "aide.png"), full_page=True)


def test_a_scenario_smooths_its_brokerage_transfers_into_a_new_one(page, server):
    page.goto("/previsions")
    _ready(page)
    rows = page.request.get("/api/previsions").json()["projection"]["rows"]
    keys = [r["key"] for r in rows if not r["partial"]]
    for key, amount in ((keys[1], 5000), (keys[5], 7000)):
        page.request.post("/api/previsions", headers={"Origin": server}, data={
            "action": "add", "month": key, "label": "Vers IBKR", "amount": str(amount), "destination": "taxable"})
    page.request.post("/api/previsions", headers={"Origin": server},
                      data={"action": "plan-save-as", "name": "À lisser"})
    page.reload()
    _ready(page)
    page.get_by_role("button", name="Actions sur « À lisser »").click()
    page.get_by_role("menuitem", name=re.compile("^Lisser les virements IBKR")).click()
    sheet = page.get_by_role("dialog")
    expect(sheet.locator("[data-smooth-amount]")).to_have_text(re.compile(r"^\d[\d'’]* CHF$"))
    sheet.get_by_role("radio", name="certains mois seulement").click()
    expect(sheet.get_by_text("par mois, de mai à décembre")).to_be_visible()
    if os.environ.get("PMS_SHOTS"):
        sheet.screenshot(path=os.path.join(os.environ["PMS_SHOTS"], "lisser.png"))
    sheet.get_by_role("button", name="Créer ce scénario").click()
    expect(page.get_by_role("button", name="Actions sur « À lisser — IBKR mensuel »")).to_be_visible()


def test_a_cash_floor_is_typed_once_and_said_everywhere(page):
    page.goto("/previsions")
    _ready(page)
    low = page.request.get("/api/previsions").json()["projection"]["low"]["amount"]
    field = page.get_by_label("Seuil d'alerte")
    field.fill(f"{round(low + 5000, -3):,.0f}".replace(",", "'"))
    field.press("Enter")
    cash = page.locator("#p-cash")
    expect(cash.get_by_text("Sous ton seuil")).to_be_visible()
    expect(page.locator("aside").get_by_text("Cash sous le seuil")).to_be_visible()
    if os.environ.get("PMS_SHOTS"):
        cash.screenshot(path=os.path.join(os.environ["PMS_SHOTS"], "seuil.png"))
    page.goto("/")
    _ready(page)
    expect(page.get_by_text("Cash projeté sous ton seuil", exact=True)).to_be_visible()
    page.goto("/previsions")
    _ready(page)
    page.get_by_label("Seuil d'alerte").fill("")
    page.get_by_label("Seuil d'alerte").press("Enter")
    expect(page.locator("aside").get_by_text("Cash sous le seuil")).to_have_count(0)


def test_forecast_against_what_happened_reads_month_by_month(page):
    page.goto("/previsions")
    _ready(page)
    panel = page.locator("#p-hindsight")
    panel.scroll_into_view_if_needed()
    # No kept forecast has a whole month behind it yet: the method answers.
    expect(panel.get_by_role("button", name="La méthode seule")).to_have_attribute("aria-pressed", "true")
    expect(panel.locator("[data-hindsight-month]").first).to_be_visible()
    expect(panel.get_by_text(re.compile(r"^Sur les \d+ derniers mois"))).to_be_visible()
    if os.environ.get("PMS_SHOTS"):
        page.wait_for_timeout(600)
        panel.screenshot(path=os.path.join(os.environ["PMS_SHOTS"], "hindsight.png"))
    panel.get_by_role("button", name="Ton plan").click()
    expect(panel.get_by_text(re.compile("Première comparaison le mois prochain|La prévision de ce mois est gardée"))).to_be_visible()


def test_the_tax_still_owed_shows_on_the_tax_page_and_beside_the_cash(page):
    page.goto("/impots")
    _ready(page)
    panel = page.locator("#p-provision")
    expect(panel.get_by_text(re.compile(r"^Taux tiré de 2025"))).to_be_visible()
    if os.environ.get("PMS_SHOTS"):
        panel.screenshot(path=os.path.join(os.environ["PMS_SHOTS"], "provision.png"))
    page.goto("/previsions")
    _ready(page)
    expect(page.locator("#p-cash [data-tax-provision]")).to_contain_text("Impôts encore dus")


def test_monthly_tax_installments_are_set_once_and_paid_in_the_forecast(page, server):
    page.goto("/impots")
    _ready(page)
    page.get_by_label("Je paie par acomptes mensuels").check()
    page.get_by_label("Premier acompte").fill("2026-09")
    page.get_by_label("Montant par mois").fill("450")
    page.get_by_role("button", name="Enregistrer").click()
    expect(page.get_by_text(re.compile(r"acomptes de 450 CHF par mois"))).to_be_visible()
    expect(page.locator("#p-provision [data-installments]")).to_contain_text("4 à venir")
    if os.environ.get("PMS_SHOTS"):
        page.locator("#p-provision").screenshot(path=os.path.join(os.environ["PMS_SHOTS"], "acomptes.png"))
    page.goto("/previsions")
    _ready(page)
    expect(page.get_by_text("Acompte d'impôts").first).to_be_attached()
    # Back to no installments, for the tests after this one.
    page.request.post("/api/impots/reglages", headers={"Origin": server},
                      data={"canton": "", "since": None, "paid_next_year": False, "installments": None})
