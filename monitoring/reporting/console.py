"""Console reporting backend.

Renders a :class:`~monitoring.analytics.JobAnalysis` as an aligned text table
for the terminal. It reads only from the domain model, never from the raw API,
so it stays decoupled from how the data was fetched.
"""

from __future__ import annotations

from ..analytics import JobAnalysis


def render_console(analysis: JobAnalysis) -> str:
    """Render the ReleaseName x State matrix as an aligned, printable string."""
    states = analysis.states
    releases = analysis.releases_by_volume()

    name_width = max(
        [len("ReleaseName")] + [len(r.release_name) for r in releases]
    )
    col_width = max([len("Success %")] + [len(s) for s in states]) + 2

    lines: list[str] = []
    header = "ReleaseName".ljust(name_width)
    header += "".join(s.rjust(col_width) for s in states)
    header += "Total".rjust(col_width)
    header += "Success %".rjust(col_width)
    lines.append(header)
    lines.append("-" * len(header))

    for r in releases:
        row = r.release_name.ljust(name_width)
        row += "".join(
            str(r.state_counts.get(s, 0)).rjust(col_width) for s in states
        )
        row += str(r.total).rjust(col_width)
        row += f"{r.success_pct:.1f}%".rjust(col_width)
        lines.append(row)

    return "\n".join(lines)
