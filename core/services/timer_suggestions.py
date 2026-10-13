from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
import logging

from django.utils import timezone

from core.commitments import (
    commitment_applies_to_project,
    commitment_applies_to_subproject,
    get_commitment_progress,
    reconcile_commitment,
)
from core.models import Commitment, Projects, Sessions, SubProjects
from core.services.timer_recommendation_context import (
    build_recommendation_candidates,
    build_recommendation_context,
    recommendation_cache_key,
)
from core.utils import filter_by_active_context, get_active_context


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LunaSuggestionResult:
    suggestions: list[dict]
    pending: bool = False
    advice_status: str = "No options met Luna's recommendation threshold right now."


def timer_combo_key(project, subprojects):
    sub_ids = tuple(sorted(subproject.id for subproject in subprojects))
    return project.id, sub_ids


def session_combo_key(session):
    return timer_combo_key(session.project, list(session.subprojects.all()))


def _build_timer_suggestion(
    *, kind, icon, title, detail, project, subprojects, metric=None,
    progress=None, recommendation_detail=None,
):
    subprojects = list(subprojects)
    return {
        "kind": kind,
        "icon": icon,
        "title": title,
        "detail": detail,
        "recommendation_detail": recommendation_detail or detail,
        "project": project,
        "subprojects": subprojects,
        "subproject_names": [subproject.name for subproject in subprojects],
        "metric": metric,
        "progress": progress,
        "key": timer_combo_key(project, subprojects),
    }


def _timer_recent_suggestions(recent_sessions, active_keys, limit=4):
    suggestions = []
    seen = set()
    for session in recent_sessions:
        key = session_combo_key(session)
        if key in seen or key in active_keys:
            continue
        seen.add(key)
        ended_at = timezone.localtime(session.end_time)
        days_ago = max((timezone.localdate() - ended_at.date()).days, 0)
        if days_ago == 0:
            recommendation_detail = "Used today"
        elif days_ago == 1:
            recommendation_detail = "Used yesterday"
        else:
            recommendation_detail = f"Used {days_ago} days ago"
        suggestions.append(
            _build_timer_suggestion(
                kind="recent",
                icon="fa-history",
                title=session.project.name,
                detail=f"Last used {ended_at.strftime('%b %d, %H:%M')}",
                project=session.project,
                subprojects=session.subprojects.all(),
                metric="recent",
                recommendation_detail=recommendation_detail,
            )
        )
        if len(suggestions) >= limit:
            break
    return suggestions


def _timer_habit_suggestions(recent_sessions, active_keys, now, limit=3):
    now_local = timezone.localtime(now)
    habit_counts = Counter()
    habit_latest = {}
    habit_sessions = {}
    for session in recent_sessions:
        if not session.start_time:
            continue
        started_at = timezone.localtime(session.start_time)
        if started_at.weekday() != now_local.weekday():
            continue
        hour_gap = abs(started_at.hour - now_local.hour)
        hour_gap = min(hour_gap, 24 - hour_gap)
        if hour_gap > 2:
            continue
        key = session_combo_key(session)
        if key in active_keys:
            continue
        habit_counts[key] += 1
        habit_latest[key] = max(
            habit_latest.get(key, session.start_time), session.start_time
        )
        habit_sessions[key] = session

    ranked_keys = sorted(
        habit_counts,
        key=lambda key: (habit_counts[key], habit_latest[key]),
        reverse=True,
    )
    suggestions = []
    day_name = now_local.strftime("%A")
    hour_label = now_local.strftime("%H:%M")
    for key in ranked_keys[:limit]:
        session = habit_sessions[key]
        count = habit_counts[key]
        plural = "s" if count != 1 else ""
        suggestions.append(
            _build_timer_suggestion(
                kind="habit",
                icon="fa-calendar-day",
                title=session.project.name,
                detail=f"{count} matching session{plural} near {hour_label} on {day_name}s",
                project=session.project,
                subprojects=session.subprojects.all(),
                metric=f"{count}x",
                recommendation_detail=(
                    f"{count} matching session{plural} within the same weekday "
                    "+/-2-hour window"
                ),
            )
        )
    return suggestions


def _commitment_remaining_label(progress):
    remaining = max(progress["target"] - progress["actual"], 0)
    if progress["commitment_type"] == "time":
        return f"{round(remaining)} min remaining"
    return f"{round(remaining)} session{'s' if remaining != 1 else ''} remaining"


