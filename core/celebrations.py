"""Small, server-side decisions that make meaningful progress feel visible.

The UI owns the motion. This module only identifies transitions that are
already true in the write path, so an ordinary page load or save cannot create
an accidental celebration.
"""

from __future__ import annotations

from core.commitments import (
    commitment_applies_to_project,
    get_commitment_progress,
)
from core.models import Commitment, Projects
from core.totals import annotate_project_totals


# Minutes, rather than hours, keep the comparison exact while preserving the
# same derived-total semantics used by project pages and reports.
TRACKED_TIME_MILESTONES = (10 * 60, 25 * 60, 50 * 60, 100 * 60, 250 * 60)


def project_total_minutes(user, project_id) -> float:
    """Return one project's canonical completed-session total in minutes."""

    value = (
        annotate_project_totals(Projects.objects.filter(user=user, pk=project_id))
        .values_list("derived_total_time", flat=True)
        .first()
    )
    return float(value or 0)


def crossed_tracked_time_milestone(before_minutes, after_minutes):
    """Return the largest threshold crossed by a single completed session.

    A stop that jumps over more than one threshold gets one quiet moment, at
    the highest newly reached threshold. Re-stopping an already completed
    session cannot cross anything because the stop view only accepts active
    timers.
    """

    before = float(before_minutes or 0)
    after = float(after_minutes or 0)
    crossed = [
        threshold
        for threshold in TRACKED_TIME_MILESTONES
        if before < threshold <= after
    ]
    return max(crossed) if crossed else None


def is_completion_transition(previous_status, next_status) -> bool:
    """Whether an edit moved a live project into its completed state."""

    return previous_status in {"active", "paused"} and next_status == "complete"


def commitment_progress_for_project(user, project, *, reference_instant=None):
    """Snapshot applicable active commitment percentages for one project."""

    commitments = (
        Commitment.objects.filter(user=user, active=True)
        .select_related("project", "subproject", "context", "tag")
        .order_by("pk")
    )
    snapshots = {}
    for commitment in commitments:
        if commitment_applies_to_project(commitment, project):
            snapshots[commitment.pk] = {
                "commitment": commitment,
                "percentage": float(
                    get_commitment_progress(
                        commitment, reference_instant=reference_instant
                    ).get("percentage")
                    or 0
                ),
            }
    return snapshots


def newly_met_commitment(before, after):
    """Return the first commitment that crossed 100% between two snapshots."""

    for commitment_id in sorted(after):
        current = after[commitment_id]
        previous = before.get(commitment_id)
        if previous and previous["percentage"] < 100 <= current["percentage"]:
            return current["commitment"]
    return None


def format_tracked_time(minutes) -> str:
    """Compact, readable copy for a celebration message."""

    total = max(0, int(round(float(minutes or 0))))
    hours, remainder = divmod(total, 60)
    if hours and remainder:
        return f"{hours}h {remainder}m"
    if hours:
        return f"{hours}h"
    return f"{remainder}m"
