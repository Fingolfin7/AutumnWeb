import json
from core.forms import *
from core.utils import *
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render, redirect, reverse
from django.views.generic import (
    ListView,
    CreateView,
    UpdateView,
    DeleteView,
)
from core.commitments import (
    build_commitment_panel_items,
    commitment_applies_to_project,
    commitment_applies_to_subproject,
    get_commitment_progress,
    reconcile_commitment,
)
from core.models import Projects, SubProjects, Commitment, status_choices


class ProjectsListView(LoginRequiredMixin, ListView):
    model = Projects
    template_name = "core/projects_list.html"
    context_object_name = "projects"
    ordering = ["-last_updated"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Projects"

        context["search_form"] = SearchProjectForm(
            initial={
                "project_name": self.request.GET.get("project_name"),
                "start_date": self.request.GET.get("start_date"),
                "end_date": self.request.GET.get("end_date"),
                "context": self.request.GET.get("context") or "",
                "tags": self.request.GET.getlist("tags"),
                "exclude_projects": self.request.GET.getlist("exclude_projects"),
            },
            user=self.request.user,
        )

        ungrouped_projects = context["object_list"]

        # One reliable empty check for the whole page
        context["has_projects"] = ungrouped_projects.exists()

        # Build commitment progress data for all projects with active commitments
        commitment_progress = {}
        for project in ungrouped_projects:
            try:
                commitment = project.commitment
                if commitment and commitment.active:
                    # Reconcile past periods
                    reconcile_commitment(commitment)
                    # Get current progress
                    commitment_progress[project.id] = get_commitment_progress(
                        commitment
                    )
            except Commitment.DoesNotExist:
                pass
        context["commitment_progress"] = commitment_progress

        # group by project status (active, paused, complete) from the status_choices tuple
        grouped_projects = []
        for (
            status,
            displayName,
        ) in status_choices:  # db_Status is how the status is stored in the database
            grouped_projects.append(
                {
                    "status": displayName,
                    "projects": ungrouped_projects.filter(status=status).order_by(
                        "-last_updated"
                    ),
                }
            )

        context["grouped_projects"] = grouped_projects
        context["exclude_project_meta_json"] = json.dumps(
            build_exclude_project_meta(self.request.user)
        )

        return context

    def get_queryset(self):
        projects = Projects.objects.filter(user=self.request.user)

        # Allow explicit ?context= to override global active context
        override_context_id = self.request.GET.get("context")
        projects = filter_by_active_context(
            projects, self.request, override_context_id=override_context_id
        )

        search_name = self.request.GET.get("project_name")
        start_date = self.request.GET.get("start_date")
        end_date = self.request.GET.get("end_date")
        tag_ids = self.request.GET.getlist("tags")

        if search_name:
            projects = filter_by_projects(projects, name=search_name)

        if start_date:
            start = timezone.make_aware(parse_date_or_datetime(start_date))
            if end_date:
                end = timezone.make_aware(
                    parse_date_or_datetime(end_date) + timedelta(days=1)
                )
                projects = projects.filter(start_date__range=[start, end])
            else:
                projects = projects.filter(start_date__gte=start)

        if tag_ids:
            projects = projects.filter(tags__id__in=tag_ids).distinct()

        exclude_ids = self.request.GET.getlist("exclude_projects")
        if exclude_ids:
            projects = projects.exclude(id__in=exclude_ids)

        return projects


class CreateProjectView(LoginRequiredMixin, CreateView):
    model = Projects
    context_object_name = "project"
    form_class = CreateProjectForm
    template_name = "core/create_project.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create Project"
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.user = (
            self.request.user
        )  # set the user field of the project to the current user
        if Projects.objects.filter(
            user=self.request.user, name=form.instance.name
        ).exists():
            form.add_error("name", "You already have a project with this name.")
            return self.form_invalid(form)
        form.save()
        messages.success(self.request, "Project created successfully")
        return redirect("projects")


class CreateSubProjectView(LoginRequiredMixin, CreateView):
    model = SubProjects
    form_class = CreateSubProjectForm
    template_name = "core/create_subproject.html"

    def get_initial(self):
        initial = super().get_initial()
        if "pk" in self.kwargs:
            initial["parent_project"] = Projects.objects.get(
                pk=self.kwargs.get("pk"), user=self.request.user
            )
        elif "project_name" in self.kwargs:
            initial["parent_project"] = Projects.objects.get(
                name=self.kwargs.get("project_name"), user=self.request.user
            )
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create Subproject"
        return context

    def form_valid(self, form):
        form.instance.user = (
            self.request.user
        )  # set the user field of the subproject to the current user
        form.save()
        messages.success(self.request, "Subproject created successfully")
        return redirect("projects")

    def form_invalid(self, form):
        # add an error for the name field if the user already has a subproject with the same name under the same project
        if SubProjects.objects.filter(
            user=self.request.user,
            name=form.instance.name,
            parent_project=form.instance.parent_project,
        ).exists():
            form.add_error(
                "name",
                "You already have a subproject with this name under the selected project.",
            )
        return super().form_invalid(form)


class UpdateProjectView(LoginRequiredMixin, UpdateView):
    model = Projects
    form_class = UpdateProjectForm
    template_name = "core/update_project.html"
    context_object_name = "project"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Update Project"
        context["subprojects"] = (
            self.object.subprojects.all()
        )  # get all subprojects related to the project
        context["session_count"] = (
            self.object.sessions.count()
        )  # get the number of sessions related to the project
        context["average_session_duration"] = (
            self.object.total_time / context["session_count"]
            if context["session_count"] > 0
            else 0
        )
        # context["recent_sessions"] = self.object.recent_sessions.all()

        # Build all commitments relevant to this project (multiple scopes can apply).
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
            c for c in commitments_qs if commitment_applies_to_project(c, self.object)
        ]
        context["related_commitments"] = build_commitment_panel_items(filtered)
        context["add_commitment_url"] = reverse("create_commitment", kwargs={"project_pk": self.object.id})

        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        if (
            Projects.objects.filter(user=self.request.user, name=form.instance.name)
            .exclude(pk=self.object.pk)
            .exists()
        ):
            form.add_error("name", "You already have a project with this name.")
            return self.form_invalid(form)
        form.save()
        messages.success(self.request, "Project updated successfully")
        return redirect("update_project", pk=self.kwargs["pk"])


