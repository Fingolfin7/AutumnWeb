from collections import Counter
import logging
import os

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.template.loader import render_to_string
from django.utils import timezone
from datetime import datetime, timedelta
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings
from django.core.cache import cache
from django.shortcuts import get_object_or_404, render, redirect
from django.views.generic import (
    ListView,
)
from django.views.decorators.http import require_GET, require_POST
from core.commitments import (
    commitment_applies_to_project,
    commitment_applies_to_subproject,
    get_commitment_progress,
    reconcile_commitment,
)
from core.celebrations import (
    commitment_progress_for_project,
    crossed_tracked_time_milestone,
    format_tracked_time,
    newly_met_commitment,
    project_total_minutes,
)
from core.models import Projects, SubProjects, Sessions, Commitment, TimerReminder
from core.services import SessionMutationService
from core.services.reminders import create_timer_reminder
from core.views.allocations import parse_allocation_post
from core.forms import StopTimerForm
from core.utils import (
    filter_by_active_context,
    parse_stop_after_duration,
    stop_expired_timers,
)

try:
    # The service is optional at development time. A missing service must not
    # make the ordinary timer page or its deterministic suggestions fail.
    from core.services.jev_recommendations import rank_timer_candidates
    from core.services.jev_timer_context import (
        build_jev_candidates as build_rich_jev_candidates,
        build_jev_context as build_rich_jev_context,
        jev_cache_key as rich_jev_cache_key,
    )
except ImportError:  # pragma: no cover - exercised in deployments without Jev
    rank_timer_candidates = None
    build_rich_jev_candidates = None
    build_rich_jev_context = None
    rich_jev_cache_key = None


logger = logging.getLogger(__name__)


ACTIVE_TIMER_FRAGMENT_TEMPLATES = {
    "dashboard": "core/partials/active_timers_dashboard.html",
    "timers": "core/partials/active_timers_timers.html",
}


def _active_timer_reminder_prefetch():
    """Keep reminder rows on the active-card render to one related query."""
    return Prefetch(
        "reminders",
        queryset=TimerReminder.objects.filter(active=True)
        .only(
            "id",
            "session_id",
            "mode",
            "next_fire_at",
            "interval_seconds",
            "message",
            "last_fired_at",
        )
        .order_by("next_fire_at", "id"),
        to_attr="active_reminders",
    )


@login_required
def active_timers_fragment(request):
    """Render only the active-timer region used by the polling UI."""
    surface = request.GET.get("surface", "timers")
    template_name = ACTIVE_TIMER_FRAGMENT_TEMPLATES.get(surface)
    if template_name is None:
        return HttpResponseBadRequest("Unknown timer surface")

    stop_expired_timers(request.user)
    timers = (
        Sessions.objects.filter(end_time__isnull=True, user=request.user)
        .select_related("project")
        .prefetch_related(
            Prefetch(
                "subprojects",
                queryset=SubProjects.objects.only("id", "name"),
            ),
            _active_timer_reminder_prefetch(),
        )
        .only(
            "id",
            "project_id",
            "project__id",
            "project__name",
            "start_time",
            "end_time",
            "auto_stop_at",
            "notify_on_auto_stop",
            "note",
            "version",
        )
        .order_by("-start_time")
    )
    timers = filter_by_active_context(timers, request)
    if surface == "dashboard":
        timers = timers[:5]

    # These partials do not need request context processors. Avoiding them keeps
    # this five-second polling path limited to active-timer data.
    html = render_to_string(template_name, {"timers": timers})
    response = HttpResponse(html)
    response["Cache-Control"] = "no-store"
    return response


