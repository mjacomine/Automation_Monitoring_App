"""HTML trending-analysis reporting backend.

Renders a self-contained, interactive "Trending Analysis" page from the same
per-job records the dashboard already embeds (Organization, State, ErrorDate).
All trend math runs client-side in vanilla JS — no charting library, no server
round-trip — so the page stays a dependency-free static file like the rest of
the app. This backend is read-only: it consumes records produced by the
existing read path and performs presentation-layer aggregation only.

Two reports:
  1. Organization vs. all-clients benchmark — monthly success-rate trend for a
     selected organization plotted against the benchmark (mean of the
     per-organization monthly success rates).
  2. Period-over-period success rate — a selected organization's monthly
     success rate in a recent period vs a historical period, with the delta.

Colours come from the shared brand design tokens: primary green for the
selected organization / recent period, secondary slate for the benchmark, and
gold as the comparison-period accent.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

# --- Page styling ----------------------------------------------------------
_CSS = ""  # styling moved to shared styles.css (single source of truth)


# --- Client-side trend computation + SVG charts ----------------------------
# Reads the RECORDS constant (per-job rows: o=org, s=state, d=YYYY-MM-DD)
# emitted above it. All aggregation is presentation-layer and read-only.
_TRENDS_JS = """
const $ = function (id) { return document.getElementById(id); };
const MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function distinct(a) {
  return Array.from(new Set(a.filter(function (v) { return v != null && v !== ""; })));
}
function monthKey(d) { return d ? d.slice(0, 7) : ""; }
function monthLabel(k) {
  var p = k.split("-");
  return MONTHS_ABBR[parseInt(p[1], 10) - 1] + " " + p[0];
}

// Populated by initTrends() once RECORDS arrives from the live fetch.
var ALL_MONTHS = [];
var ORGS = [];

// monthKey -> {s: successCount, t: total}
function monthlyAgg(records) {
  var m = {};
  records.forEach(function (r) {
    var k = monthKey(r.d); if (!k) return;
    if (!m[k]) m[k] = { s: 0, t: 0 };
    m[k].t++; if (r.s === "Successful") m[k].s++;
  });
  return m;
}
function orgRecords(org) {
  return RECORDS.filter(function (r) { return r.o === org; });
}
function avg(arr) {
  var v = arr.filter(function (x) { return x != null && !isNaN(x); });
  return v.length ? v.reduce(function (a, b) { return a + b; }, 0) / v.length : null;
}
function pad(arr, k) { var o = arr.slice(); while (o.length < k) o.push(null); return o; }
function fmtPct(x) { return x == null ? "\\u2014" : x.toFixed(1) + "%"; }

// --- Reusable inline SVG line chart ---------------------------------------
function buildLineChart(cats, series, opts) {
  opts = opts || {};
  var W = 760, H = 320, padL = 48, padR = 16, padT = 16, padB = 46;
  var plotW = W - padL - padR, plotH = H - padT - padB, n = cats.length;
  var yMax = opts.yMax || 100;
  function xAt(i) { return n <= 1 ? padL + plotW / 2 : padL + (i / (n - 1)) * plotW; }
  function yAt(v) { return padT + (1 - v / yMax) * plotH; }

  var svg = '<svg viewBox="0 0 ' + W + ' ' + H +
    '" preserveAspectRatio="xMidYMid meet" role="img" aria-label="' +
    esc(opts.aria || "Trend chart") + '" class="chart">';
  [0, 25, 50, 75, 100].forEach(function (g) {
    var y = yAt(g);
    svg += '<line class="grid" x1="' + padL + '" y1="' + y + '" x2="' +
      (W - padR) + '" y2="' + y + '"></line>';
    svg += '<text class="axis-label" x="' + (padL - 8) + '" y="' + (y + 4) +
      '" text-anchor="end">' + g + "%</text>";
  });
  cats.forEach(function (c, i) {
    svg += '<text class="axis-label" x="' + xAt(i) + '" y="' + (H - padB + 20) +
      '" text-anchor="middle">' + esc(c) + "</text>";
  });
  series.forEach(function (s) {
    var pts = [];
    s.values.forEach(function (v, i) {
      if (v != null && !isNaN(v)) pts.push([xAt(i), yAt(v), i, v]);
    });
    if (pts.length > 1) {
      svg += '<polyline class="line' + (s.dashed ? " dashed" : "") +
        '" style="stroke:' + s.color + '" points="' +
        pts.map(function (p) { return p[0] + "," + p[1]; }).join(" ") + '"></polyline>';
    }
    pts.forEach(function (p) {
      var lbl = (s.labels && s.labels[p[2]]) ? s.labels[p[2]] : cats[p[2]];
      svg += '<circle class="marker" cx="' + p[0] + '" cy="' + p[1] +
        '" r="4" style="fill:' + s.color + '"><title>' + esc(s.name) +
        " \\u2014 " + esc(lbl) + ": " + p[3].toFixed(1) + "%</title></circle>";
    });
  });
  svg += "</svg>";
  return svg;
}
function legendHTML(series) {
  return series.map(function (s) {
    return '<span class="legend-item"><span class="swatch ' +
      (s.dashed ? "dashed" : "solid") + '" style="border-top-color:' + s.color +
      '"></span>' + esc(s.name) + "</span>";
  }).join("");
}
function emptyMsg(msg) {
  return '<div class="chart-empty">' + esc(msg || "No data for this selection.") + "</div>";
}

