"""HTML dashboard reporting backend.

Renders a :class:`~monitoring.analytics.JobAnalysis` into a self-contained,
executive-style HTML page with KPI cards and a colour-coded success matrix.
Presentation concerns (colours, layout, copy) live here and nowhere else.

The page is interactive: the per-job rows are embedded as JSON and the KPIs and
success matrix are (re)computed client-side, so the Organization and Error Date
filters re-aggregate the view without a server round-trip. The JavaScript
aggregation mirrors :func:`~monitoring.analytics.analyze_jobs`.

Both filters share one collapsible, multi-select checkbox control: Organization
is a flat checkbox list, Error Date a Year > Month > Day tree. Visual design
uses CSS custom properties (design tokens) built from the brand palette —
forest green (primary), slate blue (secondary), warm gold (accent) — plus a
neutral gray scale, so colours are defined once in ``:root`` and reused.
"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape

from ..analytics import JobAnalysis


# --- Page styling ----------------------------------------------------------
# Design tokens in :root derive every colour from the three brand hues plus a
# neutral scale; components reference the tokens so the palette is single-source.
_CSS = """
  :root {
    /* Brand */
    --brand: #467958;       /* primary  - forest green */
    --brand-600: #3c6a4d;   /* hover / darker */
    --brand-700: #2f5540;   /* darkest */
    --brand-050: #eef3ef;   /* light green tint */
    --slate: #82A2B1;       /* secondary - slate blue */
    --slate-600: #5e8090;
    --slate-700: #41606d;   /* dark slate for header fills (AA) */
    --slate-050: #eef3f5;
    --gold: #D4A842;        /* tertiary - warm gold accent */
    --gold-600: #a87f23;    /* gold text on light (AA) */
    --gold-050: #faf2dc;

    /* Neutrals */
    --canvas: #eef1ef;      /* app background */
    --surface: #ffffff;     /* cards */
    --surface-2: #f6f8f7;   /* zebra stripe */
    --border: #e3e8e6;
    --text: #1f2a30;
    --text-muted: #5b6970;
    --on-brand: #ffffff;

    /* Semantic status (AA on white) */
    --ok: #2e7d50;
    --ok-strong: #246b45;   /* badge fill for white text */
    --risk: #c0392b;

    /* Effects */
    --radius: 14px;
    --radius-sm: 9px;
    --shadow: 0 1px 2px rgba(16,24,32,.05), 0 8px 24px rgba(16,24,32,.08);
    --shadow-sm: 0 1px 3px rgba(16,24,32,.12);
    --ring: 0 0 0 3px rgba(70,121,88,.35);
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    background: var(--canvas);
    color: var(--text);
    line-height: 1.5;
  }

  a:focus-visible, button:focus-visible, select:focus-visible,
  input:focus-visible {
    outline: none; box-shadow: var(--ring);
  }

  /* Top app bar */
  .appbar {
    position: sticky; top: 0; z-index: 50;
    background: var(--brand); color: var(--on-brand);
    box-shadow: var(--shadow-sm);
  }
  .appbar-inner {
    max-width: 1100px; margin: 0 auto; padding: 14px 24px;
    display: flex; align-items: center; justify-content: space-between;
  }
  .brand {
    display: flex; align-items: center; gap: 10px;
    font-size: 16px; font-weight: 700; letter-spacing: .3px;
  }
  .brand-mark {
    width: 14px; height: 14px; border-radius: 4px; background: var(--gold);
    box-shadow: 0 0 0 3px rgba(212,168,66,.25);
  }
  .appbar-nav a {
    color: var(--on-brand); text-decoration: none;
    font-size: 14px; font-weight: 600; opacity: .92;
    padding: 6px 12px; border-radius: 999px;
  }
  .appbar-nav a:hover { background: rgba(255,255,255,.15); opacity: 1; }
  .appbar-nav a:focus-visible { box-shadow: 0 0 0 3px rgba(255,255,255,.7); }

  /* Layout */
  .wrap { max-width: 1100px; margin: 0 auto; padding: 32px 24px 48px; }
  .page-head { margin-bottom: 24px; }
  .page-head h1 {
    font-size: 24px; font-weight: 700; color: var(--text); letter-spacing: .2px;
  }
  .sub { color: var(--text-muted); font-size: 13.5px; margin-top: 6px; }

  /* Filter bar */
  .filters {
    display: flex; gap: 18px; flex-wrap: wrap; align-items: flex-end;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 18px 20px;
    box-shadow: var(--shadow); margin-bottom: 24px;
  }
  .filters .field { display: flex; flex-direction: column; gap: 6px; }
  .filters label {
    font-size: 11.5px; text-transform: uppercase; letter-spacing: .8px;
    color: var(--text-muted); font-weight: 700;
  }
  .result-count {
    margin-left: auto; align-self: center;
    color: var(--text-muted); font-size: 13px; font-weight: 600;
    background: var(--slate-050); border: 1px solid var(--border);
    padding: 6px 12px; border-radius: 999px;
  }

  /* Collapsible multi-select checkbox filter (Organization + Error Date) */
  .cbf { position: relative; }
  .cbf-button {
    font-family: inherit; font-size: 14px; padding: 10px 12px;
    border: 1px solid var(--border); border-radius: var(--radius-sm);
    background: var(--surface); color: var(--text);
    min-width: 220px; cursor: pointer; text-align: left;
    display: inline-flex; justify-content: space-between; align-items: center;
    gap: 8px;
  }
  .cbf-button:hover { border-color: var(--slate); }
  .cbf-caret { color: var(--text-muted); font-size: 12px; }
  .cbf-panel {
    position: absolute; z-index: 30; top: calc(100% + 6px); left: 0;
    width: 280px; max-height: 340px; overflow-y: auto;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius-sm); box-shadow: var(--shadow); padding: 6px;
  }
  .cbf-panel[hidden] { display: none; }
  .tree-row {
    display: flex; align-items: center; gap: 8px; padding: 7px 8px;
    border-radius: 7px; cursor: pointer; font-size: 14px; color: var(--text);
    white-space: nowrap;
  }
  .tree-row:hover { background: var(--brand-050); }
  .tree-row.selected {
    background: var(--gold-050); color: var(--gold-600); font-weight: 700;
  }
  .tree-children { padding-left: 18px; }
  .caret { width: 14px; text-align: center; color: var(--text-muted); font-size: 11px; }
  .caret-spacer { width: 14px; display: inline-block; }
  .tree-check {
    accent-color: var(--brand); width: 15px; height: 15px; cursor: pointer;
    flex: none;
  }
  .check-spacer { width: 15px; display: inline-block; }

  /* KPI cards */
  .kpis {
    display: grid; grid-template-columns: repeat(5, 1fr);
    gap: 16px; margin-bottom: 24px;
  }
  .kpi {
    background: var(--surface); border: 1px solid var(--border);
    border-top: 3px solid var(--slate); border-radius: var(--radius);
    padding: 18px 20px; box-shadow: var(--shadow);
  }
  .kpi .label {
    font-size: 11.5px; text-transform: uppercase; letter-spacing: .8px;
    color: var(--text-muted); font-weight: 700;
  }
  .kpi .value {
    font-size: 30px; font-weight: 800; margin-top: 8px;
    color: var(--text); letter-spacing: -.5px;
  }
  .kpi-hero {
    border-top-color: var(--gold);
    background: linear-gradient(180deg, var(--gold-050), var(--surface) 62%);
  }
  .kpi-hero .value { font-size: 38px; }
  .value.ok { color: var(--ok); }
  .value.risk { color: var(--risk); }

  /* Success matrix */
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow);
  }
  .table-scroll { overflow: auto; max-height: 72vh; }
  table { width: 100%; border-collapse: collapse; }
  thead th {
    position: sticky; top: 0; z-index: 1;
    background: var(--slate-700); color: #ffffff; text-align: right;
    padding: 13px 16px; font-size: 11.5px; text-transform: uppercase;
    letter-spacing: .6px; font-weight: 700;
  }
  thead th:first-child { text-align: left; }
  tbody td {
    padding: 13px 16px; border-bottom: 1px solid var(--border);
    font-size: 14.5px; text-align: right;
  }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr:nth-child(even) { background: var(--surface-2); }
  tbody tr:hover { background: var(--brand-050); }
  td.name { text-align: left; font-weight: 600; color: var(--text); }
  td.num { color: var(--text-muted); font-variant-numeric: tabular-nums; }
  td.total { font-weight: 700; color: var(--text); }
  td.pct { font-weight: 700; font-variant-numeric: tabular-nums; }
  td.pct.ok { color: var(--ok); }
  td.pct.risk { color: var(--risk); }
  .empty-row {
    padding: 22px 16px !important; text-align: center !important;
    color: var(--text-muted); font-size: 14px;
  }
  .dot {
    display: inline-block; width: 9px; height: 9px; border-radius: 50%;
    margin-right: 7px; vertical-align: middle;
  }
  .dot.ok { background: var(--ok); }
  .dot.risk { background: var(--risk); }
  .badge {
    display: inline-block; color: #fff; font-size: 11px; font-weight: 700;
    padding: 4px 10px; border-radius: 999px; text-transform: uppercase;
    letter-spacing: .5px; white-space: nowrap;
  }
  .badge.ok { background: var(--ok-strong); }
  .badge.risk { background: var(--risk); }

  /* Legend */
  .legend {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 16px 20px;
    box-shadow: var(--shadow); margin-top: 18px;
  }
  .legend-title {
    font-size: 11.5px; text-transform: uppercase; letter-spacing: .8px;
    font-weight: 700; color: var(--text-muted); margin-bottom: 12px;
  }
  .legend-items {
    display: flex; gap: 24px; font-size: 13px; align-items: center;
    color: var(--text); flex-wrap: wrap;
  }
  .legend .dot { width: 11px; height: 11px; }

  footer {
    color: var(--text-muted); font-size: 12px; margin-top: 24px;
    text-align: center;
  }

  @media (max-width: 860px) {
    .kpis { grid-template-columns: repeat(2, 1fr); }
    .kpi-hero { grid-column: span 2; }
  }
  @media (max-width: 520px) {
    .kpis { grid-template-columns: 1fr; }
    .kpi-hero { grid-column: span 1; }
    .filters .field, .cbf-button { width: 100%; min-width: 0; }
  }
  @media (prefers-reduced-motion: reduce) {
    * { transition: none !important; scroll-behavior: auto !important; }
  }
