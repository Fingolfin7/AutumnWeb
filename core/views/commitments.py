import json
from core.forms import *
from core.utils import *
from core.models import Context, Tag
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, reverse
from django.views.generic import (
    CreateView,
    UpdateView,
    DeleteView,
)
from core.commitments import (
    build_commitment_scope_meta,
    get_commitment_progress,
    reconcile_commitment,
)
from core.models import Projects, SubProjects, Commitment


class CreateCommitmentView(LoginRequiredMixin, CreateView):
    model = Commitment
    form_class = CommitmentForm
    template_name = "core/create_commitment.html"

    def _get_prefill_target(self):
        if "project_pk" in self.kwargs:
            project = get_object_or_404(
                Projects, pk=self.kwargs["project_pk"], user=self.request.user
            )
            return "project", project

        aggregation_type = (self.request.GET.get("aggregation_type") or "").strip()
        target_id = (self.request.GET.get("target_id") or "").strip()
        model_map = {
            "context": Context,
            "tag": Tag,
            "project": Projects,
            "subproject": SubProjects,
        }
        model = model_map.get(aggregation_type)
        if model is None or not target_id:
            return None, None
        try:
            target_obj = model.objects.get(pk=int(target_id), user=self.request.user)
        except (ValueError, model.DoesNotExist):
            return None, None
        return aggregation_type, target_obj

    def get_initial(self):
        initial = super().get_initial()
        aggregation_type, target_obj = self._get_prefill_target()
        if aggregation_type and target_obj:
            initial["aggregation_type"] = aggregation_type
            initial[aggregation_type] = target_obj
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Add Commitment"
        context["commitment_scope_meta_json"] = json.dumps(
            build_commitment_scope_meta(self.request.user)
        )
        if "project_pk" in self.kwargs:
            context["project"] = get_object_or_404(
                Projects, pk=self.kwargs["project_pk"], user=self.request.user
            )
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        kwargs["project"] = None
        aggregation_type, target_obj = self._get_prefill_target()
        if aggregation_type == "project" and target_obj is not None:
            project = target_obj
            kwargs["project"] = project
            if self.request.method == "POST":
                data = self.request.POST.copy()
                data.setdefault("aggregation_type", "project")
                data.setdefault("project", str(project.pk))
                kwargs["data"] = data
        return kwargs

    def form_valid(self, form):
        form.instance.user = self.request.user
        form.save()
        messages.success(self.request, "Commitment added successfully")
        if form.instance.aggregation_type == "project" and form.instance.project_id:
            return redirect("update_project", pk=form.instance.project.pk)
        return redirect("home")


class UpdateCommitmentView(LoginRequiredMixin, UpdateView):
    model = Commitment
    form_class = UpdateCommitmentForm
    template_name = "core/update_commitment.html"
    context_object_name = "commitment"

    def get_queryset(self):
        return Commitment.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Update Commitment"
        context["commitment_scope_meta_json"] = json.dumps(
            build_commitment_scope_meta(self.request.user)
        )
        # Reconcile and get progress
        reconcile_commitment(self.object)
        context["progress"] = get_commitment_progress(self.object)
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        kwargs["project"] = self.object.project if self.object.aggregation_type == "project" else None
        return kwargs

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Commitment updated successfully")
        if self.object.aggregation_type == "project" and self.object.project_id:
            return redirect("update_project", pk=self.object.project.pk)
        return redirect("home")


class DeleteCommitmentView(LoginRequiredMixin, DeleteView):
    model = Commitment
    template_name = "core/delete_commitment.html"
    context_object_name = "commitment"

    def get_queryset(self):
        return Commitment.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Delete Commitment"
        return context

    def get_success_url(self):
        messages.success(self.request, "Commitment deleted successfully")
        if self.object.aggregation_type == "project" and self.object.project_id:
            return reverse("update_project", kwargs={"pk": self.object.project.pk})
        return reverse("home")
