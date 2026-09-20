"""Account-scoped rich context assembly for timer Jev recommendations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from django.utils import timezone

from core.commitments import get_commitment_evaluation
from core.models import Commitment, Projects, Sessions
from core.utils import filter_by_active_context, get_active_context

from .jev_recommendations import MAX_CANDIDATES


def _iso(value):
    return timezone.localtime(value).isoformat() if value else None


def _duration_minutes(session):
    if not session.start_time or not session.end_time:
        return None
    return round(max((session.end_time - session.start_time).total_seconds(), 0) / 60, 2)


def _safe_subprojects(session, subs):
    return [
        sub
        for sub in subs
        if sub.user_id == session.user_id and sub.parent_project_id == session.project_id
    ]


def _session_row(session):
    subs = _safe_subprojects(session, session.subprojects.all())
    return {
        "id": session.id,
        "project_id": session.project_id,
        "subproject_ids": [sub.id for sub in subs],
        "started_at": _iso(session.start_time),
        "ended_at": _iso(session.end_time),
        "duration_minutes": _duration_minutes(session),
        "note": session.note or "",
    }


def _timer_row(session, now):
    subs = _safe_subprojects(session, session.subprojects.all())
    elapsed = max((now - session.start_time).total_seconds(), 0) if session.start_time else 0
    return {
        "id": session.id,
        "project_id": session.project_id,
        "project_name": session.project.name,
        "subproject_ids": [sub.id for sub in subs],
        "subproject_names": [sub.name for sub in subs],
        "started_at": _iso(session.start_time),
        "elapsed_minutes": round(elapsed / 60, 2),
        "note": session.note or "",
    }


def _snapshot_ids(snapshot, field):
    return {
        value.get("id") if isinstance(value, dict) else value
        for value in (snapshot or {}).get(field, [])
    }


def revision_matches_candidate(revision, project, subproject_ids):
    """Mirror ``_revision_sessions_queryset`` for candidate eligibility."""
    if revision is None:
        return False
    target_id = revision.target_id
    aggregation = revision.aggregation_type
    subproject_ids = set(subproject_ids)
    if aggregation == "project" and project.id != target_id:
        return False
    if aggregation == "subproject" and target_id not in subproject_ids:
        return False
    if aggregation == "context" and project.context_id != target_id:
        return False
    project_tag_ids = {tag.id for tag in project.tags.all()}
    if aggregation == "tag" and target_id not in project_tag_ids:
        return False

    allowed = {
        "context": {"tag", "project", "subproject"},
        "tag": {"project", "subproject"},
        "project": {"subproject"},
        "subproject": set(),
    }.get(aggregation, set())
    dimensions = {
        "projects": ({project.id}, "project"),
        "subprojects": (subproject_ids, "subproject"),
        "contexts": ({project.context_id}, "context"),
        "tags": (project_tag_ids, "tag"),
    }
    for plural, (actual, singular) in dimensions.items():
        if singular not in allowed:
            continue
        includes = _snapshot_ids(revision.filters_snapshot, f"include_{plural}")
        excludes = _snapshot_ids(revision.filters_snapshot, f"exclude_{plural}")
        if includes and not actual.intersection(includes):
            return False
        if excludes and actual.intersection(excludes):
            return False
    return True


def _ytd_totals(user, project_ids, now):
    if not project_ids:
        return {}
    local_now = timezone.localtime(now)
    year_start = timezone.make_aware(
        datetime.combine(local_now.date().replace(month=1, day=1), datetime.min.time()),
        local_now.tzinfo,
    )
    sessions = (
        Sessions.objects.filter(
            user=user,
            project__user=user,
            project_id__in=project_ids,
            end_time__isnull=False,
            end_time__gte=year_start,
            end_time__lt=now,
        )
        .only("id", "project_id", "start_time", "end_time")
        .order_by("end_time", "id")
    )
    totals = {}
    for session in sessions:
        month = timezone.localtime(session.end_time).strftime("%Y-%m")
        item = totals.setdefault(session.project_id, {}).setdefault(
            month, {"session_count": 0, "duration_minutes": 0}
        )
        item["session_count"] += 1
        item["duration_minutes"] += _duration_minutes(session) or 0
    return {
        project_id: [{"month": month, **values} for month, values in sorted(months.items())]
        for project_id, months in totals.items()
    }


def _project_row(project, ytd):
    tags = list(project.tags.all())
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "status": project.status,
        "context": (
            {
                "id": project.context_id,
                "name": project.context.name if project.context else "",
                "description": project.context.description if project.context else "",
            }
            if project.context_id
            else None
        ),
        "tags": [{"id": tag.id, "name": tag.name} for tag in tags],
        "subprojects": [
            {"id": sub.id, "name": sub.name, "description": sub.description or ""}
            for sub in project.subprojects.all()
            if sub.user_id == project.user_id and sub.parent_project_id == project.id
        ],
        "ytd_monthly_totals": ytd.get(project.id, []),
    }


def _commitment_row(commitment, evaluation, candidates, projects_by_id, now):
    revision = evaluation.get("revision")
    eligible = []
    for candidate in candidates:
        project = projects_by_id.get(candidate["project_id"])
        if project and revision_matches_candidate(
            revision, project, candidate.get("subproject_ids", [])
        ):
            eligible.append(candidate["id"])
    remaining_seconds = max((evaluation["period_end"] - now).total_seconds(), 0)
    return {
        "id": commitment.id,
        "name": commitment.target_name,
        "aggregation_type": revision.aggregation_type if revision else commitment.aggregation_type,
        "target_name": revision.target_name if revision else commitment.target_name,
        "commitment_type": evaluation["commitment_type"],
        "period": evaluation["period"],
        "target": evaluation["target"],
        "actual": evaluation["actual"],
        "percentage": evaluation["percentage"],
        "status": evaluation["status"],
        "period_start": _iso(evaluation["period_start"]),
        "effective_period_start": _iso(evaluation["effective_period_start"]),
        "period_end": _iso(evaluation["period_end"]),
        "timezone": evaluation.get("timezone"),
        "time_remaining_seconds": round(remaining_seconds, 2),
        "time_remaining_minutes": round(remaining_seconds / 60, 2),
        "banking": {
            "enabled": evaluation["enabled"],
            "balance": evaluation["balance"],
            "banked_credit": evaluation["banked_credit"],
            "covered_actual": evaluation["covered_actual"],
            "covered": evaluation["covered"],
            "remaining": evaluation["remaining"],
        },
        "eligible_candidate_ids": eligible,
        "canonical_revision": (
            {
                "generation": revision.generation,
                "effective_from": _iso(revision.effective_from_instant),
                "aggregation_type": revision.aggregation_type,
                "target_id": revision.target_id,
                "filters_snapshot": revision.filters_snapshot,
            }
            if revision
            else None
        ),
    }


def build_jev_candidates(user, request):
    """Return active, selected-context candidates excluding all running projects."""
    from core.views.timers import (
        _jev_candidate_id,
        _session_combo_key,
        _timer_combo_key,
        build_timer_suggestions,
    )

    active_projects = list(
        filter_by_active_context(
            Projects.objects.filter(user=user, status="active")
            .select_related("context")
            .prefetch_related("tags", "subprojects"),
            request,
        )
    )
    active_project_ids = {project.id for project in active_projects}
    active_timers = list(
        Sessions.objects.filter(user=user, project__user=user, end_time__isnull=True)
        .select_related("project")
        .prefetch_related("subprojects")
    )
    running_projects = {timer.project_id for timer in active_timers}
    active_keys = {_session_combo_key(timer) for timer in active_timers}
    suggestions = build_timer_suggestions(user, request)
    candidates, by_key = [], {}

    def add_combo(project, subs, *, signal=None, reason=""):
        key = _timer_combo_key(project, subs)
        if key in active_keys or project.id in running_projects or key in by_key:
            if key in by_key and signal:
                if signal not in by_key[key]["signals"]:
                    by_key[key]["signals"].append(signal)
            return
        candidate = {
            "id": _jev_candidate_id(project, subs),
            "project_id": project.id,
            "project_name": project.name,
            "subproject_ids": [sub.id for sub in subs],
            "subprojects": [{"id": sub.id, "name": sub.name} for sub in subs],
            "context_reason": reason,
            "reason": reason,
            "signals": [signal] if signal else [],
        }
        candidates.append(candidate)
        by_key[key] = candidate
    for group_name in ("commitments", "habits", "recent"):
        for suggestion in suggestions[group_name]:
            project = suggestion["project"]
            if project.id not in active_project_ids or project.id in running_projects:
                continue
            subs = [
                sub
                for sub in (suggestion.get("subprojects") or [])
                if sub.user_id == user.id and sub.parent_project_id == project.id
            ]
            key = _timer_combo_key(project, subs)
            if key in active_keys:
                continue
            signal = {
                "kind": suggestion["kind"],
                "detail": suggestion.get("jev_detail") or suggestion.get("detail") or "",
                "metric": suggestion.get("metric"),
            }
            if key in by_key:
                by_key[key]["signals"].append(signal)
                continue
            reason = suggestion.get("detail") or ""
            candidate = {
                "id": _jev_candidate_id(project, subs),
                "project_id": project.id,
                "project_name": project.name,
                "subproject_ids": [sub.id for sub in subs],
                "subprojects": [{"id": sub.id, "name": sub.name} for sub in subs],
                "context_reason": reason,
                "reason": reason,
                "signals": [signal],
            }
            candidates.append(candidate)
            by_key[key] = candidate

    # Deterministic sections are intentionally small for the ordinary timer
    # page. Jev's candidate pool also considers every recent combo so a useful
    # subproject is not lost merely because it fell outside those UI limits.
    recent_start = timezone.now() - timedelta(days=30)
    active_by_id = {project.id: project for project in active_projects}
    for session in (
        filter_by_active_context(
            Sessions.objects.filter(
                user=user,
                project__user=user,
                end_time__isnull=False,
                end_time__gte=recent_start,
                end_time__lt=timezone.now(),
            )
            .select_related("project")
            .prefetch_related("subprojects")
            .order_by("-end_time", "-id"),
            request,
        )
    ):
        project = active_by_id.get(session.project_id)
        if project is None:
            continue
        subs = _safe_subprojects(session, session.subprojects.all())
        add_combo(
            project,
            subs,
            signal={"kind": "history", "detail": "Completed in the last 30 days", "metric": None},
        )

    # A fulfilled commitment is still useful context, and a subproject-only
    # commitment must remain eligible even if it has no recent session.
    commitments = Commitment.objects.filter(user=user, active=True).select_related(
        "project", "subproject", "context", "tag"
    )
    for commitment in commitments:
        evaluation = get_commitment_evaluation(commitment)
        revision = evaluation.get("revision")
        if revision is None:
            continue
        for project in active_projects:
            if revision_matches_candidate(revision, project, []):
                add_combo(
                    project,
                    [],
                    signal={
                        "kind": "commitment",
                        "detail": "Eligible for a tracked commitment",
                        "metric": None,
                    },
                )
            for sub in project.subprojects.all():
                if sub.user_id != user.id or sub.parent_project_id != project.id:
                    continue
                if revision_matches_candidate(revision, project, [sub.id]):
                    add_combo(
                        project,
                        [sub],
                        signal={
                            "kind": "commitment",
                            "detail": "Eligible for a tracked commitment",
                            "metric": None,
                        },
                    )

    for project in active_projects:
        if project.id in running_projects:
            continue
        key = _timer_combo_key(project, [])
        if key in active_keys or key in by_key:
            continue
        candidate = {
            "id": _jev_candidate_id(project, []),
            "project_id": project.id,
            "project_name": project.name,
            "subproject_ids": [],
            "subprojects": [],
            "context_reason": "",
            "reason": "",
            "signals": [{"kind": "active", "detail": "Active project", "metric": None}],
        }
        candidates.append(candidate)
        by_key[key] = candidate
    return candidates


def build_jev_context(user, request, candidates):
    """Build the account-wide rich state used to score selected-context candidates."""
    now = timezone.now()
    local_now = timezone.localtime(now)
    selected_context, mode = get_active_context(request)
    recent_start = now - timedelta(days=30)
    recent = list(
        Sessions.objects.filter(
            user=user,
            project__user=user,
            end_time__isnull=False,
            end_time__gte=recent_start,
            end_time__lte=now,
        )
        .select_related("project__context")
        .prefetch_related("project__tags", "subprojects")
        .order_by("-end_time", "-id")
    )
    recent_duration_minutes = round(
        sum(_duration_minutes(session) or 0 for session in recent), 2
    )
    candidate_project_ids = {candidate["project_id"] for candidate in candidates}
    recent_project_ids = {session.project_id for session in recent}
    missing = candidate_project_ids - recent_project_ids
    older = []
    if missing:
        seen = set()
        for session in (
            Sessions.objects.filter(
                user=user,
                project__user=user,
                project_id__in=missing,
                end_time__isnull=False,
                end_time__lt=recent_start,
            )
            .select_related("project__context")
            .prefetch_related("project__tags", "subprojects")
            .order_by("-end_time", "-id")
        ):
            if session.project_id not in seen:
                older.append(session)
                seen.add(session.project_id)

    running = list(
        Sessions.objects.filter(user=user, project__user=user, end_time__isnull=True)
        .select_related("project__context")
        .prefetch_related("project__tags", "subprojects")
        .order_by("start_time", "id")
    )
    commitments = []
    target_ids = set()
    for commitment in Commitment.objects.filter(user=user, active=True).select_related(
        "project", "subproject", "context", "tag"
    ).prefetch_related(
        "include_projects", "exclude_projects", "include_subprojects",
        "exclude_subprojects", "include_contexts", "exclude_contexts",
        "include_tags", "exclude_tags",
    ).order_by("id"):
        evaluation = get_commitment_evaluation(commitment, now)
        commitments.append((commitment, evaluation))
        if commitment.project_id:
            target_ids.add(commitment.project_id)
        if commitment.subproject_id:
            target_ids.add(commitment.subproject.parent_project_id)

    running_project_ids = {timer.project_id for timer in running}
    all_project_ids = candidate_project_ids | recent_project_ids | running_project_ids | {
        session.project_id for session in older
    } | target_ids
    project_rows = list(
        Projects.objects.filter(user=user, id__in=all_project_ids)
        .select_related("context")
        .prefetch_related("tags", "subprojects")
        .order_by("id")
    )
    projects_by_id = {project.id: project for project in project_rows}
    ytd = _ytd_totals(user, all_project_ids, now)
    commitment_rows = [
        _commitment_row(commitment, evaluation, candidates, projects_by_id, now)
        for commitment, evaluation in commitments
    ]
    links = {candidate["id"]: [] for candidate in candidates}
    for row in commitment_rows:
        for candidate_id in row["eligible_candidate_ids"]:
            links.setdefault(candidate_id, []).append(row["id"])
    for candidate in candidates:
        candidate["commitment_ids"] = links.get(candidate["id"], [])

    coverage = {
        "candidate_count_before_cap": len(candidates) + 1,
        "active_context_only": True,
        "running_projects_excluded": sorted(running_project_ids),
    }
    activity_limit = MAX_CANDIDATES - 1  # Reserve one place for starting nothing.
    omitted_count = max(len(candidates) - activity_limit, 0)
    if omitted_count:
        candidates.sort(
            key=lambda candidate: (
                not bool(candidate.get("commitment_ids")),
                not bool(candidate.get("signals")),
                candidate["id"],
            )
        )
        coverage["omitted_candidate_ids"] = [
            candidate["id"] for candidate in candidates[activity_limit:]
        ][:100]
        candidates[:] = candidates[:activity_limit]
    candidates.append({
        "id": "no_activity",
        "project_id": None,
        "project_name": "Start nothing for now",
        "subproject_ids": [],
        "subprojects": [],
        "reason": "Do not start a new tracked activity now. This can mean taking a break, leaving time unstructured, or continuing an already-running activity. It does not stop any timer. Evaluate this as a valid option using the same evidence and rubric; do not assume fatigue or free time when unknown.",
        "commitment_ids": [],
        "signals": [],
    })
    sent_ids = {candidate["id"] for candidate in candidates}
    for row in commitment_rows:
        row["eligible_candidate_ids"] = [
            candidate_id
            for candidate_id in row["eligible_candidate_ids"]
            if candidate_id in sent_ids
        ]
    coverage["candidate_count_sent"] = len(candidates)
    coverage["omitted_candidate_count"] = omitted_count

    return {
        "now": {
            "local_datetime": local_now.isoformat(),
            "local_date": local_now.date().isoformat(),
            "local_time": local_now.strftime("%H:%M:%S"),
            "weekday": local_now.strftime("%A"),
            "timezone": str(local_now.tzinfo),
            "cache_bucket": int(local_now.timestamp() // 600),
        },
        "active_context": {
            "id": selected_context.id if selected_context else None,
            "name": selected_context.name if selected_context else "all",
            "mode": mode,
        },
        "history_coverage": {
            "requested_days": 30,
            "from_inclusive": _iso(recent_start),
            "to_exclusive": _iso(now),
            "query_complete": True,
            "notes_truncated": False,
            "recent_completed_sessions_before_budget": len(recent),
            "older_latest_sessions_before_budget": len(older),
            "recent_duration_minutes": recent_duration_minutes,
        },
        "projects": [_project_row(project, ytd) for project in project_rows],
        "commitments": commitment_rows,
        "recent_completed_sessions": [_session_row(session) for session in recent],
        "older_latest_sessions": [_session_row(session) for session in older],
        "running_timers": [_timer_row(timer, now) for timer in running],
        "candidate_coverage": coverage,
    }


def jev_cache_key(user, request, candidates, context):
    """Fingerprint rich state while bucketing volatile clock/elapsed values."""
    cache_context = json.loads(
        json.dumps(context, ensure_ascii=False, separators=(",", ":"), default=str)
    )
    now_data = cache_context.get("now", {})
    now_data.pop("local_datetime", None)
    now_data.pop("local_time", None)
    history = cache_context.get("history_coverage", {})
    history.pop("from_inclusive", None)
    history.pop("to_exclusive", None)
    for timer in cache_context.get("running_timers", []):
        if "elapsed_minutes" in timer:
            timer["elapsed_minutes"] = int(float(timer["elapsed_minutes"]) // 10) * 10
    for commitment in cache_context.get("commitments", []):
        commitment.pop("time_remaining_seconds", None)
        if "time_remaining_minutes" in commitment:
            commitment["time_remaining_minutes"] = int(
                float(commitment["time_remaining_minutes"]) // 10
            ) * 10
    digest = hashlib.sha256(
        json.dumps(
            {"candidates": candidates, "context": cache_context},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    selected = context.get("active_context") or {}
    return (
        f"jev-timers:v2:{user.id}:{selected.get('mode', 'all')}:"
        f"{selected.get('id') or 'all'}:{digest}"
    )