"""


# --- Client-side aggregation + filtering -----------------------------------
# Mirrors analytics.analyze_jobs: group by ReleaseName, count by State, derive
# success % and health against THRESHOLD. Reads the RECORDS / STATES / THRESHOLD
# constants emitted just above it in the page.
#
# Both filters are multi-select checkbox controls sharing one setup routine:
#   * Organization - a flat checkbox list; a row matches if its org is in the
#     selected set (empty set = all).
#   * Error Date - a Year > Month > Day tree; each checked box contributes a
#     date prefix ("YYYY", "YYYY-MM", or "YYYY-MM-DD") and a row matches if its
#     date starts with ANY selected prefix (the union; empty = all).
#
# Status colour is applied via CSS classes (ok / risk) so the palette stays in
# the design tokens; the healthy/at-risk decision itself is unchanged.
_DASHBOARD_JS = """
const $ = function (id) { return document.getElementById(id); };
const MONTHS = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];

var selectedOrgs = [];   // checked organization codes
var selectedDates = [];  // checked prefixes: "YYYY" | "YYYY-MM" | "YYYY-MM-DD"

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function distinct(values) {
  return Array.from(new Set(values.filter(function (v) {
    return v != null && v !== "";
  })));
}

function checkedValues(panelId) {
  var boxes = $(panelId).querySelectorAll(".tree-check");
  var out = [];
  Array.prototype.forEach.call(boxes, function (b) {
    if (b.checked) out.push(b.getAttribute("data-value"));
  });
  return out;
}

