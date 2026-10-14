from core.celebrations import (
    commitment_progress_for_project,
    crossed_tracked_time_milestone,
    format_tracked_time,
    newly_met_commitment,
    project_total_minutes,
)
from core.models import Sessions


def capture_timer_stop_progress(user, timer, *, reference_instant):
    return {
        "total_minutes": project_total_minutes(user, timer.project_id),
        "commitments": commitment_progress_for_project(
            user, timer.project, reference_instant=reference_instant
        ),
    }


def timer_stop_celebration(user, timer, before, *, reference_instant):
    after = capture_timer_stop_progress(
        user, timer, reference_instant=reference_instant
    )
    newly_met = newly_met_commitment(before["commitments"], after["commitments"])
    if newly_met is not None:
        return {
            "kind": "progress",
            "message": f"Stopped timer — commitment met: {newly_met.target_name}.",
        }
    milestone = crossed_tracked_time_milestone(
        before["total_minutes"], after["total_minutes"]
    )
    if milestone is not None:
        return {
            "kind": "progress",
            "message": (
                f"Stopped timer — {timer.project.name} reached "
                f"{format_tracked_time(milestone)} tracked."
            ),
        }
    return None


def project_completion_celebration(user, project):
    total_minutes = project_total_minutes(user, project.pk)
    session_count = Sessions.objects.filter(
        user=user, project_id=project.pk, end_time__isnull=False
    ).count()
    if not session_count:
        return {"kind": "completion", "message": "Project complete — no sessions logged yet."}
    session_word = "session" if session_count == 1 else "sessions"
    return {
        "kind": "completion",
        "message": (
            f"Project complete — {format_tracked_time(total_minutes)} "
            f"tracked across {session_count} {session_word}."
        ),
    }
