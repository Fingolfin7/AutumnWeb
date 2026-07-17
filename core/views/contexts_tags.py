from core.forms import *
from core.utils import *
from core.models import Context, Tag
from django.contrib import messages
from core.totals import derived_project_totals
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect, reverse
from django.views.generic import (
    UpdateView,
    DeleteView,
)
from core.commitments import (
    build_commitment_panel_items,
    commitment_applies_to_context,
    commitment_applies_to_tag,
)
from core.models import Projects, Sessions, Commitment
from core.services import (
    CommitmentTargetProtectedError,
    DestructiveMutationService,
)


@login_required
def set_active_context(request):
    """
    Update the active context in the session based on a dropdown selection.
    """
    if request.method == "POST":
        context_id = request.POST.get("context_id") or "all"
        # Validate context_id when not 'all'
        if context_id != "all":
            try:
                Context.objects.get(id=int(context_id), user=request.user)
            except (Context.DoesNotExist, ValueError, TypeError):
                context_id = "all"
        set_active_context(request, context_id)
        next_url = (
            request.POST.get("next")
            or request.META.get("HTTP_REFERER")
            or reverse("home")
        )
        return redirect(next_url)

    # Fallback GET handler – treat like resetting to All
    set_active_context(request, "all")
    return redirect("home")


@login_required
def manage_contexts(request):
    """
    Simple page to create and list contexts for the current user.
    """
    if request.method == "POST":
        form = ContextForm(request.POST)
        if form.is_valid():
            ctx = form.save(commit=False)
            ctx.user = request.user
            # Enforce per-user uniqueness gracefully
            if Context.objects.filter(user=request.user, name=ctx.name).exists():
                form.add_error("name", "You already have a context with this name.")
            else:
                ctx.save()
                messages.success(request, "Context created successfully")
                return redirect("contexts")
    else:
        form = ContextForm()

    contexts = Context.objects.filter(user=request.user).order_by("name")

    context = {
        "title": "Contexts",
        "form": form,
        "contexts": contexts,
    }

    return render(request, "core/contexts.html", context)


@login_required
def manage_tags(request):
    """
    Simple page to create and list tags for the current user.
    """
    if request.method == "POST":
        form = TagForm(request.POST)
        if form.is_valid():
            tag = form.save(commit=False)
            tag.user = request.user
            if Tag.objects.filter(user=request.user, name=tag.name).exists():
                form.add_error("name", "You already have a tag with this name.")
            else:
                tag.save()
                messages.success(request, "Tag created successfully")
                return redirect("tags")
    else:
        form = TagForm()

    tags = Tag.objects.filter(user=request.user).order_by("name")

    context = {
        "title": "Tags",
        "form": form,
        "tags": tags,
    }

    return render(request, "core/tags.html", context)


# New views to update/delete Context and Tag
class UpdateContextView(LoginRequiredMixin, UpdateView):
    model = Context
    form_class = ContextForm
    template_name = "core/update_context.html"
    context_object_name = "context_obj"

    def get_queryset(self):
        return Context.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Update Context"

        # Sidebar stats for this context
        projects_qs = Projects.objects.filter(
            user=self.request.user, context=self.object
        )
        # Respect any globally selected active context (if it's a different context, this becomes empty)
        projects_qs = filter_by_active_context(projects_qs, self.request)

        total_projects = projects_qs.count()
        project_ids = list(projects_qs.values_list("pk", flat=True))
        total_time = sum(
            derived_project_totals(self.request.user, project_ids).values()
        )

        # Per-status counts
        sidebar_status_counts = {
            "active": projects_qs.filter(status="active").count(),
            "paused": projects_qs.filter(status="paused").count(),
            "complete": projects_qs.filter(status="complete").count(),
            "archived": projects_qs.filter(status="archived").count(),
        }

        sessions_qs = Sessions.objects.filter(
            user=self.request.user,
            project__in=projects_qs,
            end_time__isnull=False,
        )
        session_count = sessions_qs.count()
        average_session_duration = (
            (total_time / session_count) if session_count > 0 else 0
        )

        ctx.update(
            {
                "sidebar_total_projects": total_projects,
                "sidebar_total_time": total_time,
                "sidebar_average_session_duration": average_session_duration,
                "sidebar_status_counts": sidebar_status_counts,
            }
        )
        commitments_qs = (
            Commitment.objects.filter(user=self.request.user)
            .select_related("project", "subproject", "context", "tag")
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
            .order_by("-active", "aggregation_type", "created_at")
        )
        filtered = [
            c for c in commitments_qs if commitment_applies_to_context(c, self.object)
        ]
        ctx["related_commitments"] = build_commitment_panel_items(filtered)
        ctx["add_commitment_url"] = (
            f"{reverse('create_commitment_generic')}?aggregation_type=context&target_id={self.object.id}"
        )
        return ctx

    def form_valid(self, form):
        if (
            Context.objects.filter(user=self.request.user, name=form.instance.name)
            .exclude(pk=self.object.pk)
            .exists()
        ):
            form.add_error("name", "You already have a context with this name.")
            return self.form_invalid(form)
        form.save()
        messages.success(self.request, "Context updated successfully")
        return redirect("contexts")