class UpdateSubProjectView(LoginRequiredMixin, UpdateView):
    model = SubProjects
    form_class = UpdateSubProjectForm
    template_name = "core/update_subproject.html"
    context_object_name = "subproject"

    def get_object(self, queryset=None):
        subproject = super().get_object(queryset)
        # subproject.audit_total_time()
        return subproject

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Update Subproject"
        context["session_count"] = (
            self.object.sessions.count()
        )  # get the number of sessions related to the project
        context["average_session_duration"] = (
            self.object.total_time / context["session_count"]
            if context["session_count"] > 0
            else 0
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
            c
            for c in commitments_qs
            if commitment_applies_to_subproject(c, self.object)
        ]
        context["related_commitments"] = build_commitment_panel_items(filtered)
        context["add_commitment_url"] = (
            f"{reverse('create_commitment_generic')}?aggregation_type=subproject&target_id={self.object.id}"
        )
        return context

    def form_valid(self, form):
        if (
            SubProjects.objects.filter(
                user=self.request.user,
                name=form.instance.name,
                parent_project=form.instance.parent_project,
            )
            .exclude(pk=self.object.pk)
            .exists()
        ):
            form.add_error(
                "name",
                "You already have a subproject with this name under the selected project.",
            )
            return self.form_invalid(form)
        form.save()
        messages.success(self.request, "Subproject updated successfully")
        return redirect("update_subproject", pk=self.kwargs["pk"])


class DeleteProjectView(LoginRequiredMixin, DeleteView):
    model = Projects
    template_name = "core/delete_project.html"
    context_object_name = "project"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Delete Project"
        return context

    def get_success_url(self):
        messages.success(self.request, "Project deleted successfully")
        return reverse("projects")


class DeleteSubProjectView(LoginRequiredMixin, DeleteView):
    model = SubProjects
    template_name = "core/delete_subproject.html"
    context_object_name = "subproject"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Delete Subproject"
        return context

    def get_success_url(self):
        messages.success(self.request, "Subproject deleted successfully")
        return reverse("projects")


