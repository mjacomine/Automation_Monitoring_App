"""HTML dashboard reporting backend.

Renders a :class:`~monitoring.analytics.JobAnalysis` into a self-contained,
executive-style HTML page with KPI cards and a colour-coded success matrix.
Presentation concerns (colours, layout, copy) live here and nowhere else.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

from ..analytics import JobAnalysis

# Colour thresholds for the Success % indicator.
SUCCESS_GREEN = "#008000"  # at/above the success threshold
SUCCESS_RED = "#FF0000"    # below the success threshold


def _color_for(pct: float, threshold: float) -> str:
    return SUCCESS_GREEN if pct >= threshold else SUCCESS_RED


def render_dashboard(
    analysis: JobAnalysis,
    filter_desc: str,
    generated_at: datetime | None = None,
) -> str:
    """Build the executive HTML dashboard for a job analysis.

    Args:
        analysis: The aggregated domain model to render.
        filter_desc: Human-readable description of the OData filter applied.
        generated_at: Timestamp to stamp on the report (defaults to now).
    """
    stamp = (generated_at or datetime.now()).strftime("%B %d, %Y at %I:%M %p")
    threshold = analysis.success_threshold
    overall_color = _color_for(analysis.overall_success_pct, threshold)

    state_headers = "".join(f"<th>{escape(s)}</th>" for s in analysis.states)

    rows = []
    for r in analysis.releases_by_volume():
        color = _color_for(r.success_pct, threshold)
        badge = "On Target" if r.is_healthy else "Needs Attention"
        state_cells = "".join(
            f"<td class='num'>{r.state_counts.get(s, 0)}</td>"
            for s in analysis.states
        )
        rows.append(f"""
        <tr>
          <td class="name">{escape(r.release_name)}</td>
          {state_cells}
          <td class="num total">{r.total}</td>
          <td class="pct" style="color:{color};">
            <span class="dot" style="background:{color};"></span>{r.success_pct:.1f}%
          </td>
          <td><span class="badge" style="background:{color};">{badge}</span></td>
        </tr>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RPA Job Success Dashboard</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    background: #467958;
    color: #1e293b;
    padding: 40px 24px;
  }}
  .wrap {{ max-width: 1100px; margin: 0 auto; }}
  header {{ color: #f8fafc; margin-bottom: 28px; }}
  header h1 {{ font-size: 26px; font-weight: 600; letter-spacing: .3px; }}
  header .sub {{ color: #FFFFFF; font-size: 14px; margin-top: 6px; }}
  .kpis {{
    display: grid; grid-template-columns: repeat(5, 1fr);
    gap: 16px; margin-bottom: 28px;
  }}
  .kpi {{
    background: #ffffff; border-radius: 12px; padding: 20px;
    box-shadow: 0 6px 18px rgba(0,0,0,.25);
  }}
  .kpi .label {{
    font-size: 12px; text-transform: uppercase; letter-spacing: .8px;
    color: #64748b; font-weight: 600;
  }}
  .kpi .value {{ font-size: 30px; font-weight: 700; margin-top: 8px; }}
  .card {{
    background: #ffffff; border-radius: 12px; overflow: hidden;
    box-shadow: 0 6px 18px rgba(0,0,0,.25);
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    background: #82A2B1; color: #f1f5f9; text-align: right;
    padding: 14px 16px; font-size: 12px; text-transform: uppercase;
    letter-spacing: .6px; font-weight: 600;
  }}
  thead th:first-child {{ text-align: left; }}
  tbody td {{
    padding: 14px 16px; border-bottom: 1px solid #e2e8f0;
    font-size: 15px; text-align: right;
  }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:nth-child(even) {{ background: #f8fafc; }}
  td.name {{ text-align: left; font-weight: 600; color: #0f172a; }}
  td.num {{ color: #475569; font-variant-numeric: tabular-nums; }}
  td.total {{ font-weight: 700; color: #0f172a; }}
  td.pct {{ font-weight: 700; font-variant-numeric: tabular-nums; }}
  .dot {{
    display: inline-block; width: 9px; height: 9px; border-radius: 50%;
    margin-right: 7px; vertical-align: middle;
  }}
  .badge {{
    color: #fff; font-size: 11px; font-weight: 600; padding: 4px 10px;
    border-radius: 999px; text-transform: uppercase; letter-spacing: .5px;
    white-space: nowrap;
  }}
  .legend {{
    background: #ffffff; color: #000000; margin-top: 18px;
    border-radius: 12px; padding: 18px 20px;
    box-shadow: 0 6px 18px rgba(0,0,0,.25);
  }}
  .legend .legend-title {{
    font-size: 12px; text-transform: uppercase; letter-spacing: .8px;
    font-weight: 700; color: #000000; margin-bottom: 12px;
  }}
  .legend .legend-items {{
    display: flex; gap: 24px; font-size: 13px; align-items: center;
  }}
  .legend .dot {{ width: 11px; height: 11px; }}
  footer {{ color: #64748b; font-size: 12px; margin-top: 22px; text-align: center; }}
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>RPA Job Success Dashboard</h1>
      <div class="sub">Generated {escape(stamp)} &nbsp;&bull;&nbsp; Filter: {escape(filter_desc)}</div>
    </header>

    <div class="kpis">
      <div class="kpi">
        <div class="label">Unique Automations</div>
        <div class="value">{analysis.unique_automations}</div>
      </div>
      <div class="kpi">
        <div class="label">Total Jobs</div>
        <div class="value">{analysis.total_jobs}</div>
      </div>
      <div class="kpi">
        <div class="label">Overall Success</div>
        <div class="value" style="color:{overall_color};">{analysis.overall_success_pct:.1f}%</div>
      </div>
      <div class="kpi">
        <div class="label">Processes On Target</div>
        <div class="value" style="color:{SUCCESS_GREEN};">{analysis.healthy_count}</div>
      </div>
      <div class="kpi">
        <div class="label">Processes At Risk</div>
        <div class="value" style="color:{SUCCESS_RED};">{analysis.at_risk_count}</div>
      </div>
    </div>

    <div class="card">
      <table>
        <thead>
          <tr>
            <th>Process (ReleaseName)</th>
            {state_headers}
            <th>Total</th>
            <th>Success %</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>{''.join(rows)}
        </tbody>
      </table>
    </div>

    <div class="legend">
      <div class="legend-title">Legend</div>
      <div class="legend-items">
        <span><span class="dot" style="background:{SUCCESS_GREEN};"></span>Success % &ge; {threshold:.0f}% (On Target)</span>
        <span><span class="dot" style="background:{SUCCESS_RED};"></span>Success % &lt; {threshold:.0f}% (Needs Attention)</span>
      </div>
    </div>

    <footer>UiPath Orchestrator &mdash; Automated reporting</footer>
  </div>
</body>
</html>"""
