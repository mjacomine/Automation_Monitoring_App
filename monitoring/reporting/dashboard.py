"""HTML dashboard reporting backend.

Renders a :class:`~monitoring.analytics.JobAnalysis` into a self-contained,
executive-style HTML page with KPI cards and a colour-coded success matrix.
Presentation concerns (colours, layout, copy) live here and nowhere else.

The page is interactive: the per-job rows are embedded as JSON and the KPIs and
success matrix are (re)computed client-side, so the Organization and Error Date
dropdown filters re-aggregate the view without a server round-trip. The
JavaScript aggregation mirrors :func:`~monitoring.analytics.analyze_jobs`.
"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape

from ..analytics import JobAnalysis

# Colour thresholds for the Success % indicator.
SUCCESS_GREEN = "#008000"  # at/above the success threshold
SUCCESS_RED = "#FF0000"    # below the success threshold


# --- Page styling ----------------------------------------------------------
_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    background: #467958;
    color: #1e293b;
    padding: 40px 24px;
  }
  .wrap { max-width: 1100px; margin: 0 auto; }
  header { color: #f8fafc; margin-bottom: 28px; }
  header h1 { font-size: 26px; font-weight: 600; letter-spacing: .3px; }
  header .sub { color: #FFFFFF; font-size: 14px; margin-top: 6px; }

  .filters {
    display: flex; gap: 20px; flex-wrap: wrap; align-items: flex-end;
    background: #ffffff; border-radius: 12px; padding: 18px 20px;
    box-shadow: 0 6px 18px rgba(0,0,0,.25); margin-bottom: 28px;
  }
  .filters .field { display: flex; flex-direction: column; gap: 6px; }
  .filters label {
    font-size: 12px; text-transform: uppercase; letter-spacing: .8px;
    color: #64748b; font-weight: 600;
  }
  .filters select {
    font-family: inherit; font-size: 14px; padding: 9px 12px;
    border: 1px solid #cbd5e1; border-radius: 8px; background: #f8fafc;
    color: #0f172a; min-width: 220px; cursor: pointer;
  }
  .filters select:focus {
    outline: none; border-color: #82A2B1;
    box-shadow: 0 0 0 3px rgba(130,162,177,.35);
  }
  .filters .result-count {
    margin-left: auto; align-self: center;
    color: #64748b; font-size: 13px; font-weight: 600;
  }

  /* Collapsible Year > Month > Day date filter */
  .date-filter { position: relative; }
  .date-button {
    font-family: inherit; font-size: 14px; padding: 9px 12px;
    border: 1px solid #cbd5e1; border-radius: 8px; background: #f8fafc;
    color: #0f172a; min-width: 220px; cursor: pointer; text-align: left;
    display: inline-flex; justify-content: space-between; align-items: center;
    gap: 8px;
  }
  .date-button:focus {
    outline: none; border-color: #82A2B1;
    box-shadow: 0 0 0 3px rgba(130,162,177,.35);
  }
  .date-caret { color: #64748b; font-size: 12px; }
  .date-panel {
    position: absolute; z-index: 20; top: calc(100% + 6px); left: 0;
    width: 260px; max-height: 320px; overflow-y: auto;
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px;
    box-shadow: 0 10px 28px rgba(0,0,0,.30); padding: 6px;
  }
  .date-panel[hidden] { display: none; }
  .tree-row {
    display: flex; align-items: center; gap: 6px; padding: 6px 8px;
    border-radius: 6px; cursor: pointer; font-size: 14px; color: #0f172a;
    white-space: nowrap;
  }
  .tree-row:hover { background: #f1f5f9; }
  .tree-row.selected { background: #467958; color: #ffffff; font-weight: 600; }
  .tree-row.selected .caret { color: #ffffff; }
  .tree-children { padding-left: 16px; }
  .caret { width: 14px; text-align: center; color: #64748b; font-size: 11px; }
  .caret-spacer { width: 14px; display: inline-block; }
  .tree-check {
    accent-color: #467958; width: 15px; height: 15px; cursor: pointer; flex: none;
  }
  .check-spacer { width: 15px; display: inline-block; }
  .tree-all { font-weight: 600; }

  .kpis {
    display: grid; grid-template-columns: repeat(5, 1fr);
    gap: 16px; margin-bottom: 28px;
  }
  .kpi {
    background: #ffffff; border-radius: 12px; padding: 20px;
    box-shadow: 0 6px 18px rgba(0,0,0,.25);
  }
  .kpi .label {
    font-size: 12px; text-transform: uppercase; letter-spacing: .8px;
    color: #64748b; font-weight: 600;
  }
  .kpi .value { font-size: 30px; font-weight: 700; margin-top: 8px; }
  .card {
    background: #ffffff; border-radius: 12px; overflow: hidden;
    box-shadow: 0 6px 18px rgba(0,0,0,.25);
  }
  table { width: 100%; border-collapse: collapse; }
  thead th {
    background: #82A2B1; color: #f1f5f9; text-align: right;
    padding: 14px 16px; font-size: 12px; text-transform: uppercase;
    letter-spacing: .6px; font-weight: 600;
  }
  thead th:first-child { text-align: left; }
  tbody td {
    padding: 14px 16px; border-bottom: 1px solid #e2e8f0;
    font-size: 15px; text-align: right;
  }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr:nth-child(even) { background: #f8fafc; }
  td.name { text-align: left; font-weight: 600; color: #0f172a; }
  td.num { color: #475569; font-variant-numeric: tabular-nums; }
  td.total { font-weight: 700; color: #0f172a; }
  td.pct { font-weight: 700; font-variant-numeric: tabular-nums; }
  .dot {
    display: inline-block; width: 9px; height: 9px; border-radius: 50%;
    margin-right: 7px; vertical-align: middle;
  }
  .badge {
    color: #fff; font-size: 11px; font-weight: 600; padding: 4px 10px;
    border-radius: 999px; text-transform: uppercase; letter-spacing: .5px;
    white-space: nowrap;
  }
  .legend {
    background: #ffffff; color: #000000; margin-top: 18px;
    border-radius: 12px; padding: 18px 20px;
    box-shadow: 0 6px 18px rgba(0,0,0,.25);
  }
  .legend .legend-title {
    font-size: 12px; text-transform: uppercase; letter-spacing: .8px;
    font-weight: 700; color: #000000; margin-bottom: 12px;
  }
  .legend .legend-items {
    display: flex; gap: 24px; font-size: 13px; align-items: center;
  }
  .legend .dot { width: 11px; height: 11px; }
  footer { color: #64748b; font-size: 12px; margin-top: 22px; text-align: center; }

  @media (max-width: 760px) {
    .kpis { grid-template-columns: repeat(2, 1fr); }
    .filters select { min-width: 160px; }
  }
"""