def _pick_commitment_timer_combo(commitment, recent_sessions, available_projects):
    available_project_ids = {project.id for project in available_projects}
    if commitment.aggregation_type == "project" and commitment.project_id:
        if commitment.project_id in available_project_ids:
            return commitment.project, []
        return None, []
    if commitment.aggregation_type == "subproject" and commitment.subproject_id:
        project = commitment.subproject.parent_project
        if project.id in available_project_ids:
            return project, [commitment.subproject]
        return None, []
    for session in recent_sessions:
        if session.project_id not in available_project_ids:
            continue
        if not commitment_applies_to_project(commitment, session.project):
            continue
        subprojects = [
            subproject for subproject in session.subprojects.all()
            if commitment_applies_to_subproject(commitment, subproject)
        ]
        return session.project, subprojects
    for project in available_projects:
        if commitment_applies_to_project(commitment, project):
            return project, []
    return None, []


def _timer_commitment_suggestions(
    user, request, recent_sessions, active_keys, limit=4
):
    available_projects = list(
        filter_by_active_context(
            Projects.objects.filter(user=user, status="active")
            .select_related("context").prefetch_related("tags"),
            request,
        )
    )
    suggestions = []
    seen = set()
    commitments = (
        Commitment.objects.filter(user=user, active=True)
        .select_related(
            "project", "subproject", "subproject__parent_project", "context", "tag"
        )
        .prefetch_related(
            "include_projects", "exclude_projects", "include_subprojects",
            "exclude_subprojects", "include_contexts", "exclude_contexts",
            "include_tags", "exclude_tags",
        )
    )
    commitment_items = []
    for commitment in commitments:
        reconcile_commitment(commitment)
        progress = get_commitment_progress(commitment)
        if progress["actual"] >= progress["target"]:
            continue
        commitment_items.append((commitment, progress))
    commitment_items.sort(key=lambda item: item[1]["percentage"])

    for commitment, progress in commitment_items:
        project, subprojects = _pick_commitment_timer_combo(
            commitment, recent_sessions, available_projects
        )
        if project is None:
            continue
        key = timer_combo_key(project, subprojects)
        if key in seen or key in active_keys:
            continue
        seen.add(key)
        period_end = timezone.localtime(progress["period_end"]).strftime("%b %d")
        days_remaining = max(
            (timezone.localtime(progress["period_end"]).date() - timezone.localdate()).days,
            0,
        )
        suggestions.append(
            _build_timer_suggestion(
                kind="commitment",
                icon="fa-bullseye",
                title=commitment.target_name,
                detail=f"{_commitment_remaining_label(progress)} by {period_end}",
                project=project,
                subprojects=subprojects,
                metric=f"{progress['percentage']}%",
                progress=progress,
                recommendation_detail=(
                    f"{_commitment_remaining_label(progress)} with "
                    f"{days_remaining} days remaining"
                ),
            )
        )
        if len(suggestions) >= limit:
            break
    return suggestions


def build_timer_suggestions(user, request):
    now = timezone.now()
    lookback_start = now - timedelta(days=90)
    active_timers = filter_by_active_context(
        Sessions.objects.filter(user=user, end_time__isnull=True)
        .select_related("project").prefetch_related("subprojects"),
        request,
    )
    active_keys = {session_combo_key(timer) for timer in active_timers}
    recent_sessions_qs = filter_by_active_context(
        Sessions.objects.filter(
            user=user, end_time__isnull=False, end_time__gte=lookback_start
        )
        .select_related("project").prefetch_related("subprojects")
        .order_by("-end_time"),
        request,
    )
    recent_sessions = list(recent_sessions_qs[:200])
    return {
        "commitments": _timer_commitment_suggestions(
            user, request, recent_sessions, active_keys
        ),
        "habits": _timer_habit_suggestions(recent_sessions, active_keys, now),
        "recent": _timer_recent_suggestions(recent_sessions, active_keys),
    }


def recommendation_candidate_id(project, subprojects):
    subproject_ids = ",".join(
        str(subproject_id)
        for subproject_id in sorted(subproject.id for subproject in subprojects)
    )
    return f"project:{project.id}:subprojects:{subproject_ids}"