function dateLabel(prefix) {
  if (!prefix) return "All Dates";
  var p = prefix.split("-");
  if (p.length === 1) return p[0];
  if (p.length === 2) return MONTHS[parseInt(p[1], 10) - 1] + " " + p[0];
  return p[1] + "/" + p[2] + "/" + p[0];  // MM/dd/yyyy
}

function renderOrgList(orgs) {
  var html = "";
  orgs.forEach(function (o) {
    html += '<div class="tree-row">' +
      '<input type="checkbox" class="tree-check" data-value="' + esc(o) + '">' +
      '<span class="tree-label">' + esc(o) + "</span></div>";
  });
  return html;
}

function buildDateTree(dates) {
  // year -> { month("YYYY-MM") -> [ "YYYY-MM-DD", ... ] }
  var tree = {};
  dates.forEach(function (d) {
    var y = d.slice(0, 4), m = d.slice(0, 7);
    if (!tree[y]) tree[y] = {};
    if (!tree[y][m]) tree[y][m] = [];
    tree[y][m].push(d);
  });
  return tree;
}

function renderDateTree(tree) {
  // Years newest first; months by numeric order (Jan->Dec); days ascending.
  var years = Object.keys(tree).sort().reverse();
  var html = "";
  years.forEach(function (y) {
    html += '<div class="tree-row">' +
      '<span class="caret">&#9656;</span>' +
      '<input type="checkbox" class="tree-check" data-value="' + y + '">' +
      '<span class="tree-label">' + y + "</span></div>";
    html += '<div class="tree-children" style="display:none">';
    Object.keys(tree[y]).sort().forEach(function (m) {
      var name = MONTHS[parseInt(m.slice(5, 7), 10) - 1];
      html += '<div class="tree-row">' +
        '<span class="caret">&#9656;</span>' +
        '<input type="checkbox" class="tree-check" data-value="' + m + '">' +
        '<span class="tree-label">' + name + "</span></div>";
      html += '<div class="tree-children" style="display:none">';
      tree[y][m].slice().sort().forEach(function (d) {
        var label = d.slice(5, 7) + "/" + d.slice(8, 10) + "/" + d.slice(0, 4);
        html += '<div class="tree-row">' +
          '<span class="caret-spacer"></span>' +
          '<input type="checkbox" class="tree-check" data-value="' + d + '">' +
          '<span class="tree-label">' + label + "</span></div>";
      });
      html += "</div>";
    });
    html += "</div>";
  });
  return html;
}