# --- Client-side aggregation + filtering -----------------------------------
# Mirrors analytics.analyze_jobs: group by ReleaseName, count by State, derive
# success % and health against THRESHOLD, sort releases by volume. Reads the
# RECORDS / STATES / THRESHOLD constants emitted just above it in the page.
#
# The Error Date filter is a collapsible Year > Month > Day tree with a checkbox
# on every node for multi-select. Each checked box contributes a date prefix
# ("YYYY", "YYYY-MM", or "YYYY-MM-DD"); a row matches if its date starts with
# ANY selected prefix (the union). No selection means all dates.
_DASHBOARD_JS = """
const $ = function (id) { return document.getElementById(id); };
const GREEN = "#008000", RED = "#FF0000";
const MONTHS = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];

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

function fillSelect(sel, values, allLabel) {
  var html = ['<option value="">' + allLabel + "</option>"];
  values.forEach(function (v) {
    html.push('<option value="' + esc(v) + '">' + esc(v) + "</option>");
  });
  sel.innerHTML = html.join("");
}

function dateLabel(prefix) {
  if (!prefix) return "All Dates";
  var p = prefix.split("-");
  if (p.length === 1) return p[0];
  if (p.length === 2) return MONTHS[parseInt(p[1], 10) - 1] + " " + p[0];
  return p[1] + "/" + p[2] + "/" + p[0];  // MM/dd/yyyy
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

function updateDateButton() {
  var label;
  if (selectedDates.length === 0) label = "All Dates";
  else if (selectedDates.length === 1) label = dateLabel(selectedDates[0]);
  else label = selectedDates.length + " selected";
  $("date-button").innerHTML = esc(label) +
    ' <span class="date-caret">&#9662;</span>';
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

function refreshDateFilter() {
  var boxes = $("date-panel").querySelectorAll(".tree-check");
  selectedDates = [];
  Array.prototype.forEach.call(boxes, function (b) {
    if (b.checked) selectedDates.push(b.getAttribute("data-value"));
  });
  updateDateButton();
  render();
}

function updateSummary() {
  var org = $("filter-org").value;
  var orgLabel = org === "" ? "All Organizations" : org;
  var dateText;
  if (selectedDates.length === 0) {
    dateText = "All Dates";
  } else if (selectedDates.length <= 3) {
    dateText = selectedDates.slice().sort().map(dateLabel).join(", ");
  } else {
    dateText = selectedDates.length + " dates selected";
  }
  $("filter-summary").textContent =
    "Filters: Organization = " + orgLabel + "  \\u00b7  Error Date = " + dateText;
}

function render() {
  var org = $("filter-org").value;
  var rows = RECORDS.filter(function (r) {
    return (org === "" || r.o === org) && dateMatches(r.d);
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
  releases.sort(function (a, b) { return b.total - a.total; });

  var grandTotal = releases.reduce(function (a, r) { return a + r.total; }, 0);
  var grandSucc = releases.reduce(function (a, r) { return a + r.successful; }, 0);
  var overall = grandTotal ? (grandSucc / grandTotal) * 100 : 0;
  var healthy = releases.filter(function (r) { return r.healthy; }).length;

  $("kpi-automations").textContent = releases.length;
  $("kpi-total").textContent = rows.length;
  var succEl = $("kpi-success");
  succEl.textContent = overall.toFixed(1) + "%";
  succEl.style.color = overall >= THRESHOLD ? GREEN : RED;
  $("kpi-ontarget").textContent = healthy;
  $("kpi-ontarget").style.color = GREEN;
  $("kpi-atrisk").textContent = releases.length - healthy;
  $("kpi-atrisk").style.color = RED;

  var out = [];
  releases.forEach(function (r) {
    var color = r.pct >= THRESHOLD ? GREEN : RED;
    var badge = r.healthy ? "On Target" : "Needs Attention";
    var cells = "";
    STATES.forEach(function (s) {
      cells += "<td class='num'>" + (r.counts[s] || 0) + "</td>";
    });
    out.push(
      '<tr><td class="name">' + esc(r.name) + "</td>" + cells +
      '<td class="num total">' + r.total + "</td>" +
      '<td class="pct" style="color:' + color + ';"><span class="dot" style="background:' +
      color + ';"></span>' + r.pct.toFixed(1) + "%</td>" +
      '<td><span class="badge" style="background:' + color + ';">' + badge + "</span></td></tr>"
    );
  });
  if (out.length === 0) {
    out.push('<tr><td colspan="' + (STATES.length + 4) +
      '" style="padding:18px;text-align:left;color:#64748b;">' +
      "No jobs match the selected filters.</td></tr>");
  }
  $("table-body").innerHTML = out.join("");
  $("result-count").textContent = rows.length + " of " + RECORDS.length + " jobs";
  updateSummary();
}

(function init() {
  var orgs = distinct(RECORDS.map(function (r) { return r.o; })).sort();
  fillSelect($("filter-org"), orgs, "All Organizations");
  $("filter-org").addEventListener("change", render);

  var dates = distinct(RECORDS.map(function (r) { return r.d; }));
  $("date-tree").innerHTML = renderDateTree(buildDateTree(dates));

  var button = $("date-button");
  var panel = $("date-panel");
  button.addEventListener("click", function (e) {
    e.stopPropagation();
    panel.hidden = !panel.hidden;
  });
  document.addEventListener("click", function (e) {
    if (!e.target.closest(".date-filter")) panel.hidden = true;
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
      e.stopPropagation();
      return;
    }
    if (e.target.closest(".tree-all")) {
      var boxes = panel.querySelectorAll(".tree-check");
      Array.prototype.forEach.call(boxes, function (b) { b.checked = false; });
      refreshDateFilter();
      return;
    }
    if (e.target.classList.contains("tree-check")) {
      refreshDateFilter();  // native toggle already applied
      return;
    }
    var row = e.target.closest(".tree-row");
    if (row) {
      var cb = row.querySelector(".tree-check");
      if (cb) { cb.checked = !cb.checked; refreshDateFilter(); }
    }
  });

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

    state_headers = "".join(f"<th>{escape(s)}</th>" for s in states)

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
        '  <div class="wrap">\n'
        "    <header>\n"
        "      <h1>RPA Job Success Dashboard</h1>\n"
    )

    header_sub = (
        f'      <div class="sub">Last Refreshed {escape(stamp)} '
        f'&nbsp;&bull;&nbsp; <span id="filter-summary">Filters: '
        f"{escape(filter_desc)}</span></div>\n"
        "    </header>\n"
    )

    controls = (
        '\n    <div class="filters">\n'
        '      <div class="field">\n'
        '        <label for="filter-org">Organization</label>\n'
        '        <select id="filter-org"></select>\n'
        "      </div>\n"
        '      <div class="field">\n'
        "        <label>Error Date</label>\n"
        '        <div class="date-filter">\n'
        '          <button type="button" class="date-button" id="date-button">'
        'All Dates <span class="date-caret">&#9662;</span></button>\n'
        '          <div class="date-panel" id="date-panel" hidden>\n'
        '            <div class="tree-row tree-all selected">'
        '<span class="caret-spacer"></span><span class="check-spacer"></span>'
        '<span class="tree-label">All Dates</span></div>\n'
        '            <div id="date-tree"></div>\n'
        "          </div>\n"
        "        </div>\n"
        "      </div>\n"
        '      <div class="result-count" id="result-count"></div>\n'
        "    </div>\n"
        '\n    <div class="kpis">\n'
        '      <div class="kpi"><div class="label">Unique Automations</div>'
        '<div class="value" id="kpi-automations">0</div></div>\n'
        '      <div class="kpi"><div class="label">Total Jobs</div>'
        '<div class="value" id="kpi-total">0</div></div>\n'
        '      <div class="kpi"><div class="label">Overall Success</div>'
        '<div class="value" id="kpi-success">0%</div></div>\n'
        '      <div class="kpi"><div class="label">Processes On Target</div>'
        '<div class="value" id="kpi-ontarget">0</div></div>\n'
        '      <div class="kpi"><div class="label">Processes At Risk</div>'
        '<div class="value" id="kpi-atrisk">0</div></div>\n'
        "    </div>\n"
    )

    table_part = (
        '\n    <div class="card">\n'
        "      <table>\n"
        "        <thead>\n"
        "          <tr>\n"
        "            <th>Process (ReleaseName)</th>\n"
        f"            {state_headers}\n"
        "            <th>Total</th>\n"
        "            <th>Success %</th>\n"
        "            <th>Status</th>\n"
        "          </tr>\n"
        "        </thead>\n"
        '        <tbody id="table-body"></tbody>\n'
        "      </table>\n"
        "    </div>\n"
    )

    legend = (
        '\n    <div class="legend">\n'
        '      <div class="legend-title">Legend</div>\n'
        '      <div class="legend-items">\n'
        f'        <span><span class="dot" style="background:{SUCCESS_GREEN};"></span>'
        f"Success % &ge; {threshold:.0f}% (On Target)</span>\n"
        f'        <span><span class="dot" style="background:{SUCCESS_RED};"></span>'
        f"Success % &lt; {threshold:.0f}% (Needs Attention)</span>\n"
        "      </div>\n"
        "    </div>\n"
        "\n    <footer>UiPath Orchestrator &mdash; Automated reporting</footer>\n"
        "  </div>\n"
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
