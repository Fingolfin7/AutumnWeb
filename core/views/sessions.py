import json
import pytz

from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from datetime import datetime
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render, redirect, reverse
from django.views.generic import (
    ListView,
    DeleteView,
)
from core.models import Context, Projects, SubProjects, Sessions, Tag
from core.services import SessionMutationService, UNSET
from core.views.allocations import parse_allocation_post
from core.forms import SearchProjectForm, UpdateSessionForm
from core.search import SESSION_ORDER, rank_sessions
from core.services.semantic_search import RELATED_LIMIT, RelatedOutcome
from core.utils import (
    build_exclude_project_meta,
    filter_by_active_context,
    filter_sessions_by_params,
    group_sessions_by_date,
    requested_similarity,
    similarity_slider,
    summarise_search_filters,
)


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
def update_session(request, session_id: int = None, session_uuid=None):
    """
    Allow user to change session details, including project, subprojects, start time, end time, and note.
    Reachable by integer id or by uuid; the uuid form survives export/re-import
    cycles, so it can be used as a stable external link.
    """
    lookup = {"id": session_id} if session_uuid is None else {"uuid": session_uuid}
    current_session = get_object_or_404(
        Sessions.objects.select_for_update(), user=request.user, **lookup
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

                subprojects = list(SubProjects.objects.filter(
                    name__in=subproject_names, parent_project=project, user=request.user
                ))

                if not subprojects and subproject_names:
                    raise ValueError("No subprojects found for the selected project")

                try:
                    allocations = parse_allocation_post(request.POST, subprojects)
                except ValueError as exc:
                    form.add_error(None, str(exc))
                    raise

                candidate = form.save(commit=False)
                updated_session = SessionMutationService.mutate_session(
                    current_session.pk,
                    user=request.user,
                    project=project,
                    subprojects=subprojects if allocations is None else UNSET,
                    allocations=allocations if allocations is not None else UNSET,
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
    session_links = {
        link.subproject_id: link
        for link in current_session.subproject_links.select_related("subproject")
    }
    filtered_subs = [
        {
            "subproject": sp,
            "is_selected": sp.pk in session_links,
            "allocation_bp": session_links[sp.pk].allocation_bp
            if sp.pk in session_links
            else 0,
        }
        for sp in subprojects
    ]

    context = {"title": "Update Session", "filtered_subs": filtered_subs, "form": form}

    return render(request, "core/update_session.html", context)


class SessionsListView(LoginRequiredMixin, ListView):
    model = Sessions
    template_name = "core/list_sessions.html"
    context_object_name = "sessions"
    paginate_by = 7

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Sessions"
        context["search_form"] = SearchProjectForm(
            initial={
                "search": self.request.GET.get("search"),
                "project_name": self.request.GET.get("project_name"),
                "start_date": self.request.GET.get("start_date"),
                "end_date": self.request.GET.get("end_date"),
                "note_snippet": self.request.GET.get("note_snippet"),
                "context": self.request.GET.get("context") or "",
                "tags": self.request.GET.getlist("tags"),
                "include_projects": self.request.GET.getlist("include_projects"),
                "exclude_projects": self.request.GET.getlist("exclude_projects"),
            },
            user=self.request.user,
        )

        paginated_sessions = context["object_list"]
        context["grouped_sessions"] = group_sessions_by_date(paginated_sessions)

        # What the filter sheet is currently hiding, echoed back onto the page.
        # This replaces the old "Found N results" flash: the count now lives
        # beside the list where it stays readable, instead of in a banner that
        # cost a second full run of the unpaginated query to produce.
        context["active_filters"] = summarise_search_filters(
            self.request, self.request.user
        )
        page = context.get("page_obj")
        context["result_count"] = (
            page.paginator.count if page else len(context["object_list"])
        )

        context["exclude_project_meta_json"] = json.dumps(
            build_exclude_project_meta(self.request.user)
        )

        context.update(self._related_context())

        return context

    def _scoped_sessions(self):
        sessions = (
            Sessions.objects.filter(end_time__isnull=False, user=self.request.user)
            .select_related("project")
            .prefetch_related("subprojects")
        )

        # Allow explicit ?context= to override the global active context
        override_context_id = self.request.GET.get("context")
        return filter_by_active_context(
            sessions, self.request, override_context_id=override_context_id
        )

    def get_queryset(self):
        # One shared search (core.search.rank_sessions, as API v2 and MCP use):
        # the list holds the direct keyword matches, and the "Related" section
        # below it the meaning-based ones, best first, paged on its own.
        # Every filter except the keyword term narrows both.
        params = self.request.GET.copy()
        params.pop("search", None)
        params.pop("related", None)
        sessions = filter_sessions_by_params(
            self.request, self._scoped_sessions(), params_override=params
        )
        self.cutoff = requested_similarity(self.request.GET)
        self.related_outcome = RelatedOutcome(collect_scores=True)
        self.search = rank_sessions(
            sessions,
            self.request.GET.get("search"),
            user=self.request.user,
            related=True,
            cutoff=self.cutoff,
            outcome=self.related_outcome,
        )
        return self.search.direct.order_by(*SESSION_ORDER)

    def _related_context(self):
        """Every related match above the cutoff, a page of them at a time, and
        the slider that sets the cutoff (whenever related matching ran, so a
        search with none can still be loosened)."""
        context = {"related_sessions": [], "related_page": None, "related_slider": None}
        if self.related_outcome.included:
            context["related_slider"] = similarity_slider(
                self.request.user, value=self.cutoff, outcome=self.related_outcome
            )
        related_ids = self.search.related_ids
        if related_ids:
            page = Paginator(related_ids, RELATED_LIMIT).get_page(
                self.request.GET.get("related_page")
            )
            context["related_sessions"] = self.search.related_sessions(page.object_list)
            context["related_page"] = page
        return context


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