class DeleteContextView(LoginRequiredMixin, DeleteView):
    model = Context
    template_name = "core/delete_context.html"
    context_object_name = "context_obj"

    def get_queryset(self):
        return Context.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Delete Context"
        return context

    def get_success_url(self):
        messages.success(self.request, "Context deleted successfully")
        return reverse("contexts")

    def form_valid(self, form):
        try:
            DestructiveMutationService.delete_context(
                user=self.request.user, context_name=self.object.name
            )
        except CommitmentTargetProtectedError as exc:
            messages.error(self.request, str(exc))
            return redirect("contexts")
        return redirect(self.get_success_url())


class UpdateTagView(LoginRequiredMixin, UpdateView):
    model = Tag
    form_class = TagForm
    template_name = "core/update_tag.html"
    context_object_name = "tag"

    def get_queryset(self):
        return Tag.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Update Tag"

        # Allow explicit ?context= to override the global active context for the sidebar stats.
        # (Used by the context dropdown on this page.)
        override_context_id = self.request.GET.get("context")

        # Sidebar stats for this tag
        projects_qs = Projects.objects.filter(
            user=self.request.user, tags=self.object
        ).distinct()
        projects_qs = filter_by_active_context(
            projects_qs, self.request, override_context_id=override_context_id
        )

        total_projects = projects_qs.count()
        project_ids = list(projects_qs.values_list("pk", flat=True))
        total_time = sum(
            derived_project_totals(self.request.user, project_ids).values()
        )

        # Per-status counts
        sidebar_status_counts = {
            "active": projects_qs.filter(status="active").count(),
            "paused": projects_qs.filter(status="paused").count(),
            "complete": projects_qs.filter(status="complete").count(),
            "archived": projects_qs.filter(status="archived").count(),
        }

        sessions_qs = Sessions.objects.filter(
            user=self.request.user,
            project__in=projects_qs,
            end_time__isnull=False,
        )
        session_count = sessions_qs.count()
        average_session_duration = (
            (total_time / session_count) if session_count > 0 else 0
        )

        ctx.update(
            {
                "override_context_id": override_context_id or "",
                "sidebar_total_projects": total_projects,
                "sidebar_total_time": total_time,
                "sidebar_average_session_duration": average_session_duration,
                "sidebar_status_counts": sidebar_status_counts,
            }
        )
        commitments_qs = (
            Commitment.objects.filter(user=self.request.user)
            .select_related("project", "subproject", "context", "tag")
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
            .order_by("-active", "aggregation_type", "created_at")
        )
        filtered = [c for c in commitments_qs if commitment_applies_to_tag(c, self.object)]
        ctx["related_commitments"] = build_commitment_panel_items(filtered)
        ctx["add_commitment_url"] = (
            f"{reverse('create_commitment_generic')}?aggregation_type=tag&target_id={self.object.id}"
        )
        return ctx

    def form_valid(self, form):
        if (
            Tag.objects.filter(user=self.request.user, name=form.instance.name)
            .exclude(pk=self.object.pk)
            .exists()
        ):
            form.add_error("name", "You already have a tag with this name.")
            return self.form_invalid(form)
        form.save()
        messages.success(self.request, "Tag updated successfully")
        return redirect("tags")


class DeleteTagView(LoginRequiredMixin, DeleteView):
    model = Tag
    template_name = "core/delete_tag.html"
    context_object_name = "tag"

    def get_queryset(self):
        return Tag.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Delete Tag"
        return context

    def get_success_url(self):
        messages.success(self.request, "Tag deleted successfully")
        return reverse("tags")

    def form_valid(self, form):
        try:
            DestructiveMutationService.delete_tag(
                user=self.request.user, tag_name=self.object.name
            )
        except CommitmentTargetProtectedError as exc:
            messages.error(self.request, str(exc))
            return redirect("tags")
        return redirect(self.get_success_url())