// --- Report 1: organization vs all-clients benchmark ----------------------
function benchmarkValues() {
  var byOrg = {};
  ORGS.forEach(function (o) { byOrg[o] = monthlyAgg(orgRecords(o)); });
  return ALL_MONTHS.map(function (k) {
    var rates = [];
    ORGS.forEach(function (o) {
      var a = byOrg[o][k]; if (a && a.t > 0) rates.push(a.s / a.t * 100);
    });
    if (!rates.length) return null;
    return rates.reduce(function (x, y) { return x + y; }, 0) / rates.length;
  });
}
function orgValues(org) {
  var a = monthlyAgg(orgRecords(org));
  return ALL_MONTHS.map(function (k) { var x = a[k]; return (x && x.t > 0) ? x.s / x.t * 100 : null; });
}
// Default to the organization with the most dated records, so the initial
// view shows a real trend line rather than landing on an org with no dates.
function bestOrg() {
  var best = ORGS[0], bestN = -1;
  ORGS.forEach(function (o) {
    var n = RECORDS.filter(function (r) { return r.o === o && r.d; }).length;
    if (n > bestN) { bestN = n; best = o; }
  });
  return best;
}
function renderReport1() {
  if (!ALL_MONTHS.length) {
    $("r1-chart").innerHTML = emptyMsg(); $("r1-legend").innerHTML = "";
    $("r1-note").innerHTML = ""; return;
  }
  var org = $("r1-org").value;
  var ov = orgValues(org);
  var cats = ALL_MONTHS.map(monthLabel);
  var series = [
    { name: org, color: "var(--brand)", dashed: false, values: ov },
    { name: "All-clients benchmark", color: "var(--slate-600)", dashed: true, values: benchmarkValues() }
  ];
  $("r1-chart").innerHTML = buildLineChart(cats, series,
    { aria: "Monthly success rate: " + org + " versus all-clients benchmark" });
  $("r1-legend").innerHTML = legendHTML(series);
  var hasData = ov.some(function (v) { return v != null; });
  $("r1-note").innerHTML = hasData ? "" :
    '<div class="chart-note">No dated jobs for ' + esc(org) +
    " \\u2014 this organization has no error dates to plot, so only the " +
    "benchmark is shown.</div>";
}

