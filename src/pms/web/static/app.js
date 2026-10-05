/* Progressive enhancement only.
 *
 * Every control on the page is already a working link or form. This file makes
 * navigation feel instant by fetching the same URL and swapping <main> in place,
 * and adds the tooltip layer. With JavaScript disabled the app still works --
 * it just does full page loads.
 */
(function () {
  "use strict";

  /* --------------------------------------------------------------- theme */
  var root = document.documentElement;
  var themeBtn = document.getElementById("themeBtn");
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var dark = getComputedStyle(root).getPropertyValue("--page").trim() === "#0d0d0d";
      var next = dark ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("pms-theme", next); } catch (e) {}
    });
  }

  /* ------------------------------------------------------------- tooltip */
  var tip = document.getElementById("tip");

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function row(label, value, colour) {
    return '<div class="t-row"><span>' +
      (colour ? '<i style="background:' + colour + '"></i>' : "") + esc(label) +
      "</span><b>" + esc(value) + "</b></div>";
  }
  /* The ±1σ band row: an annotation, so no colour chip -- same shape as a
     row, quieter styling. */
  function bandRow(label, value) {
    return '<div class="t-band"><span>' + esc(label) + "</span><b>" +
      esc(value) + "</b></div>";
  }
  function hide() { if (tip) tip.classList.remove("on"); }

  /* The calendar's cells carry no payload of their own: the day's figures
     come from #chartData, keyed by the date in the cell's link. */
  var calendarDays = {};
  function frDate(iso) {
    var p = iso.split("-");
    return p[2] + "." + p[1] + "." + p[0];
  }
  function calendarPanel(el) {
    var link = el.closest && el.closest("a[href^='/day/']");
    if (!link || !el.classList.contains("cell")) return "";
    var iso = link.getAttribute("href").slice(5);
    var day = calendarDays[iso] || [0, 0];
    return '<div class="t-title">' + esc(frDate(iso)) + "</div>" +
      row("Dépensé", money(day[0], 2) + " CHF", "") +
      row("Transactions", String(day[1]), "") +
      '<div class="t-hint">Ouvrir la journée</div>';
  }

  function panel(el) {
    var title = el.getAttribute("data-title");
    var rows = el.getAttribute("data-rows");
    if (!title && !rows) {
      var day = calendarPanel(el);
      if (day) return day;
    }
    var html = title ? '<div class="t-title">' + esc(title) + "</div>" : "";
    if (rows) {
      try {
        JSON.parse(rows).forEach(function (r) { html += row(r[0], r[1], r[2] || ""); });
      } catch (e) { /* malformed payload: fall through to the totals below */ }
    }
    var total = el.getAttribute("data-total");
    if (total) {
      html += '<div class="t-sep"></div>' + row("Total dépensé", total + " CHF", "");
      var income = el.getAttribute("data-income");
      if (income && parseFloat(income.replace(/[^\d.-]/g, "")) > 0) {
        html += row("Encaissé", income + " CHF", "");
      }
      html += row("Transactions", el.getAttribute("data-count") || "0", "");
    }
    var hint = el.getAttribute("data-hint");
    if (hint) html += '<div class="t-hint">' + esc(hint) + "</div>";
    return html;
  }

  function place(el) {
    if (!tip) return;
    var html = panel(el);
    if (!html) return;
    var box = el.getBoundingClientRect();
    tip.innerHTML = html;
    tip.style.left = Math.min(Math.max(box.left + box.width / 2, 100), window.innerWidth - 100) + "px";
    tip.style.top = Math.max(box.top + (box.height > 220 ? 44 : 2), 92) + "px";
    tip.classList.add("on");
  }

  document.addEventListener("mouseover", function (ev) {
    var el = ev.target.closest && ev.target.closest("[data-tip]");
    if (el) place(el);
  });
  document.addEventListener("mouseout", function (ev) {
    if (ev.target.closest && ev.target.closest("[data-tip]")) hide();
  });
  /* Keyboard parity: focusing a mark shows what hovering it would. */
  document.addEventListener("focusin", function (ev) {
    var el = ev.target.closest && ev.target.closest("[data-tip]");
    if (!el && ev.target.tagName === "A") {
      /* SVG links carry the payload on a rect child, not the <a> itself. */
      el = ev.target.querySelector("[data-tip]");
    }
    if (el) place(el);
  });
  document.addEventListener("focusout", hide);
  window.addEventListener("scroll", hide, { passive: true });


  /* ------------------------------------- crosshair on the two line charts */
  /* Rebuilt after every <main> swap, because the SVGs are replaced wholesale. */
  function crosshair(svgId, hitId, crossId, series, geom, title, fmt, bandFmt) {
    var svg = document.getElementById(svgId);
    var hit = document.getElementById(hitId);
    var cross = document.getElementById(crossId);
    if (!svg || !hit || !cross) return;
    var dots = svg.querySelectorAll(".focus-dot");

    hit.addEventListener("mousemove", function (ev) {
      var box = svg.getBoundingClientRect();
      /* The SVG is scaled by its viewBox, so convert client px to user units. */
      var scale = geom.width / box.width;
      var t = ((ev.clientX - box.left) * scale - geom.padLeft) / geom.plotW;
      t = Math.max(0, Math.min(1, t));

      var rows = "";
      dots.forEach(function (dot) {
        if (dot.style.display === "none") { dot.classList.remove("on"); return; }
        var s = series[+dot.getAttribute("data-slot")];
        if (!s) { dot.classList.remove("on"); return; }
        var p = s.pts[Math.round(t * (s.pts.length - 1))];
        /* null means the series has no data that far in yet -- carrying the
           last value forward would state a total that was never reached. */
        if (!p) { dot.classList.remove("on"); return; }
        dot.setAttribute("cx", p[0]);
        dot.setAttribute("cy", p[1]);
        dot.classList.add("on");
        /* A series with a fixed colour (a bucket) names it; the rest take
           their validated slot. */
        rows += row(s.name, fmt(p[2]), s.fill || "var(--s" + s.slot + ")");
        /* The band exists only where the polygon has thickness: a point
           without low/high fields is observed, and low == high is the
           degenerate band (vol 0, the join, empty pockets) -- neither draws. */
        if (bandFmt && p.length > 3 && p[4] > p[3]) {
          rows += bandRow("±1σ", bandFmt(p[3], p[4]));
        }
      });

      var x = geom.padLeft + t * geom.plotW;
      cross.setAttribute("x1", x);
      cross.setAttribute("x2", x);
      cross.classList.add("on");
      if (!tip) return;
      tip.innerHTML = '<div class="t-title">' + title(t) + "</div>" + rows;
      tip.style.left = Math.min(Math.max(ev.clientX, 100), window.innerWidth - 100) + "px";
      tip.style.top = Math.max(box.top + 26, 92) + "px";
      tip.classList.add("on");
    });
    hit.addEventListener("mouseleave", function () {
      cross.classList.remove("on");
      dots.forEach(function (d) { d.classList.remove("on"); });
      hide();
    });
  }

  var MONTHS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
                   "juil.", "août", "sept.", "oct.", "nov.", "déc."];

  function wireCharts() {
    var payload = document.getElementById("chartData");
    if (!payload) return;
    var data;
    try { data = JSON.parse(payload.textContent); } catch (e) { return; }
    calendarDays = data.calendar || {};

    if (data.balance) {
      crosshair("balChart", "balHit", "balCross", data.balance.series,
                data.balance.geom,
                function (t) {
                  var d = data.balance.dates;
                  return d[Math.round(t * (d.length - 1))] || "";
                },
                function (v) { return money(v, 2) + " CHF"; });
    }
    if (data.years) {
      crosshair("yearChart", "yearHit", "yearCross", data.years.series,
                data.years.geom,
                function (t) {
                  var day = Math.max(1, Math.round(t * 365) + 1);
                  var d = new Date(2025, 0, day);
                  return d.getDate() + " " + MONTHS_FR[d.getMonth()];
                },
                function (v) { return money(v, 0) + " CHF"; });
    }
    if (data.projection) {
      crosshair("projChart", "projHit", "projCross", data.projection.series,
                data.projection.geom,
                function (t) {
                  var labels = data.projection.labels;
                  return labels[Math.round(t * (labels.length - 1))] || "";
                },
                function (v) { return money(v, 0) + " CHF"; });
    }
    if (data.wealth) {
      crosshair("wealthChart", "wealthHit", "wealthCross", data.wealth.series,
                data.wealth.geom,
                function (t) {
                  var labels = data.wealth.labels;
                  return labels[Math.round(t * (labels.length - 1))] || "";
                },
                function (v) { return money(v, 0) + " CHF"; },
                function (lo, hi) {
                  return money(lo, 0) + " – " + money(hi, 0) + " CHF";
                });
    }
    if (data.ibkr) {
      crosshair("ibkrChart", "ibkrHit", "ibkrCross", data.ibkr.series,
                data.ibkr.geom,
                function (t) {
                  var labels = data.ibkr.labels;
                  return labels[Math.round(t * (labels.length - 1))] || "";
                },
                /* Base 100 prints an index level, one decimal, no francs. */
                data.ibkr.unit === ""
                  ? function (v) { return v.toFixed(1); }
                  : function (v) { return money(v, 0) + " CHF"; });
    }
    /* The bucket shares, month by month -- in percent, not francs. */
    if (data.shares) {
      crosshair("sharesChart", "sharesHit", "sharesCross", data.shares.series,
                data.shares.geom,
                function (t) {
                  var labels = data.shares.labels;
                  return labels[Math.round(t * (labels.length - 1))] || "";
                },
                function (v) { return v.toFixed(1) + " %"; });
    }
    /* The monthly-profile bars: one point per calendar month, so the dot
       lands on the bar's top -- the full median and the stripped remainder. */
    if (data.monthly) {
      crosshair("monthlyChart", "monthlyHit", "monthlyCross", data.monthly.series,
                data.monthly.geom,
                function (t) {
                  var labels = data.monthly.labels;
                  return labels[Math.round(t * (labels.length - 1))] || "";
                },
                function (v) { return money(v, 0) + " CHF"; });
    }
    /* The category drill: one point per observed month of the category. */
    if (data.category) {
      crosshair("categoryChart", "categoryHit", "categoryCross", data.category.series,
                data.category.geom,
                function (t) {
                  var labels = data.category.labels;
                  return labels[Math.round(t * (labels.length - 1))] || "";
                },
                function (v) { return money(v, 0) + " CHF"; });
    }
  }

  function money(n, d) {
    var neg = n < 0;
    var s = Math.abs(n).toFixed(d);
    var dot = s.indexOf(".");
    var whole = dot === -1 ? s : s.slice(0, dot);
    var frac = dot === -1 ? "" : s.slice(dot);
    return (neg ? "-" : "") + whole.replace(/\B(?=(\d{3})+(?!\d))/g, "’") + frac;
  }

  wireCharts();

  /* The "new statement" notice can be dismissed, per statement: a per-viewer
     convenience, so browser storage -- and a page that works without it. */
  var NEWS_KEY = "pms-news-dismissed";
  function wireNews() {
    var box = document.querySelector("[data-news]");
    if (!box) return;
    var sha = box.getAttribute("data-news");
    var dismissed = null;
    try { dismissed = localStorage.getItem(NEWS_KEY); } catch (e) { /* private mode */ }
    if (sha && dismissed === sha) { box.remove(); return; }
    var close = box.querySelector(".news-close");
    if (!close) return;
    close.hidden = false;
    close.addEventListener("click", function () {
      try { localStorage.setItem(NEWS_KEY, sha); } catch (e) { /* still hide it */ }
      box.remove();
    });
  }
  wireNews();

  /* A live filter over grouped tables (the corrections): it narrows every
     group at once, unfolds the ones with a match and hides the others, and
     folds back to the page's own state once cleared. Its field stays hidden
     without JavaScript: the groups still open by hand. */
  function wireRowFilter() {
    document.querySelectorAll("[data-filter-rows]").forEach(function (input) {
      if (input.dataset.wired) return;
      input.dataset.wired = "1";
      var wrap = input.closest("[data-filter-wrap]");
      if (wrap) wrap.hidden = false;
      var scope = document.querySelector(input.getAttribute("data-filter-rows"));
      if (!scope) return;
      var groups = [].slice.call(scope.querySelectorAll("details.group-fold"));
      var initial = groups.map(function (g) { return g.open; });
      var empty = scope.querySelector("[data-filter-empty]");
      input.addEventListener("input", function () {
        var needle = input.value.trim().toLowerCase();
        var any = false;
        groups.forEach(function (group, i) {
          var hits = 0;
          group.querySelectorAll("tbody tr").forEach(function (tr) {
            var show = !needle || tr.textContent.toLowerCase().indexOf(needle) !== -1;
            tr.hidden = !show;
            if (show) hits++;
          });
          group.hidden = !!needle && !hits;
          group.open = needle ? hits > 0 : initial[i];
          if (hits) any = true;
        });
        if (empty) empty.hidden = !needle || any;
      });
    });
  }
  wireRowFilter();

  /* The calendar's twin table, built on its first unfold from the same
     #chartData as the tooltips: the longest table on the page no longer
     ships with every render. `toggle` does not bubble, hence the capture. */
  document.addEventListener("toggle", function (ev) {
    var box = ev.target;
    if (!box.matches || !box.matches("details[data-lazy-table='calendar']")) return;
    if (!box.open || box.querySelector("table")) return;
    var days = Object.keys(calendarDays).sort();
    var body = days.map(function (iso) {
      var d = calendarDays[iso];
      return '<tr><td class="num">' + frDate(iso) + '</td>' +
        '<td class="r num">' + money(d[0], 2) + '</td>' +
        '<td class="r num">' + d[1] + '</td></tr>';
    }).join("");
    var wrap = document.createElement("div");
    wrap.className = "tbl-wrap tbl-scroll";
    wrap.innerHTML = '<table class="data"><thead><tr>' +
      '<th class="l">Date</th><th class="r">Dépensé</th>' +
      '<th class="r">Transactions</th></tr></thead><tbody>' + body +
      "</tbody></table>";
    var fallback = box.querySelector("[data-lazy-fallback]");
    if (fallback) fallback.replaceWith(wrap); else box.appendChild(wrap);
  }, true);


  /* ------------------------------------------- sorting the smaller tables */
  /* The transactions table sorts server-side because it is paged. Every other
     table in the app shows all of its rows at once, so sorting them in the
     browser is both correct and instant. A column declares its type on the
     <th>; anything else is compared as text. */
  function cellValue(row, index, type) {
    var cell = row.cells[index];
    if (!cell) return type === "num" ? 0 : "";
    var raw = cell.getAttribute("data-sort");
    if (raw === null) raw = cell.textContent.trim();

    if (type === "num") {
      var n = parseFloat(raw.replace(/[’'\s]/g, "").replace(/[^\d.,-]/g, "").replace(",", "."));
      return isNaN(n) ? 0 : n;
    }
    if (type === "date") {
      var m = raw.match(/(\d{2})\.(\d{2})\.(\d{4})/);
      return m ? m[3] + m[2] + m[1] : raw;
    }
    return raw.toLocaleLowerCase("fr");
  }

  function sortTable(table, index, dir) {
    var head = table.tHead.rows[0].cells[index];
    var type = head.getAttribute("data-type") || "text";
    var body = table.tBodies[0];
    var rows = [].slice.call(body.rows).filter(function (r) {
      return r.cells.length > 1;          /* keep "no results" rows out of it */
    });

    rows.sort(function (a, b) {
      var x = cellValue(a, index, type), y = cellValue(b, index, type);
      if (type === "num") return (x - y) * dir;
      return String(x).localeCompare(String(y), "fr") * dir;
    });
    rows.forEach(function (r) { body.appendChild(r); });

    [].forEach.call(table.tHead.rows[0].cells, function (th) {
      th.classList.remove("on");
      th.removeAttribute("aria-sort");
      var a = th.querySelector(".arrow");
      if (a) a.textContent = "";
    });
    head.classList.add("on");
    head.setAttribute("aria-sort", dir > 0 ? "ascending" : "descending");
    var arrow = head.querySelector(".arrow");
    if (arrow) arrow.textContent = dir > 0 ? "▴" : "▾";
  }

  function wireSortableTables(root) {
    (root || document).querySelectorAll("table.sortable-table").forEach(function (table) {
      if (table.dataset.sortWired || !table.tHead || !table.tBodies.length) return;
      table.dataset.sortWired = "1";
      [].forEach.call(table.tHead.rows[0].cells, function (th, i) {
        if (th.getAttribute("data-type") === "none") return;
        th.classList.add("sortable");
        if (!th.querySelector(".arrow")) {
          var span = document.createElement("span");
          span.className = "arrow";
          th.appendChild(span);
        }
        th.tabIndex = 0;
        th.setAttribute("role", "button");
        var flip = function () {
          var dir = th.classList.contains("on") &&
                    th.getAttribute("aria-sort") === "ascending" ? -1 : 1;
          sortTable(table, i, dir);
        };
        th.addEventListener("click", flip);
        th.addEventListener("keydown", function (ev) {
          if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); flip(); }
        });
      });
    });
  }

  wireSortableTables();

  /* ----------------------------------- legend toggles on the savings plot */
  /* Clicking a legend entry hides or shows that line. Pure view preference,
     rebuilt from scratch on every swap -- the URL keeps the window, the
     split and the focus, not the display state. */
  function wireLegendToggles() {
    var svg = document.getElementById("ibkrChart");
    if (!svg) return;
    Array.prototype.slice.call(
      document.querySelectorAll("[data-legend]")).forEach(function (item) {
      item.addEventListener("click", function () { toggleLine(item); });
      item.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggleLine(item); }
      });
    });
  }

  function toggleLine(item) {
    var key = item.getAttribute("data-legend");
    var off = item.classList.toggle("off");
    item.classList.toggle("on", !off);
    item.setAttribute("aria-pressed", off ? "false" : "true");
    var svg = document.getElementById("ibkrChart");
    svg.querySelectorAll('polyline[data-key="' + key + '"]').forEach(function (line) {
      line.style.display = off ? "none" : "";
    });
    svg.querySelectorAll('.focus-dot[data-key="' + key + '"]').forEach(function (dot) {
      dot.style.display = off ? "none" : "";
    });
    rescaleAxis();
  }

  /* Re-fit the y axis to the visible lines: the same arithmetic the server
     used, redone client-side on every legend toggle. The values live in the
     crosshair payload; only the coordinates change. */
  function rescaleAxis() {
    var svg = document.getElementById("ibkrChart");
    var payload = document.getElementById("chartData");
    if (!svg || !payload) return;
    var data;
    try { data = JSON.parse(payload.textContent); } catch (e) { return; }
    var proj = data.ibkr;
    if (!proj) return;
    var geom = proj.geom;
    var padTop = parseFloat(svg.getAttribute("data-pad-top")) || geom.padTop;
    var plotH = parseFloat(svg.getAttribute("data-plot-h")) || geom.plotH;

    var visible = [];
    svg.querySelectorAll(".focus-dot[data-key]").forEach(function (dot) {
      if (dot.style.display === "none") return;
      var s = proj.series[+dot.getAttribute("data-slot")];
      if (s) visible.push(s);
    });
    var values = [];
    visible.forEach(function (s) {
      s.pts.forEach(function (p) { if (p) values.push(p[2]); });
    });
    if (!values.length) return;

    var scale = svg.getAttribute("data-scale") || "zero";
    var vmin = scale === "zero" ? 0 : Math.min.apply(null, values);
    var vmax = Math.max.apply(null, values);
    var mag = Math.pow(10, String(Math.round(vmax)).length - 1);
    var steps = [1, 2, 2.5, 5, 10];
    for (var i = 0; i < steps.length; i++) {
      if (mag * steps[i] >= vmax) { vmax = mag * steps[i]; break; }
    }
    if (vmax <= vmin) vmax = vmin + 1;

    function yOf(v) { return padTop + plotH * (1 - (v - vmin) / (vmax - vmin)); }

    visible.forEach(function (s) {
      var key = "";
      svg.querySelectorAll(".focus-dot[data-key]").forEach(function (dot) {
        if (+dot.getAttribute("data-slot") === s.slot) key = dot.getAttribute("data-key");
      });
      var points = [];
      s.pts.forEach(function (p) {
        if (p) { p[1] = yOf(p[2]); points.push(p[0].toFixed(2) + "," + p[1].toFixed(2)); }
      });
      svg.querySelectorAll('polyline[data-key="' + key + '"]').forEach(function (line) {
        line.setAttribute("points", points.join(" "));
      });
    });

    var ticks = [[vmin, 0], [(vmin + vmax) / 2, 0.5], [vmax, 1]];
    var gridlines = svg.querySelectorAll("line.gridline");
    var labels = svg.querySelectorAll("text.axis-y");
    ticks.forEach(function (tick, i) {
      var y = padTop + plotH * (1 - tick[1]);
      if (gridlines[i]) gridlines[i].setAttribute("y1", y.toFixed(2));
      if (gridlines[i]) gridlines[i].setAttribute("y2", y.toFixed(2));
      if (labels[i]) { labels[i].setAttribute("y", (y + 4).toFixed(2)); labels[i].textContent = money(tick[0], 0); }
    });
  }

  /* ----------------------------------------- scrollspy on the toc rail */
  /* The rail works without this (plain anchors); the spy only highlights
     the section currently in view. Rebuilt after every <main> swap. */
  var spy = null;
  function wireScrollspy() {
    if (spy) window.removeEventListener("scroll", spy);
    spy = null;
    var toc = document.querySelector(".toc");
    if (!toc) return;
    var links = Array.prototype.slice.call(toc.querySelectorAll("a"));
    var sections = links.map(function (a) {
      return document.querySelector(a.getAttribute("href"));
    }).filter(Boolean);
    var current = null;
    spy = function () {
      var line = headerHeight() + 64;
      var mark = null;
      sections.forEach(function (sec, i) {
        if (sec.getBoundingClientRect().top <= line) mark = links[i];
      });
      links.forEach(function (l) { l.classList.toggle("on", l === mark); });
      /* As a strip (under 1480px) the sommaire scrolls sideways; keep the
         section in view in view there too. Moving the strip, never the page. */
      if (mark && mark !== current && toc.scrollWidth > toc.clientWidth) {
        toc.scrollLeft = mark.offsetLeft - (toc.clientWidth - mark.offsetWidth) / 2;
      }
      current = mark;
    };
    window.addEventListener("scroll", spy, { passive: true });
    spy();
  }

  /* The header wraps on a narrow window, so the strip under it cannot hard-
     code its offset: the header says how tall it is. */
  var header = document.querySelector("header.top");
  function headerHeight() { return header ? header.offsetHeight : 59; }
  function measureHeader() {
    root.style.setProperty("--header-h", headerHeight() + "px");
  }
  measureHeader();
  window.addEventListener("resize", measureHeader, { passive: true });

  /* A folded panel reached by an anchor -- the sommaire, a link, a #hash in
     the URL -- opens: landing on a closed summary would read as a link that
     did nothing. Opened before the browser scrolls, so it lands right. */
  function unfold(hash) {
    if (!hash || hash.length < 2) return;
    var target = document.getElementById(decodeURIComponent(hash.slice(1)));
    var fold = target && (target.matches("details.fold") ? target
                          : target.querySelector("details.fold"));
    if (fold && !fold.open) fold.open = true;
  }
  document.addEventListener("click", function (ev) {
    var link = ev.target.closest && ev.target.closest('a[href^="#"]');
    if (link) unfold(link.getAttribute("href"));
  });
  window.addEventListener("hashchange", function () { unfold(location.hash); });
  unfold(location.hash);

  wireScrollspy();
  wireLegendToggles();

  /* ---------------------------------------------------- in-place navigation */
  var main = document.getElementById("main");
  var controls = document.getElementById("controls");
  var inflight = null;
  var swapSeq = 0;
  var settled = Promise.resolve();
  /* The page on screen, without its #fragment: what popstate compares to. */
  var shown = location.pathname + location.search;

  /* Pages that serve their own fragment -- the only ones a swap may target. */
  var SWAPPABLE = ["/", "/previsions", "/analyse"];
  function swappable(href) {
    return !!href && href.charAt(0) === "/" &&
      SWAPPABLE.indexOf(href.split("?")[0]) !== -1;
  }
  function fragmentUrl(url, kind) {
    return url + (url.indexOf("?") === -1 ? "?" : "&") + "fragment=" + kind;
  }
  function getText(url, signal) {
    return fetch(url, signal ? { signal: signal } : undefined)
      .then(function (r) { return r.ok ? r.text() : Promise.reject(r.status); });
  }

  /* --------------------------------------------- prefetch on intent */
  /* A swap costs 150-230 ms, mostly the server building the fragment. The
     time between pointing at a link and pressing it is about as long, so
     the fragment is fetched on hover (after a short pause, so sweeping the
     pointer across a row of links does not fire a request per link) or on
     keyboard focus, and the click finds it ready. Kept 10 s at most, and
     dropped on every write: a view fetched before a reclassification must
     not come back with the numbers it had before. */
  var PREFETCH_TTL = 10000;
  var PREFETCH_DELAY = 65;
  var prefetched = {};
  var intent = null;

  function prefetch(url) {
    var hit = prefetched[url];
    if (hit && Date.now() - hit.at < PREFETCH_TTL) return;
    var entry = { at: Date.now(), html: getText(fragmentUrl(url, "1")) };
    entry.html.catch(function () {
      if (prefetched[url] === entry) delete prefetched[url];
    });
    prefetched[url] = entry;
  }
  function takePrefetched(url) {
    var hit = prefetched[url];
    prefetched = {};   // the page is about to change; every other guess is stale
    return hit && Date.now() - hit.at < PREFETCH_TTL ? hit.html : null;
  }
  /* Every write goes through here, so no prefetched view outlives it. */
  function send(url, options) {
    prefetched = {};
    return fetch(url, options);
  }

  function intendedLink(target) {
    var link = target.closest && target.closest("a[data-nav]");
    if (!link || link.getAttribute("aria-disabled") === "true") return null;
    var href = link.getAttribute("href") || (link.href && link.href.baseVal);
    if (!swappable(href)) return null;
    /* After a swap the pointer still rests on the link it clicked, which now
       points at the page on screen: fetching that again would be waste. */
    return new URL(href, location.href).href === location.href ? null : href;
  }
  document.addEventListener("mouseover", function (ev) {
    var href = intendedLink(ev.target);
    if (!href) return;
    clearTimeout(intent);
    intent = setTimeout(function () { prefetch(href); }, PREFETCH_DELAY);
  });
  document.addEventListener("mouseout", function (ev) {
    if (intendedLink(ev.target)) clearTimeout(intent);
  });
  document.addEventListener("focusin", function (ev) {
    var href = intendedLink(ev.target);
    if (href) prefetch(href);
  });

  /* A short crossfade instead of a blink, where the browser has one and the
     reader has not asked for less motion. Everything else -- the swap, the
     scroll position, the fallback -- is the same with or without it. */
  function transition(update) {
    var calm = window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!document.startViewTransition || calm) {
      update();
      return Promise.resolve();
    }
    return document.startViewTransition(update).updateCallbackDone;
  }

  function swap(url, push) {
    if (!main) { window.location.href = url; return; }
    if (inflight) inflight.abort();
    var ctrl = new AbortController();
    inflight = ctrl;
    var seq = ++swapSeq;

    var ready = takePrefetched(url);
    /* Hold the previous render at reduced opacity -- no skeleton flash, no
       layout jump while the next one is on the wire. A prefetched fragment
       is already here, so it does not dim at all. */
    if (!ready) main.classList.add("loading");

    /* `settled` resolves once <main> *and* the period bar show this page:
       ← pressed twice in a row must read the second arrow from the new bar,
       not from the one the first press left behind. */
    settled = (ready || getText(fragmentUrl(url, "1"), ctrl.signal))
      .then(function (html) {
        if (seq !== swapSeq) return;   // a later swap won the race
        return transition(function () {
          main.innerHTML = html;
          main.classList.remove("loading");
          wireCharts();
          wireSortableTables(main);
          wireScrollspy();
          wireLegendToggles();
          refreshBulk();
          wireBrush();
          wireCalendarRoving();
          wireNews();
        }).then(function () {
          focusMainHeading();
          if (push) history.pushState({ url: url }, "", url);
          shown = url.split("#")[0];
          /* The period controls live outside <main>, so refresh them separately. */
          return refreshControls(url, ctrl.signal);
        });
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") return;
        if (seq !== swapSeq) return;
        window.location.href = url;   // fall back to a real navigation
      });
  }

  function refreshControls(url, signal) {
    /* The dashboard serves its controls alone -- cheap, no aggregation. The
       other pages have no period controls; only their title is refreshed. */
    var target = url.split("?")[0] === "/" ? fragmentUrl(url, "controls") : url;
    return fetch(target, { signal: signal })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        /* Without #controls (the analysis page has none) the swap must
           still refresh the tab title -- a stale one announces a page
           that is no longer showing. */
        if (controls) {
          var fresh = doc.getElementById("controls");
          var crumbs = doc.querySelector(".crumbs");
          if (fresh) controls.replaceWith(fresh), (controls = fresh);
          var current = document.querySelector(".crumbs");
          if (fresh && crumbs && current) current.replaceWith(crumbs);
        }
        if (doc.title) document.title = doc.title;
      })
      .catch(function () { /* controls stay as they are; the page still works */ });
  }

  /* Delegated so it keeps working after <main> is replaced. */
  document.addEventListener("click", function (ev) {
    if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button !== 0) return;
    var link = ev.target.closest && ev.target.closest("a[data-nav]");
    if (!link) return;
    if (link.getAttribute("aria-disabled") === "true") { ev.preventDefault(); return; }
    var href = link.getAttribute("href") || link.href.baseVal;   // SVG <a>
    /* Swapping <main> only makes sense for pages that serve their own
       fragment. A link to another page must navigate, or it lands there
       stripped of its chrome -- including the #txPanel that sorting and
       paging replace. */
    if (!swappable(href)) return;
    ev.preventDefault();
    hide();
    /* The swap replaces <main> in place, so the scroll position survives:
       switching the savings split, the stack or the wealth view must not
       bounce the reader back to the top of the page. */
    swap(href, true);
  });

  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (!form.matches("[data-nav-form]")) return;
    ev.preventDefault();
    var params = new URLSearchParams(new FormData(form));
    swap(form.getAttribute("action") + "?" + params.toString(), true);
  });

  /* Forms inside <main> that have no pipeline of their own -- the budget
     buttons, the plan forms -- submit in place, so the scroll position
     survives. Without JavaScript the form still posts and the browser
     reloads; that path is untouched. */
  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (!form || !main || !form.closest("#main")) return;
    if (form.closest("#txPanel") || form.matches("[data-refresh]")) return;
    /* GET forms navigate: intercepting one and POSTing it would land on the
       POST route with no action -- the horizon select on /previsions would
       silently rewrite plans.json for nothing. */
    if ((form.getAttribute("method") || "get").toLowerCase() === "get") return;
    var action = form.getAttribute("action");
    if (!action) return;
    ev.preventDefault();
    /* The button that submitted carries its own name and value (the triage
       has one per category); FormData(form) alone drops it, and the server
       received a form with no choice in it. */
    var body = new FormData(form);
    if (ev.submitter && ev.submitter.name) {
      body.append(ev.submitter.name, ev.submitter.value);
    }
    send(action, { method: "POST", body: body,
                    redirect: "follow" })
      .then(function (r) { return r.ok ? { html: r.text(), url: r.url }
                                        : Promise.reject(r.status); })
      .then(function (result) { return result.html.then(function (html) {
          return { html: html, url: result.url }; }); })
      .then(function (result) {
        var doc = new DOMParser().parseFromString(result.html, "text/html");
        var fresh = doc.getElementById("main");
        if (!fresh) { window.location.href = result.url; return; }
        main.innerHTML = fresh.innerHTML;
        wireCharts();
        wireSortableTables(main);
        wireScrollspy();
        wireLegendToggles();
        refreshBulk();
        wireBrush();
        wireCalendarRoving();
        if (result.url && result.url !== location.href) {
          history.pushState({ url: result.url }, "", result.url);
        }
        shown = location.pathname + location.search;
      })
      .catch(function () { form.submit(); });  // real submit as fallback
  });

  /* A click on an in-page anchor (the sommaire) fires popstate too. Swapping
     then re-fetched the whole of <main> for a scroll -- and replaced a panel
     the anchor had just unfolded with a folded copy. Only a change of page,
     not of #fragment, is a swap. */
  window.addEventListener("popstate", function (ev) {
    var target = (ev.state && ev.state.url) || location.pathname + location.search;
    if (target.split("#")[0] === shown) return;
    swap(target, false);
  });

  /* ------------------------------------------------- focus after the swap */
  /* The whole <main> is replaced in place; give the keyboard user an anchor
     at the top of the fresh content instead of letting focus fall back to
     the document body. The heading is a safe target: it never disappears. */
  function focusMainHeading() {
    var h1 = main.querySelector("h1");
    if (h1) {
      h1.tabIndex = -1;
      h1.focus({ preventScroll: true });
    }
  }

  /* The calendar draws hundreds of day cells, all focusable links: tabbing
     through every single day would be a marathon. Roving tabindex -- exactly
     one cell per svg stays in the tab order, and the arrow keys move it. */
  function wireCalendarRoving() {
    var cal = document.getElementById("p-calendar");
    if (!cal) return;
    cal.querySelectorAll("svg").forEach(function (svg) {
      if (svg.dataset.rovingWired) return;
      var cells = svg.querySelectorAll("a");
      if (!cells.length) return;
      svg.dataset.rovingWired = "1";
      cells.forEach(function (c) { c.setAttribute("tabindex", "-1"); });
      cells[0].setAttribute("tabindex", "0");
      svg.addEventListener("keydown", function (ev) {
        var index = [].indexOf.call(cells, ev.target);
        if (index === -1) return;
        var next = null;
        if (ev.key === "ArrowRight") next = index + 1;
        else if (ev.key === "ArrowLeft") next = index - 1;
        else if (ev.key === "ArrowDown") next = index + 7;
        else if (ev.key === "ArrowUp") next = index - 7;
        else if (ev.key === "Home") next = 0;
        else if (ev.key === "End") next = cells.length - 1;
        if (next === null || next < 0 || next >= cells.length) return;
        ev.preventDefault();
        cells.forEach(function (c) { c.setAttribute("tabindex", "-1"); });
        var move = cells[next];
        move.setAttribute("tabindex", "0");
        move.focus();
      });
    });
  }

  /* ------------------------------------------- transaction panel filtering */
  function txPanel() { return document.getElementById("txPanel"); }

  /* Typing fires a request per keystroke-burst, and responses can land out of
     order -- an older, broader result arriving last would silently overwrite a
     newer one. Abort the previous request and ignore anything but the latest. */
  var txInflight = null;

  function loadTx(url) {
    var panel = txPanel();
    if (!panel) return;
    if (txInflight) txInflight.abort();
    var ctrl = new AbortController();
    txInflight = ctrl;
    panel.classList.add("loading");

    /* The panel reloads wholesale; remember where the keyboard focus was so
       the fresh content can hand it back. Computed before the fetch: by the
       time the response lands, the browser may have moved focus elsewhere. */
    var oldActive = document.activeElement;
    var oldId = oldActive && oldActive.id ? oldActive.id : null;
    var wasInPanel = !!oldActive && panel.contains(oldActive);

    fetch(url + (url.indexOf("?") === -1 ? "?" : "&") + "fragment=1",
          { signal: ctrl.signal })
      .then(function (r) { return r.ok ? r.text() : Promise.reject(r.status); })
      .then(function (html) {
        if (ctrl !== txInflight) return;   // superseded while in flight
        panel.innerHTML = html;
        panel.classList.remove("loading");
        wireSortableTables(panel);
        refreshBulk();
        restorePanelFocus(panel, oldId, wasInPanel);
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") return;
        window.location.href = url;
      });
  }

  /* Put focus back where it was after the panel's innerHTML is replaced:
     the same control if it survived (caret at the end of its value for
     inputs), else the panel itself when the old focus lived inside it. */
  function restorePanelFocus(panel, oldId, wasInPanel) {
    if (oldId) {
      var back = document.getElementById(oldId);
      if (back) {
        back.focus({ preventScroll: true });
        if (typeof back.setSelectionRange === "function") {
          try { back.setSelectionRange(back.value.length, back.value.length); } catch (e) {}
        }
        return;
      }
    }
    if (wasInPanel) {
      panel.setAttribute("tabindex", "-1");
      panel.focus({ preventScroll: true });
    }
  }

  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (!form.matches("[data-tx-form]")) return;
    ev.preventDefault();
    var params = new URLSearchParams(new FormData(form));
    loadTx(form.getAttribute("action") + "?" + params.toString());
  });

  document.addEventListener("click", function (ev) {
    var link = ev.target.closest &&
               ev.target.closest("a[data-tx-page], a[data-tx-sort]");
    if (!link) return;
    ev.preventDefault();
    if (link.getAttribute("aria-disabled") === "true") return;
    loadTx(link.getAttribute("href"));
  });

  /* Debounced live search, so typing filters without hitting Enter. */
  var timer = null;
  document.addEventListener("input", function (ev) {
    if (!ev.target.matches("[data-tx-form] input[type=search]")) return;
    clearTimeout(timer);
    var form = ev.target.closest("form");
    timer = setTimeout(function () {
      var params = new URLSearchParams(new FormData(form));
      loadTx(form.getAttribute("action") + "?" + params.toString());
    }, 220);
  });


  /* ------------------------------------ reclassification by drag-and-drop */
  /* The rows and the drop targets are already links and forms server-side;
     this only adds the pointer gesture. Every drop ends in a toast that names
     what changed and offers one-click undo, because a silent reclassification
     you cannot see is worse than no reclassification at all. */
  var dropbar = document.getElementById("dropbar");
  var toast = document.getElementById("toast");
  var dragged = null;

  function showToast(html, klass) {
    if (!toast) return;
    toast.className = "toast on" + (klass ? " " + klass : "");
    toast.innerHTML = html;
    clearTimeout(toast._timer);
    toast._timer = setTimeout(function () { toast.classList.remove("on"); }, 9000);
  }
  function hideToast() { if (toast) toast.classList.remove("on"); }

  document.addEventListener("dragstart", function (ev) {
    var tr = ev.target.closest && ev.target.closest("tr[draggable][data-key]");
    if (!tr) return;
    dragged = {
      key: tr.getAttribute("data-key"),
      label: tr.getAttribute("data-label"),
      category: tr.getAttribute("data-category")
    };
    tr.classList.add("dragging");
    ev.dataTransfer.effectAllowed = "copy";
    /* Some browsers refuse to start a drag without payload. */
    try { ev.dataTransfer.setData("text/plain", dragged.key); } catch (e) {}
    if (dropbar) { dropbar.classList.add("on"); dropbar.setAttribute("aria-hidden", "false"); }
    document.body.classList.add("dragging-row");
  });

  document.addEventListener("dragend", function () {
    dragged = null;
    document.querySelectorAll("tr.dragging").forEach(function (r) {
      r.classList.remove("dragging");
    });
    document.querySelectorAll(".dropzone.over").forEach(function (z) {
      z.classList.remove("over");
    });
    if (dropbar) { dropbar.classList.remove("on"); dropbar.setAttribute("aria-hidden", "true"); }
    document.body.classList.remove("dragging-row");
  });

  /* Anything that declares a target, so a row can be dropped on the palette at
     the bottom *or* straight onto the category bar or Need/Want/Save block it
     belongs in -- whichever is already under the pointer. */
  var DROPS = "[data-drop-category], [data-drop-bucket]";

  document.addEventListener("dragover", function (ev) {
    var zone = ev.target.closest && ev.target.closest(DROPS);
    if (!zone || !dragged) return;
    ev.preventDefault();
    ev.dataTransfer.dropEffect = "copy";
    zone.classList.add("over");
  });
  document.addEventListener("dragleave", function (ev) {
    var zone = ev.target.closest && ev.target.closest(DROPS);
    if (zone) zone.classList.remove("over");
  });

  document.addEventListener("drop", function (ev) {
    var zone = ev.target.closest && ev.target.closest(DROPS);
    if (!zone || !dragged) return;
    ev.preventDefault();
    ev.stopPropagation();
    zone.classList.remove("over");
    var target = {
      category: zone.getAttribute("data-drop-category") || "",
      bucket: zone.getAttribute("data-drop-bucket") || ""
    };
    /* Default to the merchant rule: it is what makes the fix permanent, and
       narrowing it to one row is a single click away in the toast. */
    apply(dragged, target, "merchant");
  });

  function apply(item, target, scope) {
    send("/api/reclassify", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({
        key: item.key, scope: scope,
        category: target.category, bucket: target.bucket
      })
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) { showToast("<b>Échec</b> " + esc(res.j.error || ""), "err"); return; }
        var j = res.j;
        var into = esc(j.bucket || j.category);
        var what = j.scope === "merchant"
          ? "<b>" + esc(j.match) + "</b> → " + into +
            " · " + j.count + " mouvement" + (j.count > 1 ? "s" : "") + " et les suivants"
          : "Ce mouvement → " + into;

        var actions = '<button data-undo>Annuler</button>';
        if (j.scope === "merchant") {
          actions = '<button data-narrow>Cette ligne seulement</button>' + actions;
        }
        showToast(what + '<span class="t-actions">' + actions + "</span>");

        toast.querySelector("[data-undo]").onclick = function () {
          undo(j.undo).then(function () { hideToast(); reloadView(); });
        };
        var narrow = toast.querySelector("[data-narrow]");
        if (narrow) {
          narrow.onclick = function () {
            /* Drop the merchant rule, then pin just this row. */
            undo(j.undo).then(function () { apply(item, target, "pin"); });
          };
        }
        reloadView();
      })
      .catch(function () { showToast("<b>Échec</b> requête impossible", "err"); });
  }

  function undo(payload) {
    return send("/api/reclassify/undo", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(payload)
    }).catch(function () {});
  }

  function reloadView() {
    /* Categories, buckets and totals all move when a rule changes, so the
       whole view is re-fetched rather than patched row by row. */
    swap(location.pathname + location.search, false);
  }

  /* ------------------------------------------------------------- refresh */
  /* Re-ingests inbox/ and then restarts the server process, so a session spent
     editing the backend is not served by the code that happened to be loaded at
     boot. The restart is only possible under the reloader; when it is not, the
     endpoint says so and this falls back to swapping <main> as before. */

  /* The old process answers /api/health right up to the moment it exits, so
     "the server responded" is not the signal to reload -- a changed PID is. */
  function waitForRestart(oldPid, tries) {
    if (tries > 60) {                       /* 60 x 250 ms = 15 s */
      showToast("<b>Le serveur n'est pas revenu</b> · relancez run.bat", "err");
      return;
    }
    setTimeout(function () {
      fetch("/api/health", { cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
        .then(function (h) {
          if (h.pid === oldPid) return waitForRestart(oldPid, tries + 1);
          location.reload();
        })
        .catch(function () { waitForRestart(oldPid, tries + 1); });
    }, 250);
  }

  function refreshMessage(j) {
    return j.added
      ? "<b>" + j.added + " nouveau" + (j.added > 1 ? "x" : "") + " mouvement" +
        (j.added > 1 ? "s" : "") + "</b> importé" + (j.added > 1 ? "s" : "") +
        " · " + j.movements + " au total"
      : "<b>Données à jour</b> · " + j.movements + " mouvements, " +
        j.overrides + " correction" + (j.overrides > 1 ? "s" : "");
  }

  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (!form.matches("[data-refresh]")) return;
    ev.preventDefault();
    var btn = document.getElementById("refreshBtn");
    if (btn) btn.classList.add("spin");
    send("/api/refresh", { method: "POST", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.error) {
          if (btn) btn.classList.remove("spin");
          showToast("<b>Échec du rechargement</b> " + esc(j.error), "err");
          return;
        }
        if (!j.restarting) {
          if (btn) btn.classList.remove("spin");
          showToast(refreshMessage(j));
          reloadView();
          return;
        }
        /* Keep spinning: the page is about to be replaced wholesale, because
           the templates and the Python behind them may both have moved. */
        showToast(refreshMessage(j) + " · <b>redémarrage du serveur…</b>");
        waitForRestart(j.pid, 0);
      })
      .catch(function () {
        if (btn) btn.classList.remove("spin");
        showToast("<b>Échec du rechargement</b>", "err");
      });
  });


  /* ------------------------------------------------- bulk reclassification */
  /* The form submits on its own without JavaScript. This adds the running
     count, the "whole filter" shortcut, and an undo -- reclassifying 315 rows
     with no way back would be a trap. */
  function bulkForm() { return document.getElementById("bulkForm"); }

  function picked() {
    return [].slice.call(document.querySelectorAll('input[name="keys"]:checked'));
  }

  function refreshBulk() {
    var form = bulkForm();
    if (!form) return;
    var all = document.getElementById("bulkAll");
    var count = picked().length;
    var whole = all && all.checked;
    var label = document.getElementById("bulkCount");

    if (label) {
      label.textContent = whole
        ? "tout le filtre"
        : count + " sélectionnée" + (count > 1 ? "s" : "");
    }
    form.classList.toggle("armed", whole || count > 0);

    document.querySelectorAll('input[name="keys"]').forEach(function (box) {
      box.closest("tr").classList.toggle("picked", box.checked);
    });
  }

  document.addEventListener("change", function (ev) {
    if (ev.target.id === "pickAll") {
      var on = ev.target.checked;
      document.querySelectorAll('input[name="keys"]').forEach(function (b) {
        b.checked = on;
      });
    }
    if (ev.target.name === "keys" || ev.target.id === "pickAll" ||
        ev.target.id === "bulkAll") {
      refreshBulk();
    }
  });

  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (form.id !== "bulkForm") return;
    ev.preventDefault();

    var data = new FormData(form);
    var payload = {
      from: data.get("from"), to: data.get("to"),
      q: data.get("q"), category: data.get("category"),
      bucket: data.get("bucket"), dir: data.get("dir"),
      to_category: data.get("to_category") || "",
      to_bucket: data.get("to_bucket") || "",
      apply_as: data.get("apply_as") || "pin",
      scope_all: !!data.get("scope_all"),
      keys: picked().map(function (b) { return b.value; })
    };

    send("/api/reclassify/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) { showToast("<b>Échec</b> " + esc(res.j.error || ""), "err"); return; }
        var j = res.j;
        var into = esc(j.bucket || j.category);
        var how = j.apply_as === "merchant"
          ? j.rules + " règle" + (j.rules > 1 ? "s" : "") + " sur " +
            j.merchants + " bénéficiaire" + (j.merchants > 1 ? "s" : "") +
            ", paiements futurs compris"
          : j.count + " épingle" + (j.count > 1 ? "s" : "");
        showToast("<b>" + j.count + " mouvement" + (j.count > 1 ? "s" : "") +
                  "</b> → " + into + " · " + how +
                  '<span class="t-actions"><button data-bulk-undo>Annuler</button></span>');
        toast.querySelector("[data-bulk-undo]").onclick = function () {
          send("/api/reclassify/bulk/undo", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Accept": "application/json" },
            body: JSON.stringify(j.undo)
          }).then(function () { hideToast(); reloadAfterBulk(); });
        };
        reloadAfterBulk();
      })
      .catch(function () { showToast("<b>Échec</b> requête impossible", "err"); });
  });

  function reloadAfterBulk() {
    /* On the dashboard the charts move too, so re-fetch the whole view; on the
       standalone transactions page only the panel exists. */
    if (document.getElementById("main")) {
      swap(location.pathname + location.search, false);
    } else {
      loadTx(location.pathname + location.search);
    }
  }

  refreshBulk();


  /* ------------------------------- selecting a date range on the timeline */
  /* An overlay injected by JavaScript, never present in the markup: without
     it the columns stay plain links, so the no-JavaScript path keeps working.
     A short press falls through to that link (drill down); a real drag selects
     the range it covered. */
  var BRUSH_MIN = 5;      /* px of movement before it counts as a drag */

  function wireBrush() {
    var payload = document.getElementById("chartData");
    var svg = document.getElementById("timelineChart");
    if (!payload || !svg || svg.dataset.brushWired) return;

    var data;
    try { data = JSON.parse(payload.textContent); } catch (e) { return; }
    var cfg = data.timeline;
    if (!cfg || !cfg.bands.length) return;
    svg.dataset.brushWired = "1";

    var NS = "http://www.w3.org/2000/svg";
    var band = document.createElementNS(NS, "rect");
    band.setAttribute("class", "brush");
    band.setAttribute("y", cfg.plot.y);
    band.setAttribute("height", cfg.plot.h);
    band.setAttribute("width", 0);
    band.style.display = "none";
    svg.appendChild(band);

    var overlay = document.createElementNS(NS, "rect");
    overlay.setAttribute("class", "brushlayer");
    overlay.setAttribute("x", cfg.plot.x);
    overlay.setAttribute("y", cfg.plot.y);
    overlay.setAttribute("width", cfg.plot.w);
    overlay.setAttribute("height", cfg.plot.h);
    svg.appendChild(overlay);

    var start = null;
    var hovered = null;

    function toUser(clientX) {
      var box = svg.getBoundingClientRect();
      return (clientX - box.left) * (cfg.width / box.width);
    }
    function bandAt(x) {
      for (var i = 0; i < cfg.bands.length; i++) {
        var b = cfg.bands[i];
        if (x >= b.x && x <= b.x + b.w) return i;
      }
      return x < cfg.bands[0].x ? 0 : cfg.bands.length - 1;
    }

    overlay.addEventListener("mousedown", function (ev) {
      if (ev.button !== 0) return;
      ev.preventDefault();
      start = { x: toUser(ev.clientX), clientX: ev.clientX };
    });

    /* The overlay sits above the columns, so their own mouseover never fires.
       Relay it: find the column under the pointer and show its tooltip, so
       adding the brush did not cost the hover detail. */
    overlay.addEventListener("mousemove", function (ev) {
      if (start) return;                       /* dragging: no tooltip */
      var index = bandAt(toUser(ev.clientX));
      var boxes = svg.querySelectorAll(".hitbox");
      var target = boxes[index];
      if (!target) return;
      if (target !== hovered) {
        hovered = target;
        place(target);
      }
    });
    overlay.addEventListener("mouseleave", function () {
      hovered = null;
      hide();
    });

    window.addEventListener("mousemove", function (ev) {
      if (!start) return;
      var x = toUser(ev.clientX);
      var lo = Math.min(start.x, x), hi = Math.max(start.x, x);
      band.setAttribute("x", lo);
      band.setAttribute("width", Math.max(hi - lo, 0));
      band.style.display = Math.abs(ev.clientX - start.clientX) > BRUSH_MIN ? "" : "none";
      hide();
      hovered = null;
    });

    window.addEventListener("mouseup", function (ev) {
      if (!start) return;
      var moved = Math.abs(ev.clientX - start.clientX);
      var from = bandAt(start.x), to = bandAt(toUser(ev.clientX));
      band.style.display = "none";
      var began = start;
      start = null;

      if (moved <= BRUSH_MIN) {
        /* Treat it as a click on that column: the overlay swallowed the one
           that would have reached the link underneath. Only drillable
           columns are links now, so find the column by its band index. */
        var link = svg.querySelector('a[data-band="' + from + '"]');
        if (link) {
          var href = link.getAttribute("href") || (link.href && link.href.baseVal);
          if (href) { window.location.href = href; }
        }
        return;
      }

      if (to < from) { var swap = from; from = to; to = swap; }
      var range = "?from=" + cfg.bands[from].from + "&to=" + cfg.bands[to].to + "&grain=auto";
      swapOrGo("/" + range);
    });
  }

  function swapOrGo(url) {
    if (document.getElementById("main")) { swap(url, true); window.scrollTo({ top: 0, behavior: "smooth" }); }
    else { window.location.href = url; }
  }

  wireBrush();
  wireCalendarRoving();

  /* ------------------------------------------------------------ shortcuts */
  /* The help lists gestures nobody finds by looking. Its button stays hidden
     in the markup: without JavaScript there is nothing for it to open. */
  var help = document.getElementById("shortcuts");
  var helpBtn = document.getElementById("helpBtn");
  function openHelp() {
    if (help && !help.open && typeof help.showModal === "function") {
      hide();
      help.showModal();
    }
  }
  if (help && helpBtn && typeof help.showModal === "function") {
    helpBtn.hidden = false;
    helpBtn.addEventListener("click", openHelp);
    /* A click on the backdrop closes it, like Escape does. */
    help.addEventListener("click", function (ev) {
      if (ev.target === help) help.close();
    });
  }

  /* The Twint triage: 1-9 pick a category, S skips, Z undoes the last one.
     Each maps onto a real button or link, so the page does the same without
     JavaScript. One action per row: a second key pressed before the next
     row arrives would otherwise post against the one just classified. The
     guard is the pressed element itself -- the swap replaces it, so the next
     row is free without anyone having to reset a flag. */
  var triagePressed = null;
  function triageKey(ev) {
    if (!document.querySelector("[data-triage]")) return false;
    if (ev.altKey || ev.ctrlKey || ev.metaKey) return false;
    var target = null;
    if (/^[1-9]$/.test(ev.key)) {
      target = document.querySelector('button[data-key="' + ev.key + '"]');
    } else if (ev.key === "s" || ev.key === "S") {
      target = document.querySelector("a[data-skip]:not([hidden])");
    } else if (ev.key === "z" || ev.key === "Z") {
      target = document.querySelector("button[data-undo]");
    }
    if (!target) return false;
    ev.preventDefault();
    if (!(triagePressed && document.contains(triagePressed))) {
      triagePressed = target;
      target.click();
    }
    return true;
  }

  document.addEventListener("keydown", function (ev) {
    if (ev.target.matches("input, select, textarea")) return;
    /* An open dialog owns the keyboard: Escape closes it, it does not climb
       the breadcrumb behind it. */
    if (help && help.open) return;
    if (ev.key === "?" && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
      ev.preventDefault();
      openHelp();
      return;
    }
    if (triageKey(ev)) return;
    var crumbs = document.querySelectorAll(".crumbs a");
    if (ev.key === "Escape" && crumbs.length) {
      /* Escape climbs one level out of the current drill-down. */
      crumbs[crumbs.length - 1].click();
      return;
    }
    if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
    /* Alt+← is the browser's own back; a modified arrow is never ours. */
    if (ev.altKey || ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
    /* The calendar owns its arrows (roving tabindex between days). Anywhere
       else they are the page's: they used to go dead as soon as a link or a
       button had focus -- that is, after almost any click -- and a link does
       nothing with an arrow key anyway. */
    if (ev.target.closest && ev.target.closest("svg, [role='tablist'], [role='listbox']")) {
      return;
    }
    if (!document.querySelector(".crumbs .nav-arrow")) return;
    ev.preventDefault();
    var side = ev.key === "ArrowLeft" ? "prev" : "next";
    settled.then(function () {
      var arrow = document.querySelector("a.nav-arrow." + side);
      if (arrow) arrow.click();
    });
  });
})();