@login_required
def start_timer(request):
    if request.method == "POST":
        try:
            project_name = request.POST.get("project")
            subproject_names = request.POST.getlist("subprojects")
            auto_stop_enabled = (
                str(request.POST.get("auto_stop_enabled", "")).strip().lower()
                in {"1", "true", "on", "yes"}
            )
            stop_after_amount = (
                (request.POST.get("stop_after_amount") or "").strip()
                if auto_stop_enabled
                else ""
            )
            stop_after_unit = request.POST.get("stop_after_unit", "minutes")
            stop_after = None
            if auto_stop_enabled:
                stop_after = (
                    f"{stop_after_amount} {stop_after_unit}"
                    if stop_after_amount
                    else request.POST.get("stop_after")
                )
            stop_after_duration = parse_stop_after_duration(stop_after)

            reminder_mode = (request.POST.get("reminder_mode") or "none").strip().lower()
            if reminder_mode not in {"none", "after", "interval", "at"}:
                raise ValueError("Choose a valid reminder option.")
            reminder_at = None
            if reminder_mode == "at":
                reminder_at_value = (request.POST.get("reminder_at") or "").strip()
                if not reminder_at_value:
                    raise ValidationError({"at": "Choose a date and time for the reminder."})
                try:
                    reminder_at = datetime.fromisoformat(reminder_at_value)
                except ValueError as exc:
                    raise ValidationError({"at": "Enter a valid date and time for the reminder."}) from exc

            # Fetch the project
            project = Projects.objects.filter(
                name=project_name, user=request.user
            ).first()
            if not project:
                raise ValueError("Project not found")

            # Fetch all subprojects related to the project and in the list of submitted subproject names
            subprojects = SubProjects.objects.filter(
                name__in=subproject_names, parent_project=project, user=request.user
            )
            if not subprojects.exists() and len(subproject_names) > 0:
                raise ValueError("No subprojects found for the selected project")

            start_time = timezone.now()
            with transaction.atomic():
                session = SessionMutationService.create_session(
                    user=request.user,
                    project=project,
                    start_time=start_time,
                    auto_stop_at=(
                        start_time + stop_after_duration
                        if stop_after_duration
                        else None
                    ),
                    notify_on_auto_stop=(
                        str(request.POST.get("notify_on_auto_stop", ""))
                        .strip()
                        .lower()
                        in {"1", "true", "on", "yes"}
                    ),
                    is_active=True,
                    subprojects=list(subprojects),
                )
                if reminder_mode != "none":
                    create_timer_reminder(
                        user=request.user,
                        session=session,
                        mode=reminder_mode,
                        amount=request.POST.get("reminder_amount"),
                        unit=request.POST.get("reminder_unit"),
                        at_local=reminder_at,
                        message=request.POST.get("reminder_message", ""),
                    )
            messages.success(request, "Started timer")
            return redirect("timers")

        except ValueError as ve:
            messages.error(request, str(ve))
            return redirect("start_timer")

        except ValidationError as ve:
            if hasattr(ve, "message_dict"):
                error_text = " ".join(
                    str(message)
                    for messages_for_field in ve.message_dict.values()
                    for message in messages_for_field
                )
            else:
                error_text = str(ve)
            messages.error(request, error_text or "Please correct the reminder details.")
            return redirect("start_timer")

        except Exception as e:
            messages.error(
                request, f"An error occurred while starting the timer. Error: {e}"
            )
            return redirect("start_timer")

    # Notification action links may prefill a project and subproject.  Resolve
    # them only for this authenticated owner and only on GET; no timer state is
    # changed until the ordinary POST form is submitted.
    initial_project = None
    initial_subprojects = []
    try:
        project_id = int((request.GET.get("project_id") or "").strip())
    except (TypeError, ValueError):
        project_id = None
    if project_id:
        initial_project = Projects.objects.filter(
            pk=project_id, user=request.user
        ).first()
    if initial_project:
        subproject_ids = set()
        for raw in request.GET.getlist("subproject_id"):
            try:
                subproject_ids.add(int(str(raw).strip()))
            except (TypeError, ValueError):
                continue
        if subproject_ids:
            initial_subprojects = list(
                SubProjects.objects.filter(
                    pk__in=subproject_ids,
                    user=request.user,
                    parent_project=initial_project,
                ).order_by("pk")
            )
    context = {
        "title": "Start Timer",
        "initial_project": initial_project,
        "initial_subprojects": initial_subprojects,
    }

    return render(request, "core/start_timer.html", context)


