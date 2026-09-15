"""HTML dashboard reporting backend.

Renders a :class:`~monitoring.analytics.JobAnalysis` into a self-contained,
executive-style HTML page with KPI cards and a colour-coded success matrix.
Presentation concerns (colours, layout, copy) live here and nowhere else.

The page is interactive: the per-job rows are embedded as JSON and the KPIs and
success matrix are (re)computed client-side, so the Organization, Process Name
and Process Run Date filters re-aggregate the view without a server round-trip.
The JavaScript aggregation mirrors :func:`~monitoring.analytics.analyze_jobs`.

The filters share one collapsible, multi-select checkbox control: Organization
and Process Name are flat checkbox lists, Process Run Date a Year > Month > Day
tree. The Process Name options are scoped to the current Organization selection
(all automations when no org is chosen) and sorted alphabetically.

The success matrix lays its job-state columns out in lifecycle order (Running,
Stopped, Faulted, Successful) rather than alphabetically; see ``STATE_ORDER``.
It is sortable on every column — process name, each job state,
Total, Success % and Status. Clicking a header sorts by it (text ascending,
numbers descending on first click) and clicking again reverses; the active
column is marked with an arrow and ``aria-sort`` for screen readers.

Success % is measured over completed jobs only (see
:data:`~monitoring.analytics.SUCCESS_RATE_STATES`): jobs still Running are
shown in their own column and counted in Total, but excluded from the success
denominator. Visual design
uses CSS custom properties (design tokens) built from the brand palette —
forest green (primary), slate blue (secondary), warm gold (accent) — plus a
neutral gray scale, so colours are defined once in ``:root`` and reused.
"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape

from ..analytics import SUCCESS_RATE_STATES
from .states import STATE_ORDER


# --- Page styling ----------------------------------------------------------
# Design tokens in :root derive every colour from the three brand hues plus a
# neutral scale; components reference the tokens so the palette is single-source.
_CSS = ""  # styling moved to shared styles.css (single source of truth)


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

var selectedOrgs = [];       // checked organization codes
var selectedProcesses = [];  // checked process (ReleaseName) values
var selectedDates = [];      // checked prefixes: "YYYY" | "YYYY-MM" | "YYYY-MM-DD"

// --- Table columns ---------------------------------------------------------
// Preferred left-to-right order for the job-state columns, following a run's
// lifecycle: in flight -> halted -> failed -> succeeded. Generated from
// monitoring.reporting.states.STATE_ORDER so the dashboard and the console
// table share one definition. STATES itself is data-driven (whatever states
// the query returned), so any state NOT listed here is kept and appended
// alphabetically rather than being dropped — a new Orchestrator state still
// gets a column.
var STATE_ORDER = __STATE_ORDER_JSON__;

// Success % counts only jobs whose outcome is settled. Generated from
// monitoring.analytics.SUCCESS_RATE_STATES so the dashboard, the console table
// and the trends page all measure the rate the same way. Jobs in any other
// state (notably Running) still appear in their own column and in Total — they
// are left out of the success denominator only, so an in-flight run is not
// counted as a failure while it executes.
var SUCCESS_STATES = __SUCCESS_STATES_JSON__;

function orderStates(states) {
  var known = STATE_ORDER.filter(function (s) { return states.indexOf(s) !== -1; });
  var rest = states.filter(function (s) { return STATE_ORDER.indexOf(s) === -1; });
  return known.concat(rest.sort());
}

// --- Table sorting ---------------------------------------------------------
// COLUMNS is built once from STATES (which is data-driven, so the state
// columns vary with the dataset). Each entry knows how to pull its own sort
// value off an aggregated release row, so sorting stays declarative and adding
// a column means adding one entry here.
var COLUMNS = [];
var sortKey = "name";   // column key currently sorted on
var sortDir = "desc";   // "asc" | "desc"

function buildColumns() {
  var cols = [{ key: "name", label: "Process (ReleaseName)", type: "text",
                get: function (r) { return r.name; } }];
  STATES.forEach(function (s) {
    // Bind s per iteration so each accessor reads its own state's count.
    cols.push({ key: "state:" + s, label: s, type: "num",
                get: (function (state) {
                  return function (r) { return r.counts[state] || 0; };
                })(s) });
  });
  cols.push({ key: "total",  label: "Total",      type: "num",
              get: function (r) { return r.total; } });
  cols.push({ key: "pct",    label: "Success %",  type: "num",
              get: function (r) { return r.pct; } });
  // Status is the health badge; sorting it groups At Risk vs On Target, with
  // success % as the tiebreak so the worst offenders lead a descending sort.
  cols.push({ key: "status", label: "Status",     type: "num",
              get: function (r) { return r.healthy ? 1 : 0; } });
  return cols;
}

function columnByKey(key) {
  for (var i = 0; i < COLUMNS.length; i++) {
    if (COLUMNS[i].key === key) return COLUMNS[i];
  }
  return COLUMNS[0];
}

function sortReleases(releases) {
  var col = columnByKey(sortKey);
  var dir = sortDir === "asc" ? 1 : -1;
  releases.sort(function (a, b) {
    var av = col.get(a), bv = col.get(b), cmp;
    if (col.type === "text") {
      cmp = String(av).localeCompare(String(bv));
    } else {
      cmp = av - bv;
      // Status ties on the badge: break them by success % so the ordering is
      // meaningful rather than arbitrary.
      if (cmp === 0 && col.key === "status") cmp = a.pct - b.pct;
    }
    // Stable, deterministic ordering for equal values.
    if (cmp === 0) return a.name.localeCompare(b.name);
    return cmp * dir;
  });
  return releases;
}

// Text reads naturally A -> Z; counts and percentages are most useful with the
// largest value first, so a fresh column starts descending.
function defaultDirFor(col) { return col.type === "text" ? "asc" : "desc"; }

function renderHead() {
  var html = "";
  COLUMNS.forEach(function (c) {
    var active = c.key === sortKey;
    var aria = active ? (sortDir === "asc" ? "ascending" : "descending") : "none";
    var arrow = active
      ? '<span class="sort-arrow" aria-hidden="true">' +
        (sortDir === "asc" ? "&#9650;" : "&#9660;") + "</span>"
      : '<span class="sort-arrow dim" aria-hidden="true">&#8693;</span>';
    html += '<th scope="col" aria-sort="' + aria + '">' +
      '<button type="button" class="th-sort' + (active ? " active" : "") +
      '" data-key="' + esc(c.key) + '">' +
      '<span>' + esc(c.label) + "</span>" + arrow + "</button></th>";
  });
  $("thead-row").innerHTML = html;
}

// One delegated listener on the header row: survives every renderHead() redraw.
function setupSorting() {
  $("thead-row").addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest(".th-sort") : null;
    if (!btn) return;
    var key = btn.getAttribute("data-key");
    if (key === sortKey) {
      sortDir = sortDir === "asc" ? "desc" : "asc";
    } else {
      sortKey = key;
      sortDir = defaultDirFor(columnByKey(key));
    }
    render();
  });
}

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

function updateProcessButton() {
  $("process-button").innerHTML =
    esc(summarize(selectedProcesses, function (v) { return v; }, "All Processes")) +
    ' <span class="cbf-caret">&#9662;</span>';
  var allRow = $("process-panel").querySelector(".tree-all");
  if (allRow) allRow.classList.toggle("selected", selectedProcesses.length === 0);
}

// Process (ReleaseName) options available for the current Organization
// selection: all processes when no org is chosen, otherwise only those seen
// under the selected orgs. Sorted alphabetically (A -> Z).
function processNamesForOrgs(orgSel) {
  var names = RECORDS.filter(function (r) {
    return orgSel.length === 0 || orgSel.indexOf(r.o) !== -1;
  }).map(function (r) { return r.r; });
  return distinct(names).sort(function (a, b) {
    return String(a).localeCompare(String(b));
  });
}

// Rebuild the process panel to reflect the current Organization filter,
// dropping any selected processes that are no longer available and re-checking
// those that still are.
function rebuildProcessPanel() {
  var names = processNamesForOrgs(selectedOrgs);
  selectedProcesses = selectedProcesses.filter(function (p) {
    return names.indexOf(p) !== -1;
  });
  $("process-list").innerHTML = renderOrgList(names);
  var boxes = $("process-panel").querySelectorAll(".tree-check");
  Array.prototype.forEach.call(boxes, function (b) {
    if (selectedProcesses.indexOf(b.getAttribute("data-value")) !== -1) {
      b.checked = true;
    }
  });
  updateProcessButton();
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
  rebuildProcessPanel();  // process options depend on the org selection
  render();
}

function refreshProcessFilter() {
  selectedProcesses = checkedValues("process-panel");
  updateProcessButton();
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

  var processText;
  if (selectedProcesses.length === 0) processText = "All Processes";
  else if (selectedProcesses.length <= 3) processText = selectedProcesses.slice().sort().join(", ");
  else processText = selectedProcesses.length + " selected";

  var dateText;
  if (selectedDates.length === 0) {
    dateText = "All Dates";
  } else if (selectedDates.length <= 3) {
    dateText = selectedDates.slice().sort().map(dateLabel).join(", ");
  } else {
    dateText = selectedDates.length + " dates selected";
  }
  $("filter-summary").textContent =
    "Filters: Organization = " + orgText +
    "  \\u00b7  Process = " + processText +
    "  \\u00b7  Process Run Date = " + dateText;
}

function render() {
  var rows = RECORDS.filter(function (r) {
    return (selectedOrgs.length === 0 || selectedOrgs.indexOf(r.o) !== -1) &&
           (selectedProcesses.length === 0 || selectedProcesses.indexOf(r.r) !== -1) &&
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
    // Denominator excludes in-flight states; total still counts every job.
    var completed = SUCCESS_STATES.reduce(function (a, s) {
      return a + (counts[s] || 0);
    }, 0);
    var pct = completed ? (successful / completed) * 100 : 0;
    return { name: name, counts: counts, total: total, completed: completed,
             successful: successful, pct: pct, healthy: pct >= THRESHOLD };
  });
  // Order by the column the user picked in the header (default: ReleaseName
  // descending, Z -> A). renderHead() repaints the indicators to match.
  sortReleases(releases);
  renderHead();

  var grandTotal = releases.reduce(function (a, r) { return a + r.total; }, 0);
  var grandSucc = releases.reduce(function (a, r) { return a + r.successful; }, 0);
  var grandDone = releases.reduce(function (a, r) { return a + r.completed; }, 0);
  var overall = grandDone ? (grandSucc / grandDone) * 100 : 0;
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

// Called by the auth/fetch bootstrap once RECORDS and STATES are populated
// from the live, RLS-filtered Supabase query.
function initDashboard() {
  // STATES is known only once the data is in, so the column model (and with it
  // the sortable header) is built here rather than at load time. Reorder the
  // states first: both the header and the body cells iterate STATES, so fixing
  // the order once here keeps them aligned.
  STATES = orderStates(STATES);
  COLUMNS = buildColumns();
  setupSorting();

  var orgs = distinct(RECORDS.map(function (r) { return r.o; })).sort();
  $("org-list").innerHTML = renderOrgList(orgs);
  setupPanel("org-button", "org-panel", refreshOrgFilter);

  // Process options start unfiltered (no org selected = all automations).
  rebuildProcessPanel();
  setupPanel("process-button", "process-panel", refreshProcessFilter);

  var dates = distinct(RECORDS.map(function (r) { return r.d; }));
  $("date-tree").innerHTML = renderDateTree(buildDateTree(dates));
  setupPanel("date-button", "date-panel", refreshDateFilter);

  render();
}
"""