def build_luna_suggestions(user, request):
    from core.services.luna_recommendations import LUNA_MODEL, rank_luna_candidates
    from core.services.recommendation_cache import (
        RecommendationPending, generation_in_progress, get_or_generate,
    )
    from users.codex_auth import get_profile_access_token

    profile = getattr(user, "profile", None)
    api_key = {}
    if profile and profile.ai_features_enabled:
        for name, resolve in (
            ("openai_chatgpt", lambda: get_profile_access_token(profile)),
            ("openai", lambda: profile.get_api_key("openai")),
        ):
            try:
                value = resolve()
                if value:
                    api_key[name] = value
            except Exception:
                pass
    if not api_key:
        return LunaSuggestionResult(
            suggestions=[],
            advice_status=(
                "Enable AI features and connect ChatGPT in Profile (or save an "
                "OpenAI API key) to see Luna's recommendations."
            ),
        )

    effort = profile.luna_recommendation_effort
    provider = "luna"
    try:
        selected_context, mode = get_active_context(request)
        scope = f"{mode}:{selected_context.id if selected_context else 'all'}"
        if generation_in_progress(user, provider, scope):
            return LunaSuggestionResult(suggestions=[], pending=True)
        candidates = build_recommendation_candidates(user, request)
        context = build_recommendation_context(user, request, candidates)
    except Exception as exc:
        logger.warning("Luna context unavailable category=%s", type(exc).__name__)
        return LunaSuggestionResult(
            suggestions=[], advice_status="Luna's context is unavailable right now."
        )

    candidate_map = {candidate["id"]: candidate for candidate in candidates}
    version = f"luna:{LUNA_MODEL}:{effort}:v4"
    cache_key = recommendation_cache_key(user, request, candidates, context) + version
    try:
        result = get_or_generate(
            user, provider, scope, cache_key,
            lambda: rank_luna_candidates(
                api_key=api_key, candidates=candidates, context=context, effort=effort
            ),
        )
    except RecommendationPending:
        return LunaSuggestionResult(suggestions=[], pending=True)
    except Exception as exc:
        logger.warning(
            "%s recommendation unavailable category=%s", provider, type(exc).__name__
        )
        return LunaSuggestionResult(
            suggestions=[],
            advice_status="Luna is unavailable right now. Try again on your next visit.",
        )

    rows = result.get("recommendations", []) if isinstance(result, dict) else []
    ranked_ids = []
    scores = {}
    explanations = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate_id = row.get("candidate_id")
        candidate_key = str(candidate_id) if candidate_id is not None else ""
        if candidate_key in candidate_map and candidate_key not in ranked_ids:
            ranked_ids.append(candidate_key)
            scores[candidate_key] = row.get("score")
            explanations[candidate_key] = " ".join(
                part for part in (row.get("reason", ""), row.get("next_step", "")) if part
            )
        if len(ranked_ids) >= 3:
            break

    suggestions = []
    running_project_ids = set(
        Sessions.objects.filter(user=user, end_time__isnull=True)
        .values_list("project_id", flat=True)
    )
    for candidate_id in ranked_ids:
        candidate = candidate_map.get(candidate_id)
        if candidate is None:
            continue
        if candidate_id == "no_activity":
            suggestions.append({
                "kind": "luna",
                "title": "Start nothing for now",
                "no_activity": True,
                "recommendation_score": scores.get(candidate_id),
                "detail": "No new timer. Leave this time open or continue what you're doing.",
            })
            continue
        project = Projects.objects.filter(
            user=user, pk=candidate["project_id"], status="active"
        ).first()
        if project is None:
            continue
        subprojects = list(
            SubProjects.objects.filter(
                user=user, parent_project=project,
                pk__in=candidate["subproject_ids"],
            ).order_by("pk")
        )
        if {sub.id for sub in subprojects} != set(candidate["subproject_ids"]):
            continue
        if project.id in running_project_ids:
            continue
        suggestions.append(
            _build_timer_suggestion(
                kind="luna", icon="fa-lightbulb", title=project.name,
                detail=f"Context: {candidate['reason']}" if candidate.get("reason") else "",
                project=project, subprojects=subprojects,
            )
        )
        suggestions[-1]["recommendation_score"] = scores.get(candidate_id)
        if len(suggestions) >= 3:
            break
    for suggestion in suggestions:
        candidate_id = (
            "no_activity" if suggestion.get("no_activity")
            else recommendation_candidate_id(suggestion["project"], suggestion["subprojects"])
        )
        suggestion["detail"] = explanations.get(
            candidate_id, suggestion.get("detail", "")
        )
    return LunaSuggestionResult(suggestions=suggestions)