@login_required
@transaction.atomic
def merge_projects(request):
    """
    View to merge two projects into one new project.
    Moves all sessions and subprojects from both projects to the new merged project.
    """
    if request.method == "POST":
        form = MergeProjectsForm(request.POST)
        if form.is_valid():
            try:
                project1_name = form.cleaned_data["project1"]
                project2_name = form.cleaned_data["project2"]
                new_project_name = form.cleaned_data["new_project_name"]

                # Get the projects to merge
                project1 = get_object_or_404(
                    Projects, name=project1_name, user=request.user
                )
                project2 = get_object_or_404(
                    Projects, name=project2_name, user=request.user
                )

                # Check if new project name already exists
                if Projects.objects.filter(
                    user=request.user, name=new_project_name
                ).exists():
                    form.add_error(
                        "new_project_name", "You already have a project with this name."
                    )
                    return render(
                        request,
                        "core/merge_projects.html",
                        {"title": "Merge Projects", "form": form},
                    )

                # Create merged description
                merged_description = (
                    f"Merged from '{project1.name}' and '{project2.name}'\n\n"
                )

                if project1.description:
                    merged_description += f"--- {project1.name} Description ---\n{project1.description}\n\n"

                if project2.description:
                    merged_description += f"--- {project2.name} Description ---\n{project2.description}\n\n"

                # Remove trailing newlines
                merged_description = merged_description.strip()

                # Create the new merged project
                merged_project = Projects.objects.create(
                    user=request.user,
                    name=new_project_name,
                    start_date=min(project1.start_date, project2.start_date),
                    last_updated=max(project1.last_updated, project2.last_updated),
                    total_time=0.0,  # Will be calculated by audit function
                    status="active",  # Default to active
                    description=merged_description,
                )

                # Move all sessions from both projects to the merged project
                project1_sessions = project1.sessions.all()
                project2_sessions = project2.sessions.all()

                for session in project1_sessions:
                    session.project = merged_project
                    session.save()

                for session in project2_sessions:
                    session.project = merged_project
                    session.save()

                # Move all subprojects from both projects to the merged project
                # Handle potential name conflicts by renaming duplicates
                project1_subprojects = list(project1.subprojects.all())
                project2_subprojects = list(project2.subprojects.all())

                # Get existing subproject names in the merged project
                existing_subproject_names = set()

                # First, move all subprojects from project1
                for subproject in project1_subprojects:
                    original_name = subproject.name
                    new_name = original_name

                    # If name conflict exists, append project name to make it unique
                    if new_name in existing_subproject_names:
                        new_name = f"{original_name} ({project1.name})"
                        counter = 1
                        while new_name in existing_subproject_names:
                            new_name = f"{original_name} ({project1.name}) {counter}"
                            counter += 1

                    subproject.name = new_name
                    subproject.parent_project = merged_project
                    subproject.save()
                    existing_subproject_names.add(new_name)

                # Then, move all subprojects from project2
                for subproject in project2_subprojects:
                    original_name = subproject.name
                    new_name = original_name

                    # If name conflict exists, append project name to make it unique
                    if new_name in existing_subproject_names:
                        new_name = f"{original_name} ({project2.name})"
                        counter = 1
                        while new_name in existing_subproject_names:
                            new_name = f"{original_name} ({project2.name}) {counter}"
                            counter += 1

                    subproject.name = new_name
                    subproject.parent_project = merged_project
                    subproject.save()
                    existing_subproject_names.add(new_name)

                # Audit total time for the merged project and all its subprojects
                merged_project.audit_total_time(log=False)
                for subproject in merged_project.subprojects.all():
                    subproject.audit_total_time(log=False)

                # Delete the original projects
                project1.delete()
                project2.delete()

                # Check if any subprojects were renamed
                renamed_count = 0
                for sp in project1_subprojects + project2_subprojects:
                    if " (" in sp.name and sp.name.endswith(")"):
                        renamed_count += 1

                if renamed_count > 0:
                    messages.success(
                        request,
                        f"Successfully merged '{project1_name}' and '{project2_name}' into '{new_project_name}'. {renamed_count} subprojects were renamed to avoid conflicts.",
                    )
                else:
                    messages.success(
                        request,
                        f"Successfully merged '{project1_name}' and '{project2_name}' into '{new_project_name}'",
                    )
                return redirect("projects")

            except Exception as e:
                messages.error(
                    request, f"An error occurred while merging projects: {e}"
                )
        else:
            messages.error(request, "Invalid form data. Please check your inputs.")
    else:
        form = MergeProjectsForm()

    context = {"title": "Merge Projects", "form": form}

    return render(request, "core/merge_projects.html", context)