@login_required
def stop_timer(request, session_id: int):
    stop_expired_timers(request.user)
    timer = get_object_or_404(Sessions, id=session_id, user=request.user)
    if not timer.is_active:
        messages.info(request, "That timer has already stopped.")
        return redirect("timers")

    if request.method == "POST":
        post_data = request.POST.copy()

        # Backward-compatibility with previous payloads/tests that posted `session_note`.
        if "note" not in post_data and "session_note" in post_data:
            post_data["note"] = post_data.get("session_note", "")

        # Maintain legacy behavior where POSTing without explicit date/time still stops immediately.
        if not post_data.get("start_time"):
            post_data["start_time"] = timezone.localtime(timer.start_time).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
        if not post_data.get("end_time"):
            post_data["end_time"] = timezone.localtime(timezone.now()).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )

        form = StopTimerForm(post_data, instance=timer)
        if form.is_valid():
            try:
                # Snapshot derived progress before the active session becomes
                # completed. The same reference instant makes the comparison
                # a true crossing check, rather than a page-load effect.
                celebration_reference = timezone.now()
                before_total_minutes = project_total_minutes(
                    request.user, timer.project_id
                )
                before_commitments = commitment_progress_for_project(
                    request.user,
                    timer.project,
                    reference_instant=celebration_reference,
                )
                allocations = parse_allocation_post(
                    request.POST, list(timer.subprojects.all())
                )
                candidate = form.save(commit=False)
                with transaction.atomic():
                    timer = SessionMutationService.mutate_session(
                        timer.pk,
                        user=request.user,
                        start_time=candidate.start_time,
                        end_time=candidate.end_time,
                        note=candidate.note,
                        is_active=False,
                        auto_stop_at=None,
                    )
                    if allocations is not None:
                        timer = SessionMutationService.set_allocations(
                            timer.pk,
                            user=request.user,
                            allocations=allocations,
                        )
                after_total_minutes = project_total_minutes(
                    request.user, timer.project_id
                )
                after_commitments = commitment_progress_for_project(
                    request.user,
                    timer.project,
                    reference_instant=celebration_reference,
                )
                newly_met = newly_met_commitment(
                    before_commitments, after_commitments
                )
                crossed_milestone = crossed_tracked_time_milestone(
                    before_total_minutes, after_total_minutes
                )
                if newly_met is not None:
                    messages.success(
                        request,
                        f"Stopped timer — commitment met: {newly_met.target_name}.",
                        extra_tags="celebration celebration-progress",
                    )
                elif crossed_milestone is not None:
                    messages.success(
                        request,
                        (
                            f"Stopped timer — {timer.project.name} reached "
                            f"{format_tracked_time(crossed_milestone)} tracked."
                        ),
                        extra_tags="celebration celebration-progress",
                    )
                else:
                    messages.success(request, "Stopped timer")
                return redirect("timers")
            except ValueError as exc:
                form.add_error(None, str(exc))

        messages.error(request, "Please correct the errors below.")
    else:
        form = StopTimerForm(
            instance=timer,
            initial={
                "end_time": timezone.now(),
            },
        )

    context = {"title": "Stop Timer", "timer": timer, "form": form}

    return render(request, "core/stop_timer.html", context)


@login_required
@require_POST
def update_timer_note(request, session_id: int):
    timer = get_object_or_404(Sessions, id=session_id, user=request.user)
    if timer.end_time is not None:
        return JsonResponse(
            {"error": "Only active timer notes can be updated."}, status=409
        )
    timer = SessionMutationService.mutate_session(
        timer.pk,
        user=request.user,
        note=request.POST.get("note") or None,
    )
    return JsonResponse({"note": timer.note or "", "version": timer.version})


@login_required
def restart_timer(request, session_id: int):
    stop_expired_timers(request.user)
    timer = get_object_or_404(Sessions, id=session_id, user=request.user)

    restart_time = timezone.now()
    auto_stop_duration = None
    if timer.auto_stop_at and timer.start_time and timer.auto_stop_at > timer.start_time:
        auto_stop_duration = timer.auto_stop_at - timer.start_time

    timer = SessionMutationService.mutate_session(
        timer.pk,
        user=request.user,
        start_time=restart_time,
        end_time=None,
        is_active=True,
        auto_stop_at=(
            restart_time + auto_stop_duration if auto_stop_duration else None
        ),
    )
    messages.success(request, "Restarted timer")

    return redirect("timers")


@login_required
def remove_timer(request, session_id: int):
    timer = get_object_or_404(Sessions, id=session_id, user=request.user)

    if request.method == "POST":
        SessionMutationService.delete_session(timer.pk, user=request.user)
        messages.success(request, "Removed timer")
        return redirect("timers")

    context = {"title": "Remove Timer", "timer": timer}

    return render(request, "core/remove_timer.html", context)