function summarize(values, mapper, allLabel) {
  if (values.length === 0) return allLabel;
  if (values.length === 1) return mapper(values[0]);
  return values.length + " selected";
}

function updateOrgButton() {
  $("org-button").innerHTML =
    esc(summarize(selectedOrgs, function (v) { return v; }, "All Organizations")) +
    ' <span class="cbf-caret">&#9662;</span>';
  var allRow = $("org-panel").querySelector(".tree-all");
  if (allRow) allRow.classList.toggle("selected", selectedOrgs.length === 0);
}

function updateDateButton() {
  $("date-button").innerHTML =
    esc(summarize(selectedDates, dateLabel, "All Dates")) +
    ' <span class="cbf-caret">&#9662;</span>';
  var allRow = $("date-panel").querySelector(".tree-all");
  if (allRow) allRow.classList.toggle("selected", selectedDates.length === 0);
}

function dateMatches(d) {
  if (selectedDates.length === 0) return true;
  for (var i = 0; i < selectedDates.length; i++) {
    if (d && d.indexOf(selectedDates[i]) === 0) return true;
  }
  return false;
}

function refreshOrgFilter() {
  selectedOrgs = checkedValues("org-panel");
  updateOrgButton();
  render();
}

function refreshDateFilter() {
  selectedDates = checkedValues("date-panel");
  updateDateButton();
  render();
}