@login_required
@transaction.atomic
def merge_subprojects(request, project_id):
    """
    View to merge two subprojects into one new subproject.
    Moves all sessions from both subprojects to the new merged subproject.
    """
    parent_project = get_object_or_404(Projects, id=project_id, user=request.user)

    if request.method == "POST":
        form = MergeSubProjectsForm(request.POST)
        if form.is_valid():
            try:
                subproject1_name = form.cleaned_data["subproject1"]
                subproject2_name = form.cleaned_data["subproject2"]
                new_subproject_name = form.cleaned_data["new_subproject_name"]

                # Get the subprojects to merge (must belong to the same parent project)
                subproject1 = get_object_or_404(
                    SubProjects,
                    name=subproject1_name,
                    parent_project=parent_project,
                    user=request.user,
                )
                subproject2 = get_object_or_404(
                    SubProjects,
                    name=subproject2_name,
                    parent_project=parent_project,
                    user=request.user,
                )

                # Check if new subproject name already exists in the same project
                if SubProjects.objects.filter(
                    user=request.user,
                    name=new_subproject_name,
                    parent_project=parent_project,
                ).exists():
                    form.add_error(
                        "new_subproject_name",
                        "You already have a subproject with this name in this project.",
                    )
                    return render(
                        request,
                        "core/merge_subprojects.html",
                        {
                            "title": "Merge Subprojects",
                            "form": form,
                            "parent_project": parent_project,
                        },
                    )

                # Create merged description
                merged_description = (
                    f"Merged from '{subproject1.name}' and '{subproject2.name}'\n\n"
                )

                if subproject1.description:
                    merged_description += f"--- {subproject1.name} Description ---\n{subproject1.description}\n\n"

                if subproject2.description:
                    merged_description += f"--- {subproject2.name} Description ---\n{subproject2.description}\n\n"

                # Remove trailing newlines
                merged_description = merged_description.strip()

                # Create the new merged subproject
                merged_subproject = SubProjects.objects.create(
                    user=request.user,
                    name=new_subproject_name,
                    parent_project=parent_project,
                    start_date=min(subproject1.start_date, subproject2.start_date),
                    last_updated=max(
                        subproject1.last_updated, subproject2.last_updated
                    ),
                    total_time=0.0,  # Will be calculated by audit function
                    description=merged_description,
                )

                # Move all sessions from both subprojects to the merged subproject
                subproject1_sessions = subproject1.sessions.all()
                subproject2_sessions = subproject2.sessions.all()

                for session in subproject1_sessions:
                    session.subprojects.remove(subproject1)
                    session.subprojects.add(merged_subproject)

                for session in subproject2_sessions:
                    session.subprojects.remove(subproject2)
                    session.subprojects.add(merged_subproject)

                # Audit total time for the merged subproject
                merged_subproject.audit_total_time(log=False)

                # Delete the original subprojects
                subproject1.delete()
                subproject2.delete()

                messages.success(
                    request,
                    f"Successfully merged '{subproject1_name}' and '{subproject2_name}' into '{new_subproject_name}'",
                )
                return redirect("update_project", pk=project_id)

            except Exception as e:
                messages.error(
                    request, f"An error occurred while merging subprojects: {e}"
                )
        else:
            messages.error(request, "Invalid form data. Please check your inputs.")
    else:
        form = MergeSubProjectsForm()

    context = {
        "title": "Merge Subprojects",
        "form": form,
        "parent_project": parent_project,
    }

    return render(request, "core/merge_subprojects.html", context)
