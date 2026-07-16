from collections import Counter
from core.forms import *
from core.utils import *
from django.contrib import messages
from django.db.models import Prefetch
from django.http import HttpResponse, HttpResponseBadRequest
from django.template.loader import render_to_string
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render, redirect
from django.views.generic import (
    ListView,
)
from core.commitments import (
    commitment_applies_to_project,
    commitment_applies_to_subproject,
    get_commitment_progress,
    reconcile_commitment,
)
from core.models import Projects, SubProjects, Sessions, Commitment
from core.services import SessionMutationService


ACTIVE_TIMER_FRAGMENT_TEMPLATES = {
    "dashboard": "core/partials/active_timers_dashboard.html",
    "home": "core/partials/active_timers_home.html",
    "timers": "core/partials/active_timers_timers.html",
}


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
            )
        )
        .only(
            "id",
            "project_id",
            "project__id",
            "project__name",
            "start_time",
            "end_time",
            "auto_stop_at",
            "is_active",
        )
        .order_by("-start_time")
    )
    timers = filter_by_active_context(timers, request)
    if surface in {"dashboard", "home"}:
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
            stop_after_amount = (request.POST.get("stop_after_amount") or "").strip()
            stop_after_unit = request.POST.get("stop_after_unit", "minutes")
            stop_after = (
                f"{stop_after_amount} {stop_after_unit}"
                if stop_after_amount
                else request.POST.get("stop_after")
            )
            stop_after_duration = parse_stop_after_duration(stop_after)

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
            session = SessionMutationService.create_session(
                user=request.user,
                project=project,
                start_time=start_time,
                auto_stop_at=(
                    start_time + stop_after_duration
                    if stop_after_duration
                    else None
                ),
                is_active=True,
                subprojects=list(subprojects),
            )
            messages.success(request, "Started timer")
            return redirect("timers")

        except ValueError as ve:
            messages.error(request, str(ve))
            return redirect("start_timer")

        except Exception as e:
            messages.error(
                request, f"An error occurred while starting the timer. Error: {e}"
            )
            return redirect("start_timer")

    context = {"title": "Start Timer"}

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
            post_data["start_time"] = timer.start_time.strftime("%Y-%m-%dT%H:%M")
        if not post_data.get("end_time"):
            post_data["end_time"] = timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M")

        form = StopTimerForm(post_data, instance=timer)
        if form.is_valid():
            candidate = form.save(commit=False)
            timer = SessionMutationService.mutate_session(
                timer.pk,
                user=request.user,
                start_time=candidate.start_time,
                end_time=candidate.end_time,
                note=candidate.note,
                is_active=False,
                auto_stop_at=None,
            )
            messages.success(request, "Stopped timer")
            return redirect("timers")

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
        qs = Sessions.objects.filter(end_time__isnull=True, user=self.request.user)
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
):
    subprojects = list(subprojects)
    return {
        "kind": kind,
        "icon": icon,
        "title": title,
        "detail": detail,
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
        suggestions.append(
            _build_timer_suggestion(
                kind="recent",
                icon="fa-history",
                title=session.project.name,
                detail=f"Last used {ended_at.strftime('%b %d, %H:%M')}",
                project=session.project,
                subprojects=session.subprojects.all(),
                metric="recent",
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
