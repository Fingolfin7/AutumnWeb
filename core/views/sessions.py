import json
import pytz
from core.forms import *
from core.utils import *
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from datetime import datetime
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render, redirect, reverse
from django.views.generic import (
    ListView,
    DeleteView,
)
from core.models import Projects, SubProjects, Sessions
from core.services import SessionMutationService


def remove_ambiguous_time_error(time_value):
    # Create naive datetime from string
    naive_dt = datetime.strptime(time_value, "%Y-%m-%d %H:%M:%S")
    tz = timezone.get_current_timezone()

    # If tz has a pytz-style `localize` (pytz timezone), use it to control is_dst.
    try:
        if hasattr(tz, "localize"):
            return tz.localize(naive_dt, is_dst=True)
    except pytz.AmbiguousTimeError:
        if hasattr(tz, "localize"):
            return tz.localize(naive_dt, is_dst=False)

    # Fallback: let Django create an aware datetime (best-effort; may raise for ambiguous times)
    try:
        return timezone.make_aware(naive_dt, tz)
    except pytz.AmbiguousTimeError:
        # As a final fallback, try without specifying is_dst (some tz implementations won't raise here)
        return timezone.make_aware(naive_dt, tz)


def fix_ambiguous_time(form, field_name, raw_time):
    for error in form.errors.get(field_name, []):
        if "ambiguous" in error:
            return remove_ambiguous_time_error(raw_time)
    return None  # Return None if no changes were made


@login_required
@transaction.atomic
def update_session(request, session_id: int):
    """
    Allow user to change session details, including project, subprojects, start time, end time, and note.
    Updates the existing session so its ID remains a stable reference.
    """
    current_session = get_object_or_404(
        Sessions.objects.select_for_update(), id=session_id, user=request.user
    )

    if request.method == "POST":
        form = UpdateSessionForm(request.POST, instance=current_session)
        valid = form.is_valid()
        post_data = None

        if (
            not valid
        ):  # correct ambiguous time errors that occur on daylights saving time changes
            # Extract start and end times from POST data
            start_time_raw = request.POST.get("start_time")
            end_time_raw = request.POST.get("end_time")

            # Make a local mutable copy of POST to avoid mutating the request object (and satisfy type checkers)
            post = request.POST.copy()
            post_data = post  # keep a reference for later use when reading subprojects

            # Attempt to fix ambiguous times
            fixed_start_time = fix_ambiguous_time(form, "start_time", start_time_raw)
            fixed_end_time = fix_ambiguous_time(form, "end_time", end_time_raw)

            if fixed_start_time:
                post["start_time"] = fixed_start_time
            if fixed_end_time:
                post["end_time"] = fixed_end_time

            # recreate the form with the updated POST data and try again
            form = UpdateSessionForm(post, instance=current_session)
            valid = form.is_valid()

        if valid:
            try:
                project_name = form.cleaned_data["project_name"]
                # Prefer local mutable POST data if we created it earlier; otherwise fall back to request.POST.
                if post_data is not None:
                    subproject_names = post_data.getlist("subprojects")  # type: ignore[name-defined]
                else:
                    subproject_names = request.POST.getlist("subprojects")

                project = get_object_or_404(
                    Projects, name=project_name, user=request.user
                )

                subprojects = SubProjects.objects.filter(
                    name__in=subproject_names, parent_project=project, user=request.user
                )

                if not subprojects.exists() and subproject_names:
                    raise ValueError("No subprojects found for the selected project")

                candidate = form.save(commit=False)
                updated_session = SessionMutationService.mutate_session(
                    current_session.pk,
                    user=request.user,
                    project=project,
                    subprojects=list(subprojects),
                    start_time=candidate.start_time,
                    end_time=candidate.end_time,
                    note=candidate.note,
                    is_active=False,
                )

                messages.success(request, "Updated session")
                return redirect("update_session", session_id=updated_session.id)

            except ValueError as ve:
                messages.error(request, str(ve))
            except Exception as e:
                messages.error(
                    request, f"An error occurred while updating the session. Error: {e}"
                )
        else:
            messages.error(request, "Invalid form data. Please check your inputs.")
    else:
        form = UpdateSessionForm(
            instance=current_session,
            initial={
                "project_name": current_session.project.name
                if current_session.project
                else ""
            },
        )

    subprojects = SubProjects.objects.filter(parent_project=current_session.project)
    session_subs = current_session.subprojects.all()
    filtered_subs = [
        {"subproject": sp, "is_selected": sp in session_subs} for sp in subprojects
    ]

    context = {"title": "Update Session", "filtered_subs": filtered_subs, "form": form}

    return render(request, "core/update_session.html", context)


class SessionsListView(LoginRequiredMixin, ListView):
    model = Sessions
    template_name = "core/list_sessions.html"
    context_object_name = "sessions"
    ordering = ["-end_time"]
    paginate_by = 7

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Sessions"
        context["search_form"] = SearchProjectForm(
            initial={
                "project_name": self.request.GET.get("project_name"),
                "start_date": self.request.GET.get("start_date"),
                "end_date": self.request.GET.get("end_date"),
                "note_snippet": self.request.GET.get("note_snippet"),
                "context": self.request.GET.get("context") or "",
                "tags": self.request.GET.getlist("tags"),
                "exclude_projects": self.request.GET.getlist("exclude_projects"),
            },
            user=self.request.user,
        )

        paginated_sessions = context["object_list"]
        from core.utils import group_sessions_by_date

        context["grouped_sessions"] = group_sessions_by_date(paginated_sessions)

        # Check if any search-related query parameters are present. we only want to display the message on a search
        if (
            self.request.GET.get("project_name")
            or self.request.GET.get("start_date")
            or self.request.GET.get("end_date")
            or self.request.GET.get("note_snippet")
        ):
            messages.success(self.request, f"Found {len(self.get_queryset())} results")

        context["exclude_project_meta_json"] = json.dumps(
            build_exclude_project_meta(self.request.user)
        )

        return context

    def get_queryset(self):
        sessions = Sessions.objects.filter(is_active=False, user=self.request.user)

        # Allow explicit ?context= to override the global active context
        override_context_id = self.request.GET.get("context")
        sessions = filter_by_active_context(
            sessions, self.request, override_context_id=override_context_id
        )

        return filter_sessions_by_params(self.request, sessions)


class DeleteSessionView(LoginRequiredMixin, DeleteView):
    model = Sessions
    template_name = "core/delete_session.html"
    context_object_name = "session"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Delete Session"
        return context

    def get_object(self, queryset=None):
        return get_object_or_404(
            Sessions, pk=self.kwargs["session_id"], user=self.request.user
        )

    def get_success_url(self):
        messages.success(self.request, "Session deleted successfully")
        return reverse("sessions")  # redirect to the sessions page

    def form_valid(self, form):
        success_url = self.get_success_url()
        SessionMutationService.delete_session(
            self.object.pk, user=self.request.user
        )
        return redirect(success_url)