# --- Auth gate + live, RLS-filtered data fetch ----------------------------
# Requires a logged-in session, then loads only the organizations and job rows
# the user is permitted to see (RLS enforces this), builds RECORDS/STATES, and
# renders. No data is embedded server-side, so the page exposes nothing on its
# own — access is decided by the database per authenticated user.
_DASHBOARD_BOOTSTRAP = """
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
        .select("organization_id, job_name, job_state, error_datetime")
        .range(from, from + PAGE - 1);
      if (res.error) throw res.error;
      rows = rows.concat(res.data);
      if (res.data.length < PAGE) break;
      from += PAGE;
    }
    RECORDS = rows.map(function (r) {
      return {
        o: orgs[r.organization_id] || r.organization_id,
        r: r.job_name,
        s: r.job_state,
        d: r.error_datetime ? String(r.error_datetime).slice(0, 10) : null
      };
    });
    STATES = Array.from(new Set(RECORDS.map(function (r) { return r.s; })
      .filter(Boolean))).sort();
    var stamp = document.getElementById("refresh-stamp");
    if (stamp) stamp.textContent = new Date().toLocaleString();
    initDashboard();
  } catch (e) {
    var tb = document.getElementById("table-body");
    if (tb) tb.innerHTML = '<tr><td colspan="20" class="empty-row">Could not load ' +
      "data: " + (e.message || e) + "</td></tr>";
  }
})();
"""