// --- Report 2: period over period -----------------------------------------
function precedingMonths(startKey, n) {
  var idx = ALL_MONTHS.indexOf(startKey);
  if (idx < 0) idx = ALL_MONTHS.length;
  return ALL_MONTHS.slice(Math.max(0, idx - n), idx);
}
function monthsInRange(fromStr, toStr) {
  if (!ALL_MONTHS.length) return [];
  var f = fromStr ? fromStr.slice(0, 7) : ALL_MONTHS[0];
  var t = toStr ? toStr.slice(0, 7) : ALL_MONTHS[ALL_MONTHS.length - 1];
  return ALL_MONTHS.filter(function (k) { return k >= f && k <= t; });
}
function recentMonths() {
  var p = $("r2-recent-preset").value;
  if (p === "custom") return monthsInRange($("r2-recent-from").value, $("r2-recent-to").value);
  return ALL_MONTHS.slice(-(parseInt(p, 10) || 3));
}
function historicalMonths(recent) {
  var p = $("r2-hist-preset").value;
  if (p === "custom") return monthsInRange($("r2-hist-from").value, $("r2-hist-to").value);
  var start = recent.length ? recent[0] : ALL_MONTHS[ALL_MONTHS.length - 1];
  return precedingMonths(start, parseInt(p, 10) || 3);
}
function ratesForMonths(org, months) {
  var a = monthlyAgg(orgRecords(org));
  return months.map(function (k) { var x = a[k]; return (x && x.t > 0) ? x.s / x.t * 100 : null; });
}
function rangeLabel(months) {
  if (!months.length) return "no data";
  return months.length === 1 ? monthLabel(months[0])
    : monthLabel(months[0]) + " \\u2013 " + monthLabel(months[months.length - 1]);
}
function deltaHTML(rA, hA, rM, hM) {
  var html = '<div class="delta-grid">';
  html += '<div class="delta-stat"><div class="delta-k">Recent avg</div><div class="delta-v">' +
    fmtPct(rA) + '</div><div class="delta-sub">' + esc(rangeLabel(rM)) + "</div></div>";
  html += '<div class="delta-stat"><div class="delta-k">Historical avg</div><div class="delta-v">' +
    fmtPct(hA) + '</div><div class="delta-sub">' + esc(rangeLabel(hM)) + "</div></div>";
  if (rA != null && hA != null) {
    var d = rA - hA;
    var dir = d > 0.05 ? "up" : (d < -0.05 ? "down" : "flat");
    var arrow = dir === "up" ? "\\u25b2" : (dir === "down" ? "\\u25bc" : "\\u2192");
    html += '<div class="delta-stat"><div class="delta-k">Change</div><div class="delta-v delta ' +
      dir + '">' + arrow + " " + (d >= 0 ? "+" : "") + d.toFixed(1) +
      ' pts</div><div class="delta-sub">recent vs historical</div></div>';
  } else {
    html += '<div class="delta-stat"><div class="delta-k">Change</div>' +
      '<div class="delta-v delta flat">\\u2014</div>' +
      '<div class="delta-sub">insufficient data</div></div>';
  }
  return html + "</div>";
}
function syncCustomVisibility() {
  $("r2-recent-custom").hidden = $("r2-recent-preset").value !== "custom";
  $("r2-hist-custom").hidden = $("r2-hist-preset").value !== "custom";
}
function renderReport2() {
  syncCustomVisibility();
  var org = $("r2-org").value;
  var rM = recentMonths(), hM = historicalMonths(rM);
  if (!org || (!rM.length && !hM.length)) {
    $("r2-chart").innerHTML = emptyMsg("No data for the selected periods.");
    $("r2-legend").innerHTML = ""; $("r2-delta").innerHTML = "";
    return;
  }
  var k = Math.max(rM.length, hM.length);
  var cats = []; for (var i = 0; i < k; i++) cats.push("Month " + (i + 1));
  var rRates = ratesForMonths(org, rM), hRates = ratesForMonths(org, hM);
  var series = [
    { name: "Recent", color: "var(--brand)", dashed: false,
      values: pad(rRates, k), labels: pad(rM.map(monthLabel), k) },
    { name: "Comparison (historical)", color: "var(--gold-700)", dashed: true,
      values: pad(hRates, k), labels: pad(hM.map(monthLabel), k) }
  ];
  $("r2-delta").innerHTML = deltaHTML(avg(rRates), avg(hRates), rM, hM);
  $("r2-chart").innerHTML = buildLineChart(cats, series,
    { aria: "Success rate by period position, recent vs historical, for " + org });
  $("r2-legend").innerHTML = legendHTML(series);
}

function fillSelect(sel, values, selected) {
  sel.innerHTML = values.map(function (v) {
    return '<option value="' + esc(v) + '"' + (v === selected ? " selected" : "") +
      ">" + esc(v) + "</option>";
  }).join("");
}