function updateSummary() {
  var orgText;
  if (selectedOrgs.length === 0) orgText = "All Organizations";
  else if (selectedOrgs.length <= 3) orgText = selectedOrgs.slice().sort().join(", ");
  else orgText = selectedOrgs.length + " selected";

  var dateText;
  if (selectedDates.length === 0) {
    dateText = "All Dates";
  } else if (selectedDates.length <= 3) {
    dateText = selectedDates.slice().sort().map(dateLabel).join(", ");
  } else {
    dateText = selectedDates.length + " dates selected";
  }
  $("filter-summary").textContent =
    "Filters: Organization = " + orgText + "  \\u00b7  Error Date = " + dateText;
}

function render() {
  var rows = RECORDS.filter(function (r) {
    return (selectedOrgs.length === 0 || selectedOrgs.indexOf(r.o) !== -1) &&
           dateMatches(r.d);
  });

  var table = {};
  rows.forEach(function (r) {
    var name = r.r || "(unknown)";
    var state = r.s || "(unknown)";
    if (!table[name]) table[name] = {};
    table[name][state] = (table[name][state] || 0) + 1;
  });

  var releases = Object.keys(table).map(function (name) {
    var counts = table[name];
    var total = Object.keys(counts).reduce(function (a, k) { return a + counts[k]; }, 0);
    var successful = counts["Successful"] || 0;
    var pct = total ? (successful / total) * 100 : 0;
    return { name: name, counts: counts, total: total,
             successful: successful, pct: pct, healthy: pct >= THRESHOLD };
  });
  // Sort processes alphabetically by ReleaseName, descending (Z -> A).
  releases.sort(function (a, b) { return b.name.localeCompare(a.name); });

  var grandTotal = releases.reduce(function (a, r) { return a + r.total; }, 0);
  var grandSucc = releases.reduce(function (a, r) { return a + r.successful; }, 0);
  var overall = grandTotal ? (grandSucc / grandTotal) * 100 : 0;
  var healthy = releases.filter(function (r) { return r.healthy; }).length;

  $("kpi-automations").textContent = releases.length;
  $("kpi-total").textContent = rows.length;
  var succEl = $("kpi-success");
  succEl.textContent = overall.toFixed(1) + "%";
  succEl.className = "value " + (overall >= THRESHOLD ? "ok" : "risk");
  $("kpi-ontarget").textContent = healthy;
  $("kpi-atrisk").textContent = releases.length - healthy;

  var out = [];
  releases.forEach(function (r) {
    var cls = r.pct >= THRESHOLD ? "ok" : "risk";
    var badge = r.healthy ? "&#10003; On Target" : "&#9650; Needs Attention";
    var cells = "";
    STATES.forEach(function (s) {
      cells += "<td class='num'>" + (r.counts[s] || 0) + "</td>";
    });
    out.push(
      '<tr><td class="name">' + esc(r.name) + "</td>" + cells +
      '<td class="num total">' + r.total + "</td>" +
      '<td class="pct ' + cls + '"><span class="dot ' + cls + '"></span>' +
      r.pct.toFixed(1) + "%</td>" +
      '<td><span class="badge ' + cls + '">' + badge + "</span></td></tr>"
    );
  });
  if (out.length === 0) {
    out.push('<tr><td colspan="' + (STATES.length + 4) +
      '" class="empty-row">No jobs match the selected filters.</td></tr>');
  }
  $("table-body").innerHTML = out.join("");
  $("result-count").textContent = rows.length + " of " + RECORDS.length + " jobs";
  updateSummary();
}

