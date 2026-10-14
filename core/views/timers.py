from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.template.loader import render_to_string
from django.utils import timezone
from datetime import datetime
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render, redirect
from django.views.generic import (
    ListView,
)
from django.views.decorators.http import require_GET, require_POST
from core.models import Projects, SubProjects, Sessions, TimerReminder
from core.services import SessionMutationService, timer_suggestions
from core.services.celebrations import (
    capture_timer_stop_progress,
    timer_stop_celebration,
)
from core.services.reminders import create_timer_reminder
from core.views.allocations import parse_allocation_post
from core.forms import StopTimerForm
from core.utils import (
    filter_by_active_context,
    parse_stop_after_duration,
    stop_expired_timers,
)



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
                before_progress = capture_timer_stop_progress(
                    request.user, timer,
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
                celebration = timer_stop_celebration(
                    request.user, timer, before_progress,
                    reference_instant=celebration_reference,
                )
                if celebration is not None:
                    messages.success(
                        request,
                        celebration["message"],
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
        context["timer_suggestions"] = timer_suggestions.build_timer_suggestions(
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


@login_required
@require_GET
def luna_timer_recommendations(request):
    result = timer_suggestions.build_luna_suggestions(request.user, request)
    if result.pending:
        return HttpResponse(
            status=202,
            headers={"Cache-Control": "no-store", "Retry-After": "5"},
        )
    response = render(
        request,
        "core/partials/luna_timer_recommendations.html",
        {
            "luna_suggestions": result.suggestions,
            "advice_status": result.advice_status,
        },
    )
    response["Cache-Control"] = "no-store"
    return response