// Called by the auth/fetch bootstrap once RECORDS is populated from the live,
// RLS-filtered Supabase query.
function initTrends() {
  try {
    ALL_MONTHS = distinct(RECORDS.map(function (r) { return monthKey(r.d); })).sort();
    ORGS = distinct(RECORDS.map(function (r) { return r.o; })).sort();
    if (!ORGS.length || !ALL_MONTHS.length) {
      ["r1-chart", "r2-chart"].forEach(function (id) {
        $(id).innerHTML = emptyMsg("No trend data available yet.");
      });
      return;
    }
    var defaultOrg = bestOrg();
    fillSelect($("r1-org"), ORGS, defaultOrg);
    fillSelect($("r2-org"), ORGS, defaultOrg);

    var first = ALL_MONTHS[0] + "-01";
    var last = ALL_MONTHS[ALL_MONTHS.length - 1] + "-28";
    $("r2-recent-from").value = ALL_MONTHS[Math.max(0, ALL_MONTHS.length - 3)] + "-01";
    $("r2-recent-to").value = last;
    $("r2-hist-from").value = ALL_MONTHS[Math.max(0, ALL_MONTHS.length - 6)] + "-01";
    $("r2-hist-to").value = ALL_MONTHS[Math.max(0, ALL_MONTHS.length - 4)] + "-28";
    ["r2-recent-from", "r2-recent-to", "r2-hist-from", "r2-hist-to"].forEach(function (id) {
      $(id).min = first; $(id).max = last;
    });

    $("r1-org").addEventListener("change", renderReport1);
    ["r2-org", "r2-recent-preset", "r2-hist-preset",
     "r2-recent-from", "r2-recent-to", "r2-hist-from", "r2-hist-to"].forEach(function (id) {
      $(id).addEventListener("change", renderReport2);
    });

    renderReport1();
    renderReport2();
  } catch (e) {
    ["r1-chart", "r2-chart"].forEach(function (id) {
      var el = $(id);
      if (el) el.innerHTML = '<div class="chart-empty">Unable to render charts: ' +
        esc(e.message) + "</div>";
    });
  }
}
"""

# --- Auth gate + live, RLS-filtered data fetch ----------------------------
_TRENDS_BOOTSTRAP = """
(async function () {
  var sb = supabase.createClient(window.SUPABASE_URL, window.SUPABASE_ANON_KEY);
  var session = (await sb.auth.getSession()).data.session;
  if (!session) { location.href = "login.html"; return; }
  var so = document.getElementById("signout");
  if (so) so.addEventListener("click", async function () {
    await sb.auth.signOut(); location.href = "login.html";
  });
  try {
    var orgs = {};
    var orgRes = await sb.from("d_organizations").select("organization_id, organization_name");
    if (orgRes.error) throw orgRes.error;
    (orgRes.data || []).forEach(function (o) { orgs[o.organization_id] = o.organization_name; });

    var rows = [], from = 0, PAGE = 1000;
    while (true) {
      var res = await sb.from("f_auto_metrics_jobs")
        .select("organization_id, job_state, error_datetime")
        .range(from, from + PAGE - 1);
      if (res.error) throw res.error;
      rows = rows.concat(res.data);
      if (res.data.length < PAGE) break;
      from += PAGE;
    }
    RECORDS = rows.map(function (r) {
      return {
        o: orgs[r.organization_id] || r.organization_id,
        s: r.job_state,
        d: r.error_datetime ? String(r.error_datetime).slice(0, 10) : null
      };
    });
    var stamp = document.getElementById("refresh-stamp");
    if (stamp) stamp.textContent = new Date().toLocaleString();
    initTrends();
  } catch (e) {
    ["r1-chart", "r2-chart"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.innerHTML = '<div class="chart-empty">Could not load data: ' +
        (e.message || e) + "</div>";
    });
  }
})();
"""


def render_trends(generated_at: datetime | None = None) -> str:
    """Build the authenticated Trending Analysis HTML shell.

    The page embeds NO data: on load it requires a Supabase session and fetches
    only the rows the signed-in user may see (enforced by RLS), then computes
    the trends client-side.

    Args:
        generated_at: Timestamp to stamp on the page shell (defaults to now).
    """
    stamp = (generated_at or datetime.now()).strftime("%B %d, %Y at %I:%M %p")

    head = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Trending Analysis</title>\n"
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">\n'
        '<link rel="stylesheet" href="styles.css">\n'
        "</head>\n"
        "<body>\n"
        '  <header class="appbar">\n'
        '    <div class="appbar-inner">\n'
        '      <div class="brand"><span class="brand-mark"></span>'
        "RPA Operations</div>\n"
        '      <nav class="appbar-nav">\n'
        '        <a href="index.html">Home</a>\n'
        '        <a href="dashboard.html">Dashboard</a>\n'
        '        <a href="trends.html" aria-current="page">Trending</a>\n'
        '        <a href="admin.html">Admin</a>\n'
        '        <button type="button" id="signout">Sign out</button>\n'
        "      </nav>\n"
        "    </div>\n"
        "  </header>\n"
        '  <main class="wrap">\n'
        '    <div class="page-head">\n'
        "      <h1>Trending Analysis</h1>\n"
        f'      <div class="sub">Last Refreshed <span id="refresh-stamp">'
        f"{escape(stamp)}</span> &nbsp;&bull;&nbsp; "
        "Monthly success-rate trends</div>\n"
        "    </div>\n"
    )

    report1 = (
        '\n    <section class="card" aria-label="Organization vs all-clients benchmark">\n'
        '      <div class="card-head">\n'
        "        <h2>Organization vs. All-Clients Benchmark</h2>\n"
        '        <p class="card-note">Monthly success rate. Benchmark = mean of '
        "per-organization monthly success rates.</p>\n"
        "      </div>\n"
        '      <div class="controls">\n'
        '        <div class="field">\n'
        '          <label for="r1-org">Organization</label>\n'
        '          <select id="r1-org"></select>\n'
        "        </div>\n"
        "      </div>\n"
        '      <div id="r1-chart" class="chart-wrap"></div>\n'
        '      <div id="r1-legend" class="legend-row"></div>\n'
        '      <div id="r1-note"></div>\n'
        "    </section>\n"
    )

    report2 = (
        '\n    <section class="card" aria-label="Period over period success rate">\n'
        '      <div class="card-head">\n'
        "        <h2>Period-over-Period Success Rate</h2>\n"
        '        <p class="card-note">A selected organization&rsquo;s monthly '
        "success rate in a recent period vs a historical period.</p>\n"
        "      </div>\n"
        '      <div class="controls">\n'
        '        <div class="field">\n'
        '          <label for="r2-org">Organization</label>\n'
        '          <select id="r2-org"></select>\n'
        "        </div>\n"
        '        <div class="field">\n'
        '          <label for="r2-recent-preset">Recent period</label>\n'
        '          <select id="r2-recent-preset">\n'
        '            <option value="3" selected>Last 3 months</option>\n'
        '            <option value="6">Last 6 months</option>\n'
        '            <option value="custom">Custom&hellip;</option>\n'
        "          </select>\n"
        '          <div id="r2-recent-custom" class="custom-range" hidden>\n'
        '            <input type="date" id="r2-recent-from" aria-label="Recent period start">\n'
        "            <span>to</span>\n"
        '            <input type="date" id="r2-recent-to" aria-label="Recent period end">\n'
        "          </div>\n"
        "        </div>\n"
        '        <div class="field">\n'
        '          <label for="r2-hist-preset">Comparison period</label>\n'
        '          <select id="r2-hist-preset">\n'
        '            <option value="3" selected>Previous 3 months</option>\n'
        '            <option value="6">Previous 6 months</option>\n'
        '            <option value="custom">Custom&hellip;</option>\n'
        "          </select>\n"
        '          <div id="r2-hist-custom" class="custom-range" hidden>\n'
        '            <input type="date" id="r2-hist-from" aria-label="Comparison period start">\n'
        "            <span>to</span>\n"
        '            <input type="date" id="r2-hist-to" aria-label="Comparison period end">\n'
        "          </div>\n"
        "        </div>\n"
        "      </div>\n"
        '      <div id="r2-delta"></div>\n'
        '      <div id="r2-chart" class="chart-wrap"></div>\n'
        '      <div id="r2-legend" class="legend-row"></div>\n'
        "    </section>\n"
    )

    footer = (
        "\n    <footer>UiPath Orchestrator &mdash; Automated reporting</footer>\n"
        "  </main>\n"
    )

    data_script = (
        '  <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2">'
        "</script>\n"
        '  <script src="app-config.js"></script>\n'
        "  <script>\n"
        "var RECORDS = [];\n"
        + _TRENDS_JS
        + _TRENDS_BOOTSTRAP
        + "  </script>\n"
    )

    return head + report1 + report2 + footer + data_script + "</body>\n</html>"
