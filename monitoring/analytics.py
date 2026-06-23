"""Analytics: turn raw Orchestrator job data into a reporting-ready model.

This layer is *pure* — it performs no I/O and has no knowledge of HTTP, the
console, or HTML. It consumes the raw OData payload and produces a stable
domain model (``JobAnalysis``) that every reporting backend renders. Because
the model is the contract between "compute" and "present", new outputs (CSV,
Slack, e-mail) can be added without touching this file, and this file can be
unit-tested with plain dictionaries.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

UNKNOWN = "(unknown)"


@dataclass(frozen=True)
class ReleaseStats:
    """Per-process (ReleaseName) state breakdown and derived health metrics."""

    release_name: str
    state_counts: dict[str, int]
    success_threshold: float

    @property
    def total(self) -> int:
        return sum(self.state_counts.values())

    @property
    def successful(self) -> int:
        return self.state_counts.get("Successful", 0)

    @property
    def success_pct(self) -> float:
        return (self.successful / self.total * 100) if self.total else 0.0

    @property
    def is_healthy(self) -> bool:
        return self.success_pct >= self.success_threshold


@dataclass(frozen=True)
class JobAnalysis:
    """Aggregated, presentation-agnostic view of a batch of jobs."""

    releases: list[ReleaseStats]
    states: list[str]
    total_jobs: int
    success_threshold: float

    @property
    def unique_automations(self) -> int:
        return len(self.releases)

    @property
    def grand_total(self) -> int:
        return sum(r.total for r in self.releases)

    @property
    def grand_successful(self) -> int:
        return sum(r.successful for r in self.releases)

    @property
    def overall_success_pct(self) -> float:
        return (
            self.grand_successful / self.grand_total * 100
            if self.grand_total
            else 0.0
        )

    @property
    def healthy_count(self) -> int:
        return sum(1 for r in self.releases if r.is_healthy)

    @property
    def at_risk_count(self) -> int:
        return self.unique_automations - self.healthy_count

    def releases_by_volume(self) -> list[ReleaseStats]:
        """Releases sorted by total job volume, descending."""
        return sorted(self.releases, key=lambda r: -r.total)


def analyze_jobs(payload: dict, success_threshold: float) -> JobAnalysis:
    """Build a :class:`JobAnalysis` from a raw Orchestrator OData payload.

    Cross-tabulates jobs by ReleaseName x State, missing values falling back to
    ``"(unknown)"``.

    Args:
        payload: The decoded OData response (expects a ``value`` list).
        success_threshold: Percent at/above which a process counts as healthy.
    """
    table: dict[str, Counter] = {}
    states: set[str] = set()

    jobs = payload.get("value", [])
    for job in jobs:
        release_name = job.get("ReleaseName") or UNKNOWN
        state = job.get("State") or UNKNOWN
        states.add(state)
        table.setdefault(release_name, Counter())[state] += 1

    releases = [
        ReleaseStats(
            release_name=name,
            state_counts=dict(counts),
            success_threshold=success_threshold,
        )
        for name, counts in table.items()
    ]

    return JobAnalysis(
        releases=releases,
        states=sorted(states),
        total_jobs=len(jobs),
        success_threshold=success_threshold,
    )
