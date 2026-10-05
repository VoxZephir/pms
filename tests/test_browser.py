"""app.js in a real browser.

The rest of the suite reads the markup the server sends; nothing there runs
the JavaScript that rewrites it. That layer is where several of the bugs the
user actually hit lived -- a tooltip amount that lost its decimal point
("-813’00", read as millions), the brush overlay that swallowed the hover,
sorting that did nothing on the page a category opens. These drive it.

Playwright steers the Edge or Chrome already installed, so there is no
browser to download. Skipped when Playwright or such a browser is missing.
"""

from __future__ import annotations

import re
import threading
from urllib.parse import parse_qsl, urlsplit

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect

AMOUNT = re.compile(r"-?\d{1,3}(?:’\d{3})*\.\d{2} CHF")
SHOWN = re.compile(r"\bon\b")


@pytest.fixture(scope="module")
def server(ledger_file):
    from werkzeug.serving import make_server

    from pms.web import create_app
    httpd = make_server("127.0.0.1", 0, create_app(ledger_file), threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as playwright:
        launched = None
        for channel in ("msedge", "chrome"):
            try:
                launched = playwright.chromium.launch(channel=channel)
                break
            except sync_api.Error:
                continue
        if launched is None:
            pytest.skip("no installed Edge or Chrome for Playwright to drive")
        yield launched
        launched.close()


@pytest.fixture
def page(browser, server):
    context = browser.new_context(base_url=server,
                                  viewport={"width": 1400, "height": 1000})
    context.set_default_timeout(5000)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    yield page
    context.close()
    assert not errors, f"uncaught JavaScript errors: {errors}"


def _middle(page, selector: str, at: float = 0.5) -> tuple[float, float]:
    """A point on the element, in viewport coordinates -- scrolled into view
    first, or the pointer lands on nothing."""
    target = page.locator(selector)
    target.scroll_into_view_if_needed()
    box = target.bounding_box()
    return box["x"] + box["width"] * at, box["y"] + box["height"] * 0.5


@pytest.mark.parametrize("url", ["/", "/?preset=all", "/transactions",
                                 "/reclasser", "/previsions", "/analyse"])
def test_no_page_throws(page, url):
    """The fixture fails the test on any uncaught error; loading is enough."""
    page.goto(url)
    page.wait_for_load_state("networkidle")


def test_the_balance_tooltip_keeps_its_decimal_point(page):
    """money() once ate the decimal separator: 813.00 came out as 813’00, and
    P2P transfers read as millions. Every amount must read as francs and
    centimes."""
    page.goto("/?preset=all")
    page.mouse.move(*_middle(page, "#balHit"), steps=5)
    tip = page.locator("#tip")
    expect(tip).to_have_class(SHOWN)
    shown = tip.inner_text()
    assert AMOUNT.search(shown), shown
    assert not re.search(r"’\d{2}(?!\d)", shown), shown


def test_the_brush_does_not_cost_the_timeline_its_tooltip(page):
    """The overlay sits above the columns and swallows their mouseover; it
    relays the hover to the column underneath."""
    page.goto("/?preset=12m")
    expect(page.locator("#timelineChart .brushlayer")).to_have_count(1)
    page.mouse.move(*_middle(page, "#timelineChart .brushlayer"), steps=5)
    tip = page.locator("#tip")
    expect(tip).to_have_class(SHOWN)
    assert tip.locator(".t-title").inner_text().strip()


def test_dragging_across_the_timeline_selects_that_range(page):
    page.goto("/?preset=12m")
    page.evaluate("window.__sameDocument = true")
    x0, y = _middle(page, "#timelineChart .brushlayer", at=0.2)
    x1, _ = _middle(page, "#timelineChart .brushlayer", at=0.6)
    page.mouse.move(x0, y)
    page.mouse.down()
    page.mouse.move(x1, y, steps=10)
    page.mouse.up()

    expect(page).to_have_url(re.compile(r"from=\d{4}-\d{2}-\d{2}&to=\d{4}-\d{2}-\d{2}"))
    window = dict(parse_qsl(urlsplit(page.url).query))
    assert window["from"] < window["to"]
    # Swapped in place, not reloaded: the page's own state survived.
    assert page.evaluate("window.__sameDocument") is True


def test_a_view_switch_swaps_the_page_in_place(page):
    page.goto("/?preset=12m")
    page.evaluate("window.__sameDocument = true")
    page.locator("a[data-nav][href*='stack=bucket']").first.click()
    expect(page).to_have_url(re.compile(r"stack=bucket"))
    expect(page.locator("#main")).to_contain_text("Need")
    assert page.evaluate("window.__sameDocument") is True


def test_sorting_works_on_the_page_a_category_opens(page):
    """Clicking a category lands on /transactions?category=...; its sort
    headers once did nothing there."""
    page.goto("/transactions?category=Alimentation")
    before = page.locator("#txPanel .t-lab").all_inner_texts()
    page.locator("#txPanel th a[href*='sort=label']").click()
    expect(page.locator("#txPanel th.on a[href*='sort=label']")).to_have_count(1)
    after = page.locator("#txPanel .t-lab").all_inner_texts()
    assert after != before
    assert after == sorted(after, key=str.casefold, reverse=True)


def test_the_shares_chart_unfolds_and_speaks_in_percent(page):
    """Folded by default; its summary opens it without a request, and its
    tooltip reads percentages, not francs."""
    page.goto("/?preset=all")
    panel = page.locator("#p-shares details.fold")
    expect(panel).not_to_have_attribute("open", "")
    panel.locator(":scope > summary").click()
    expect(panel).to_have_attribute("open", "")
    page.mouse.move(*_middle(page, "#sharesHit"), steps=5)
    tip = page.locator("#tip")
    expect(tip).to_have_class(SHOWN)
    assert re.search(r"Need-?\d+\.\d %", tip.inner_text().replace("\n", "")), tip.inner_text()


def test_a_smoothing_option_keeps_the_chart_open(page):
    page.goto("/?preset=all&shares=income")
    page.evaluate("window.__sameDocument = true")
    page.locator("#p-shares a[data-nav]", has_text="6 mois").click()
    expect(page).to_have_url(re.compile(r"smooth=6"))
    expect(page.locator("#p-shares details.fold")).to_have_attribute("open", "")
    expect(page.locator("#p-shares .raw-line").first).to_be_attached()
    assert page.evaluate("window.__sameDocument") is True


def test_question_mark_opens_the_help_and_escape_only_closes_it(page):
    """Escape climbs the breadcrumb -- except while the help is open: then it
    closes the help and nothing else."""
    page.goto("/?from=2025-05-01&to=2025-05-31")
    expect(page.locator("#helpBtn")).to_be_visible()
    before = page.url
    page.locator("body").press("?")
    expect(page.locator("#shortcuts")).to_have_attribute("open", "")
    page.keyboard.press("Escape")
    expect(page.locator("#shortcuts")).not_to_have_attribute("open", "")
    page.wait_for_timeout(300)
    assert page.url == before


def test_hovering_a_view_switch_fetches_it_before_the_click(page):
    """The click finds the fragment ready: one request, made on hover -- and
    the period bar comes back as its own small fragment, not a whole page."""
    requests: list[str] = []
    page.on("request", lambda r: requests.append(r.url))
    page.goto("/?preset=12m")
    link = page.locator("a[data-nav][href*='stack=bucket']").first
    link.hover()
    page.wait_for_timeout(400)
    fragments = [u for u in requests if "stack=bucket" in u and "fragment=1" in u]
    assert len(fragments) == 1, requests
    link.click()
    expect(page).to_have_url(re.compile(r"stack=bucket"))
    expect(page.locator("#main")).to_contain_text("Need")
    page.wait_for_load_state("networkidle")
    after = [u for u in requests if "stack=bucket" in u]
    assert sum("fragment=1" in u for u in after) == 1, after
    assert any("fragment=controls" in u for u in after), after
    assert not any("fragment" not in u for u in after), after


def test_the_swap_crossfades_unless_motion_is_reduced(page):
    spy = """() => { window.__transitions = 0;
        const original = document.startViewTransition.bind(document);
        document.startViewTransition = (cb) => { window.__transitions++; return original(cb); }; }"""
    page.goto("/?preset=12m")
    page.evaluate(spy)
    page.locator("a[data-nav][href*='stack=bucket']").first.click()
    expect(page).to_have_url(re.compile(r"stack=bucket"))
    assert page.evaluate("window.__transitions") == 1

    page.emulate_media(reduced_motion="reduce")
    page.goto("/?preset=12m")
    page.evaluate(spy)
    page.locator("a[data-nav][href*='stack=bucket']").first.click()
    expect(page).to_have_url(re.compile(r"stack=bucket"))
    assert page.evaluate("window.__transitions") == 0


def test_the_sommaire_is_a_strip_on_a_laptop_and_opens_what_it_points_at(browser, server):
    """Under 1480px the rail used to vanish, leaving a laptop with nothing to
    navigate by. It is now a strip under the header; a folded panel it points
    at opens, and lands below the header and the strip, not under them."""
    context = browser.new_context(base_url=server,
                                  viewport={"width": 1280, "height": 800})
    page = context.new_page()
    try:
        page.goto("/?preset=all")
        strip = page.locator(".toc")
        expect(strip).to_be_visible()
        assert strip.evaluate("e => getComputedStyle(e).position") == "sticky"
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(400)
        header = page.evaluate("document.querySelector('header.top').offsetHeight")
        assert abs(strip.bounding_box()["y"] - header) <= 1   # stuck under it

        requests: list[str] = []
        page.on("request", lambda r: requests.append(r.url))
        strip.locator("a[href='#p-custodian']").click()
        panel = page.locator("#p-custodian details.fold")
        # Smooth scrolling: wait until the page stops moving.
        page.wait_for_function("""() => new Promise(done => {
            let last = -1; const tick = () => { if (scrollY === last) done(true);
            else { last = scrollY; setTimeout(tick, 120); } }; tick(); })""")
        # Still open once the page has settled: an anchor is a scroll, not a
        # page change -- nothing re-fetched <main> behind it.
        expect(panel).to_have_attribute("open", "")
        assert not [u for u in requests if "fragment=" in u], requests
        top = page.locator("#p-custodian").bounding_box()["y"]
        strip_bottom = strip.bounding_box()["y"] + strip.bounding_box()["height"]
        assert top >= strip_bottom - 1

        page.evaluate("location.hash = 'p-years'")
        expect(page.locator("#p-years details.fold")).to_have_attribute("open", "")
    finally:
        context.close()


def test_the_calendar_speaks_on_hover_and_builds_its_table_on_demand(page):
    page.goto("/?preset=all")
    cell = page.locator("#p-calendar rect.cell:not(.empty)").nth(40)
    cell.scroll_into_view_if_needed()
    cell.hover()
    tip = page.locator("#tip")
    expect(tip).to_have_class(SHOWN)
    assert re.search(r"\d{2}\.\d{2}\.\d{4}", tip.inner_text())
    assert AMOUNT.search(tip.inner_text())
    lazy = page.locator("#p-calendar details[data-lazy-table]")
    lazy.locator(":scope > summary").click()
    expect(lazy.locator("tbody tr").first).to_be_attached()
    assert lazy.locator("tbody tr").count() > 100


def test_the_new_statement_notice_can_be_dismissed_for_good(page):
    page.goto("/?preset=all")
    notice = page.locator("[data-news]")
    expect(notice).to_be_visible()
    notice.locator(".news-close").click()
    expect(page.locator("[data-news]")).to_have_count(0)
    page.reload()
    page.wait_for_load_state("load")
    expect(page.locator("[data-news]")).to_have_count(0)


def test_arrows_step_periods_even_with_a_link_focused(page):
    """They used to go dead as soon as a link had focus -- after almost any
    click. The default view is the month in progress; ← is last month."""
    page.goto("/")
    page.locator(".toc a").first.focus()
    page.keyboard.press("ArrowLeft")
    expect(page).to_have_url(re.compile(r"from=2026-06-01&to=2026-06-30"))
    # Twice in a row, no pause: the second press must read the new period
    # bar, not the one the first press left behind.
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")
    expect(page).to_have_url(re.compile(r"from=2026-04-01&to=2026-04-30"))
    page.keyboard.press("ArrowRight")
    expect(page).to_have_url(re.compile(r"from=2026-05-01&to=2026-05-31"))
    # Alt+← is the browser's back, never ours.
    before = page.url
    page.keyboard.press("Alt+ArrowRight")
    page.wait_for_timeout(300)
    assert page.url == before


def test_the_corrections_filter_narrows_and_unfolds(browser, tmp_path_factory, ledger_file):
    import threading

    from werkzeug.serving import make_server
    from webhelpers import corrected_ledger

    app = corrected_ledger(tmp_path_factory, ledger_file, pins=12)
    httpd = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    context = browser.new_context(base_url=f"http://127.0.0.1:{httpd.server_port}")
    page = context.new_page()
    try:
        page.goto("/reclasser")
        field = page.locator("#corrections-filter")
        expect(field).to_be_visible()
        pins = page.locator("details[data-group='pin']")
        expect(pins).not_to_have_attribute("open", "")
        field.fill("sushi")
        expect(page.locator("details[data-group='rule'] tbody tr:not([hidden])")).to_have_count(1)
        expect(pins).to_be_hidden()
        field.fill("zzz-nothing")
        expect(page.locator("[data-filter-empty]")).to_be_visible()
        field.fill("")
        expect(pins).to_be_visible()
        expect(pins).not_to_have_attribute("open", "")
    finally:
        context.close()
        httpd.shutdown()


def test_the_twint_triage_is_one_key_per_twint(browser, tmp_path_factory, ledger_file):
    """1-9 classify, S skips, Z undoes -- each a real button or link."""
    from werkzeug.serving import make_server

    from pms.web import create_app

    workdir = tmp_path_factory.mktemp("triagekeys")
    (workdir / "ledger.json").write_bytes(ledger_file.read_bytes())
    httpd = make_server("127.0.0.1", 0, create_app(workdir / "ledger.json"),
                        threaded=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    context = browser.new_context(base_url=f"http://127.0.0.1:{httpd.server_port}")
    page = context.new_page()
    try:
        page.goto("/reclasser/tri")
        sub = page.locator(".title-row .sub")
        count = int(re.search(r"(\d+) à identifier", sub.inner_text()).group(1))
        first = page.locator("button[data-key='1']").get_attribute("value")

        page.keyboard.press("1")
        expect(sub).to_contain_text(f"{count - 1} à identifier")
        expect(page.locator("[data-triage-undo]")).to_contain_text(first)

        page.keyboard.press("s")
        expect(page).to_have_url(re.compile(r"at=1"))

        page.keyboard.press("z")
        expect(sub).to_contain_text(f"{count} à identifier")
    finally:
        context.close()
        httpd.shutdown()


def test_live_search_ends_on_the_last_thing_typed(page, server):
    """One request per keystroke burst, answered out of order: an older,
    broader result must never land last."""
    page.goto("/transactions")
    page.locator("#tx-q").press_sequentially("coop", delay=40)
    body = page.request.get(f"{server}/transactions?q=coop&fragment=1").text()
    count = re.search(r"([\d’]+) lignes?", body).group(1)
    expect(page.locator("#txPanel")).to_contain_text(f"{count} ligne")
