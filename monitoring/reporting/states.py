"""Canonical column order for job states, shared by every reporting backend.

This is a *presentation* concern, so it lives in the reporting layer: the
analytics model stays alphabetical and presentation-agnostic (see
:func:`~monitoring.analytics.analyze_jobs`), and each backend applies this
ordering when it lays out its columns. Nothing here changes any count, total or
percentage — only the left-to-right order the columns appear in.

The console table and the HTML dashboard both read this list, so the two stay
consistent by construction: the dashboard's JavaScript ``STATE_ORDER`` is
generated from :data:`STATE_ORDER` rather than being a second copy.
"""

from __future__ import annotations

from typing import Iterable

# Job-state columns in run-lifecycle order: in flight -> halted -> failed ->
# succeeded. Add a state here to give it a fixed position.
STATE_ORDER: tuple[str, ...] = ("Running", "Stopped", "Faulted", "Successful")


def order_states(states: Iterable[str]) -> list[str]:
    """Order ``states`` by :data:`STATE_ORDER`, keeping unlisted states.

    States named in :data:`STATE_ORDER` come first, in that order. Any state
    not listed (a new Orchestrator state appearing in the data) is appended
    afterwards in alphabetical order, so an unrecognised state still gets a
    column instead of silently disappearing from the report.

    Only states actually present in ``states`` are returned, so a report never
    grows an empty column for a state the data does not contain.
    """
    present = list(states)
    known = [s for s in STATE_ORDER if s in present]
    rest = sorted(s for s in present if s not in STATE_ORDER)
    return known + rest