def render_dashboard(
    threshold: float = 90.0,
    generated_at: datetime | None = None,
) -> str:
    """Build the authenticated, interactive HTML dashboard shell.

    The page embeds NO data: on load it requires a Supabase session and fetches
    only the organizations/jobs the signed-in user may see (enforced by RLS),
    then computes the KPIs and success matrix client-side. ``threshold`` is the
    success-rate cutoff for the On Target / Needs Attention split.

    Args:
        threshold: Percent at/above which a process counts as healthy.
        generated_at: Timestamp to stamp on the page shell (defaults to now).
    """
    stamp = (generated_at or datetime.now()).strftime("%B %d, %Y at %I:%M %p")

    head = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>RPA Job Success Dashboard</title>\n"
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">\n'
        '<link rel="stylesheet" href="styles.css">\n'
        "</head>\n"
        '<body class="page-wide">\n'
        '  <header class="appbar">\n'
        '    <div class="appbar-inner">\n'
        '      <div class="brand"><span class="brand-mark"></span>'
        "RPA Operations</div>\n"
        '      <nav class="appbar-nav">\n'
        '        <a href="index.html">Home</a>\n'
        '        <a href="dashboard.html" aria-current="page">Dashboard</a>\n'
        '        <a href="trends.html">Trending</a>\n'
        '        <a href="admin.html">Admin</a>\n'
        '        <button type="button" id="signout">Sign out</button>\n'
        "      </nav>\n"
        "    </div>\n"
        "  </header>\n"
        '  <main class="wrap">\n'
        '    <div class="page-head">\n'
        "      <h1>Job Success Dashboard</h1>\n"
    )

    header_sub = (
        f'      <div class="sub">Last Refreshed <span id="refresh-stamp">'
        f"{escape(stamp)}</span> &nbsp;&bull;&nbsp; "
        '<span id="filter-summary">Loading your data&hellip;</span></div>\n'
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
        '        <label id="process-label">Process Name</label>\n'
        '        <div class="cbf">\n'
        '          <button type="button" class="cbf-button" id="process-button"'
        ' aria-haspopup="true" aria-expanded="false"'
        ' aria-label="Filter by process name">'
        'All Processes <span class="cbf-caret">&#9662;</span></button>\n'
        '          <div class="cbf-panel" id="process-panel" hidden'
        ' role="group" aria-label="Process name filter">\n'
        '            <div class="tree-row tree-all selected">'
        '<span class="check-spacer"></span>'
        '<span class="tree-label">All Processes</span></div>\n'
        '            <div id="process-list"></div>\n'
        "          </div>\n"
        "        </div>\n"
        "      </div>\n"
        '      <div class="field">\n'
        '        <label id="date-label">Process Run Date</label>\n'
        '        <div class="cbf">\n'
        '          <button type="button" class="cbf-button" id="date-button"'
        ' aria-haspopup="true" aria-expanded="false"'
        ' aria-label="Filter by process run date">'
        'All Dates <span class="cbf-caret">&#9662;</span></button>\n'
        '          <div class="cbf-panel" id="date-panel" hidden'
        ' role="group" aria-label="Process run date filter">\n'
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
        '\n    <section class="card is-flush"'
        ' aria-label="Process success matrix">\n'
        '      <div class="table-scroll">\n'
        "        <table>\n"
        '          <thead><tr id="thead-row"></tr></thead>\n'
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
        '  <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2">'
        "</script>\n"
        '  <script src="app-config.js"></script>\n'
        "  <script>\n"
        "var RECORDS = [], STATES = [], THRESHOLD = " + str(float(threshold)) + ";\n"
        # One source of truth for column order: the JS array is generated
        # from the same STATE_ORDER the console renderer uses.
        + _DASHBOARD_JS.replace(
            "__STATE_ORDER_JSON__", json.dumps(list(STATE_ORDER))
        ).replace(
            "__SUCCESS_STATES_JSON__", json.dumps(list(SUCCESS_RATE_STATES))
        )
        + _DASHBOARD_BOOTSTRAP
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