class TimerListView(LoginRequiredMixin, ListView):
    model = Sessions
    template_name = "core/timers.html"
    context_object_name = "timers"
    ordering = ["-start_time"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Timers"
        context["timer_suggestions"] = build_timer_suggestions(
            self.request.user, self.request
        )

        return context

    def get_queryset(self):
        stop_expired_timers(self.request.user)
        qs = (
            Sessions.objects.filter(end_time__isnull=True, user=self.request.user)
            .select_related("project")
            .prefetch_related(
                Prefetch(
                    "subprojects",
                    queryset=SubProjects.objects.only("id", "name"),
                ),
                _active_timer_reminder_prefetch(),
            )
            .only(
                "id",
                "project_id",
                "project__id",
                "project__name",
                "start_time",
                "end_time",
                "auto_stop_at",
                "notify_on_auto_stop",
                "note",
                "version",
            )
        )
        # Respect active context (timers only for projects in the active context)
        return filter_by_active_context(qs, self.request)


def _timer_combo_key(project, subprojects):
    sub_ids = tuple(sorted(subproject.id for subproject in subprojects))
    return project.id, sub_ids


def _session_combo_key(session):
    return _timer_combo_key(session.project, list(session.subprojects.all()))


def _build_timer_suggestion(
    *,
    kind,
    icon,
    title,
    detail,
    project,
    subprojects,
    metric=None,
    progress=None,
    jev_detail=None,
):
    subprojects = list(subprojects)
    return {
        "kind": kind,
        "icon": icon,
        "title": title,
        "detail": detail,
        "jev_detail": jev_detail or detail,
        "project": project,
        "subprojects": subprojects,
        "subproject_names": [subproject.name for subproject in subprojects],
        "metric": metric,
        "progress": progress,
        "key": _timer_combo_key(project, subprojects),
    }


def _timer_recent_suggestions(recent_sessions, active_keys, limit=4):
    suggestions = []
    seen = set()

    for session in recent_sessions:
        key = _session_combo_key(session)
        if key in seen or key in active_keys:
            continue

        seen.add(key)
        ended_at = timezone.localtime(session.end_time)
        days_ago = max((timezone.localdate() - ended_at.date()).days, 0)
        if days_ago == 0:
            jev_detail = "Used today"
        elif days_ago == 1:
            jev_detail = "Used yesterday"
        else:
            jev_detail = f"Used {days_ago} days ago"
        suggestions.append(
            _build_timer_suggestion(
                kind="recent",
                icon="fa-history",
                title=session.project.name,
                detail=f"Last used {ended_at.strftime('%b %d, %H:%M')}",
                project=session.project,
                subprojects=session.subprojects.all(),
                metric="recent",
                jev_detail=jev_detail,
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

        key = _session_combo_key(session)
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
                detail=(
                    f"{count} matching session{plural} near "
                    f"{hour_label} on {day_name}s"
                ),
                project=session.project,
                subprojects=session.subprojects.all(),
                metric=f"{count}x",
                jev_detail=(
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
            subproject
            for subproject in session.subprojects.all()
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
            .select_related("context")
            .prefetch_related("tags"),
            request,
        )
    )
    suggestions = []
    seen = set()

    commitments = (
        Commitment.objects.filter(user=user, active=True)
        .select_related(
            "project",
            "subproject",
            "subproject__parent_project",
            "context",
            "tag",
        )
        .prefetch_related(
            "include_projects",
            "exclude_projects",
            "include_subprojects",
            "exclude_subprojects",
            "include_contexts",
            "exclude_contexts",
            "include_tags",
            "exclude_tags",
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

        key = _timer_combo_key(project, subprojects)
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
                jev_detail=(
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
        .select_related("project")
        .prefetch_related("subprojects"),
        request,
    )
    active_keys = {_session_combo_key(timer) for timer in active_timers}

    recent_sessions_qs = filter_by_active_context(
        Sessions.objects.filter(
            user=user,
            end_time__isnull=False,
            end_time__gte=lookback_start,
        )
        .select_related("project")
        .prefetch_related("subprojects")
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


# Jev is an advisory layer on top of the deterministic suggestions. Keep its
# cache short and scoped to both the account and the exact candidate payload so
# one account's ranking can never leak into another account or an old timer
# state.
JEV_CACHE_TIMEOUT = 10 * 60


def _jev_api_key(user):
    """Resolve the account credential without exposing it to templates/logs."""
    profile = getattr(user, "profile", None)
    if profile is None or not getattr(profile, "ai_features_enabled", False):
        return None

    try:
        stored_key = profile.get_api_key("typesafe")
    except Exception:
        # Credential decryption failures should degrade to no Jev section.
        stored_key = None
    if stored_key:
        return stored_key
    # A local .env key is useful for development before the profile form has
    # been used, but production must always use the account-tied credential.
    if settings.DEBUG:
        return os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_KEY")
    return None


def _jev_candidate_id(project, subprojects):
    subproject_ids = ",".join(
        str(subproject_id)
        for subproject_id in sorted(subproject.id for subproject in subprojects)
    )
    return f"project:{project.id}:subprojects:{subproject_ids}"




def _jev_suggestions(user, request):
    api_key = _jev_api_key(user)
    if not api_key or rank_timer_candidates is None:
        return []

    if build_rich_jev_candidates is None or build_rich_jev_context is None:
        return []
    try:
        candidates = build_rich_jev_candidates(user, request)
        context = build_rich_jev_context(user, request, candidates)
    except Exception as exc:
        logger.warning(
            "Jev context unavailable category=%s",
            type(exc).__name__,
        )
        return []
    candidate_map = {candidate["id"]: candidate for candidate in candidates}
    cache_key = rich_jev_cache_key(user, request, candidates, context) + ":scores-v1"
    cached = cache.get(cache_key, None)
    if cached is None:
        try:
            result = rank_timer_candidates(
                api_key=api_key,
                candidates=candidates,
                context=context,
            )
        except Exception as exc:
            # Jev is optional advice; deterministic groups must remain usable.
            logger.warning(
                "Jev recommendation unavailable category=%s",
                type(exc).__name__,
            )
            return []
        rows = result.get("recommendations", []) if isinstance(result, dict) else []
        ranked_ids = []
        scores = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            candidate_id = row.get("candidate_id")
            candidate_key = str(candidate_id) if candidate_id is not None else ""
            if candidate_key in candidate_map and candidate_key not in ranked_ids:
                ranked_ids.append(candidate_key)
                scores[candidate_key] = row.get("score")
            if len(ranked_ids) >= 3:
                break
        cache.set(cache_key, {"ids": ranked_ids, "scores": scores}, JEV_CACHE_TIMEOUT)
    else:
        ranked_ids = cached["ids"]
        scores = cached["scores"]

    suggestions = []
    running_project_ids = set(
        Sessions.objects.filter(user=user, end_time__isnull=True).values_list(
            "project_id", flat=True
        )
    )
    for candidate_id in ranked_ids or []:
        candidate = candidate_map.get(candidate_id)
        if candidate is None:
            continue
        if candidate_id == "no_activity":
            suggestions.append({
                "kind": "jev", "title": "Start nothing for now",
                "no_activity": True, "jev_score": scores.get(candidate_id),
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
                user=user,
                parent_project=project,
                pk__in=candidate["subproject_ids"],
            ).order_by("pk")
        )
        if {sub.id for sub in subprojects} != set(candidate["subproject_ids"]):
            # The ranked combination changed while Jev was evaluating it.
            continue
        # Recheck the active-timer exclusion after the ranker returns. This
        # prevents a timer started while the request was in flight showing up.
        if project.id in running_project_ids:
            continue
        suggestions.append(
            _build_timer_suggestion(
                kind="jev",
                icon="fa-lightbulb",
                title=project.name,
                detail=(
                    f"Context: {candidate['reason']}"
                    if candidate.get("reason")
                    else ""
                ),
                project=project,
                subprojects=subprojects,
            )
        )
        suggestions[-1]["jev_score"] = scores.get(candidate_id)
        if len(suggestions) >= 3:
            break
    return suggestions


@login_required
@require_GET
def jev_timer_recommendations(request):
    """Progressive Jev HTML fragment for the authenticated timer owner."""
    suggestions = _jev_suggestions(request.user, request)
    if not suggestions:
        response = HttpResponse(status=204)
        response["Cache-Control"] = "no-store"
        return response
    html = render_to_string(
        "core/partials/jev_timer_recommendations.html",
        {"jev_suggestions": suggestions},
        request=request,
    )
    response = HttpResponse(html)
    response["Cache-Control"] = "no-store"
    return response