// Wire one collapsible checkbox panel: open/close, outside-click, caret
// expand/collapse, the "All" reset row, and checkbox/label toggling.
function setupPanel(buttonId, panelId, onRefresh) {
  var button = $(buttonId), panel = $(panelId);
  button.addEventListener("click", function () {
    panel.hidden = !panel.hidden;
    button.setAttribute("aria-expanded", String(!panel.hidden));
  });
  document.addEventListener("click", function (e) {
    if (!panel.hidden && !panel.contains(e.target) && !button.contains(e.target)) {
      panel.hidden = true;
      button.setAttribute("aria-expanded", "false");
    }
  });
  panel.addEventListener("click", function (e) {
    var caret = e.target.closest(".caret");
    if (caret) {
      var children = caret.closest(".tree-row").nextElementSibling;
      if (children && children.classList.contains("tree-children")) {
        var open = children.style.display !== "none";
        children.style.display = open ? "none" : "block";
        caret.innerHTML = open ? "&#9656;" : "&#9662;";
      }
      return;
    }
    if (e.target.closest(".tree-all")) {
      var boxes = panel.querySelectorAll(".tree-check");
      Array.prototype.forEach.call(boxes, function (b) { b.checked = false; });
      onRefresh();
      return;
    }
    if (e.target.classList.contains("tree-check")) {
      onRefresh();  // native toggle already applied
      return;
    }
    var row = e.target.closest(".tree-row");
    if (row) {
      var cb = row.querySelector(".tree-check");
      if (cb) { cb.checked = !cb.checked; onRefresh(); }
    }
  });
}

(function init() {
  var orgs = distinct(RECORDS.map(function (r) { return r.o; })).sort();
  $("org-list").innerHTML = renderOrgList(orgs);
  setupPanel("org-button", "org-panel", refreshOrgFilter);

  var dates = distinct(RECORDS.map(function (r) { return r.d; }));
  $("date-tree").innerHTML = renderDateTree(buildDateTree(dates));
  setupPanel("date-button", "date-panel", refreshDateFilter);

  render();
})();
"""


def render_dashboard(
    analysis: JobAnalysis,
    filter_desc: str,
    records: list[dict] | None = None,
    generated_at: datetime | None = None,
) -> str:
    """Build the interactive executive HTML dashboard for a job analysis.

    Args:
        analysis: The aggregated domain model. Supplies the full (unfiltered)
            ``states`` column set and the success ``threshold``; the live KPI
            and matrix values are computed client-side from ``records``.
        filter_desc: Human-readable description of the OData filter applied.
        records: Per-job rows (``Organization``, ``ReleaseName``, ``State``,
            ``ErrorDate``) embedded for client-side filtering. Defaults to none.
        generated_at: Timestamp to stamp on the report (defaults to now).
    """
    stamp = (generated_at or datetime.now()).strftime("%B %d, %Y at %I:%M %p")
    threshold = analysis.success_threshold
    states = analysis.states

    state_headers = "".join(
        f'<th scope="col">{escape(s)}</th>' for s in states
    )

    # Compact, minimal per-row payload for the browser: o=org, r=release,
    # s=state, d=error date. "</" is escaped so a value can't close the script.
    compact = [
        {
            "o": rec.get("Organization"),
            "r": rec.get("ReleaseName"),
            "s": rec.get("State"),
            "d": rec.get("ErrorDate"),
        }
        for rec in (records or [])
    ]
    records_json = json.dumps(compact).replace("</", "<\\/")
    states_json = json.dumps(states).replace("</", "<\\/")

    head = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>RPA Job Success Dashboard</title>\n"
        "<style>" + _CSS + "</style>\n"
        "</head>\n"
        "<body>\n"
        '  <header class="appbar">\n'
        '    <div class="appbar-inner">\n'
        '      <div class="brand"><span class="brand-mark"></span>'
        "RPA Operations</div>\n"
        '      <nav class="appbar-nav"><a href="index.html">'
        "&larr; Home</a></nav>\n"
        "    </div>\n"
        "  </header>\n"
        '  <main class="wrap">\n'
        '    <div class="page-head">\n'
        "      <h1>Job Success Dashboard</h1>\n"
    )

    header_sub = (
        f'      <div class="sub">Last Refreshed {escape(stamp)} '
        f'&nbsp;&bull;&nbsp; <span id="filter-summary">Filters: '
        f"{escape(filter_desc)}</span></div>\n"
        "    </div>\n"
    )

    controls = (
        '\n    <section class="filters" aria-label="Filters">\n'
        '      <div class="field">\n'
        '        <label id="org-label">Organization</label>\n'
        '        <div class="cbf">\n'
        '          <button type="button" class="cbf-button" id="org-button"'
        ' aria-haspopup="true" aria-expanded="false"'
        ' aria-label="Filter by organization">'
        'All Organizations <span class="cbf-caret">&#9662;</span></button>\n'
        '          <div class="cbf-panel" id="org-panel" hidden'
        ' role="group" aria-label="Organization filter">\n'
        '            <div class="tree-row tree-all selected">'
        '<span class="check-spacer"></span>'
        '<span class="tree-label">All Organizations</span></div>\n'
        '            <div id="org-list"></div>\n'
        "          </div>\n"
        "        </div>\n"
        "      </div>\n"
        '      <div class="field">\n'
        '        <label id="date-label">Error Date</label>\n'
        '        <div class="cbf">\n'
        '          <button type="button" class="cbf-button" id="date-button"'
        ' aria-haspopup="true" aria-expanded="false"'
        ' aria-label="Filter by error date">'
        'All Dates <span class="cbf-caret">&#9662;</span></button>\n'
        '          <div class="cbf-panel" id="date-panel" hidden'
        ' role="group" aria-label="Error date filter">\n'
        '            <div class="tree-row tree-all selected">'
        '<span class="caret-spacer"></span><span class="check-spacer"></span>'
        '<span class="tree-label">All Dates</span></div>\n'
        '            <div id="date-tree"></div>\n'
        "          </div>\n"
        "        </div>\n"
        "      </div>\n"
        '      <div class="result-count" id="result-count"></div>\n'
        "    </section>\n"
        '\n    <section class="kpis" aria-label="Key metrics">\n'
        '      <div class="kpi"><div class="label">Unique Automations</div>'
        '<div class="value" id="kpi-automations">0</div></div>\n'
        '      <div class="kpi"><div class="label">Total Jobs</div>'
        '<div class="value" id="kpi-total">0</div></div>\n'
        '      <div class="kpi kpi-hero"><div class="label">Overall Success</div>'
        '<div class="value" id="kpi-success">0%</div></div>\n'
        '      <div class="kpi"><div class="label">Processes On Target</div>'
        '<div class="value ok" id="kpi-ontarget">0</div></div>\n'
        '      <div class="kpi"><div class="label">Processes At Risk</div>'
        '<div class="value risk" id="kpi-atrisk">0</div></div>\n'
        "    </section>\n"
    )

    table_part = (
        '\n    <section class="card table-card"'
        ' aria-label="Process success matrix">\n'
        '      <div class="table-scroll">\n'
        "        <table>\n"
        "          <thead>\n"
        "            <tr>\n"
        '              <th scope="col">Process (ReleaseName)</th>\n'
        f"              {state_headers}\n"
        '              <th scope="col">Total</th>\n'
        '              <th scope="col">Success %</th>\n'
        '              <th scope="col">Status</th>\n'
        "            </tr>\n"
        "          </thead>\n"
        '          <tbody id="table-body"></tbody>\n'
        "        </table>\n"
        "      </div>\n"
        "    </section>\n"
    )

    legend = (
        '\n    <section class="legend" aria-label="Legend">\n'
        '      <div class="legend-title">Legend</div>\n'
        '      <div class="legend-items">\n'
        '        <span><span class="dot ok"></span>'
        f"Success % &ge; {threshold:.0f}% (On Target)</span>\n"
        '        <span><span class="dot risk"></span>'
        f"Success % &lt; {threshold:.0f}% (Needs Attention)</span>\n"
        "      </div>\n"
        "    </section>\n"
        "\n    <footer>UiPath Orchestrator &mdash; Automated reporting</footer>\n"
        "  </main>\n"
    )

    data_script = (
        "  <script>\n"
        "const RECORDS = " + records_json + ";\n"
        "const STATES = " + states_json + ";\n"
        "const THRESHOLD = " + str(float(threshold)) + ";\n"
        + _DASHBOARD_JS
        + "  </script>\n"
    )

    return (
        head
        + header_sub
        + controls
        + table_part
        + legend
        + data_script
        + "</body>\n</html>"
    )
