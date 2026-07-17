from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Count

from .models import (
    Commitment,
    Context,
    Projects,
    Sessions,
    SessionSubproject,
    SubProjects,
    Tag,
)
from .services import (
    CommitmentTargetProtectedError,
    DestructiveMutationService,
    SessionMutationService,
)
from .totals import annotate_project_totals, annotate_subproject_totals


@admin.action(description="Mark selected projects as active")
def mark_projects_active(modeladmin, request, queryset):
    updated = queryset.update(status="active")
    modeladmin.message_user(request, f"Updated {updated} project(s) to active.", messages.SUCCESS)


@admin.action(description="Mark selected projects as paused")
def mark_projects_paused(modeladmin, request, queryset):
    updated = queryset.update(status="paused")
    modeladmin.message_user(request, f"Updated {updated} project(s) to paused.", messages.SUCCESS)


@admin.action(description="Mark selected projects as complete")
def mark_projects_complete(modeladmin, request, queryset):
    updated = queryset.update(status="complete")
    modeladmin.message_user(request, f"Updated {updated} project(s) to complete.", messages.SUCCESS)


@admin.action(description="Mark selected projects as archived")
def mark_projects_archived(modeladmin, request, queryset):
    updated = queryset.update(status="archived")
    modeladmin.message_user(request, f"Updated {updated} project(s) to archived.", messages.SUCCESS)


@admin.register(Projects)
class ProjectsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "user",
        "context",
        "status",
        "derived_total_time",
        "user_project_count",
        "user_total_project_minutes",
        "derived_last_updated",
    )
    list_filter = ("status", "context", "tags", "user")
    search_fields = ("name", "description", "user__username", "user__email", "context__name", "tags__name")
    autocomplete_fields = ("user", "context", "tags")
    list_editable = ("status", "context")
    readonly_fields = ("last_updated",)
    actions = (
        mark_projects_active,
        mark_projects_paused,
        mark_projects_complete,
        mark_projects_archived,
    )

    def save_model(self, request, obj, form, change):
        if not change:
            return super().save_model(request, obj, form, change)
        update_fields = [
            field
            for field in form.changed_data
            if field not in {"tags", "last_updated"}
        ]
        if update_fields:
            obj.save(update_fields=update_fields)

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related("user", "context").prefetch_related("tags").annotate(
            _user_project_count=Count("user__projects", distinct=True),
        )
        return annotate_project_totals(queryset, include_user_total=True)

    @admin.display(description="Total time", ordering="derived_total_time")
    def derived_total_time(self, obj):
        return round(obj.derived_total_time or 0, 4)

    @admin.display(description="Last updated", ordering="derived_last_updated")
    def derived_last_updated(self, obj):
        return obj.derived_last_updated

    @admin.display(description="User project count", ordering="_user_project_count")
    def user_project_count(self, obj):
        return obj._user_project_count or 0

    @admin.display(description="User total project minutes", ordering="derived_user_total_time")
    def user_total_project_minutes(self, obj):
        return round(obj.derived_user_total_time or 0, 2)

    def delete_model(self, request, obj):
        try:
            DestructiveMutationService.delete_project(
                user=obj.user, project_name=obj.name
            )
        except CommitmentTargetProtectedError as exc:
            self.message_user(request, str(exc), messages.ERROR)

    def delete_queryset(self, request, queryset):
        try:
            with transaction.atomic():
                for project in list(queryset):
                    DestructiveMutationService.delete_project(
                        user=project.user, project_name=project.name
                    )
        except CommitmentTargetProtectedError as exc:
            self.message_user(request, str(exc), messages.ERROR)


@admin.register(SubProjects)
class SubProjectsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "user",
        "parent_project",
        "derived_total_time",
        "user_subproject_count",
        "derived_last_updated",
    )
    list_filter = ("user", "parent_project")
    search_fields = (
        "name",
        "description",
        "parent_project__name",
        "user__username",
        "user__email",
    )
    autocomplete_fields = ("user", "parent_project")
    readonly_fields = ("last_updated",)

    def save_model(self, request, obj, form, change):
        if not change:
            return super().save_model(request, obj, form, change)
        update_fields = [
            field
            for field in form.changed_data
            if field not in {"total_time", "last_updated"}
        ]
        if update_fields:
            obj.save(update_fields=update_fields)

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related("user", "parent_project").annotate(
            _user_subproject_count=Count("user__subprojects", distinct=True)
        )
        return annotate_subproject_totals(queryset)

    @admin.display(description="Total time", ordering="derived_total_time")
    def derived_total_time(self, obj):
        return round(obj.derived_total_time or 0, 4)

    @admin.display(description="Last updated", ordering="derived_last_updated")
    def derived_last_updated(self, obj):
        return obj.derived_last_updated

    @admin.display(description="User subproject count", ordering="_user_subproject_count")
    def user_subproject_count(self, obj):
        return obj._user_subproject_count or 0

    def delete_model(self, request, obj):
        try:
            DestructiveMutationService.delete_subproject(
                user=obj.user,
                project_name=obj.parent_project.name,
                subproject_name=obj.name,
            )
        except CommitmentTargetProtectedError as exc:
            self.message_user(request, str(exc), messages.ERROR)

    def delete_queryset(self, request, queryset):
        try:
            with transaction.atomic():
                for subproject in list(queryset):
                    DestructiveMutationService.delete_subproject(
                        user=subproject.user,
                        project_name=subproject.parent_project.name,
                        subproject_name=subproject.name,
                    )
        except CommitmentTargetProtectedError as exc:
            self.message_user(request, str(exc), messages.ERROR)


class SessionSubprojectInline(admin.TabularInline):
    model = SessionSubproject
    extra = 0
    autocomplete_fields = ("subproject",)


@admin.register(Sessions)
class SessionsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project",
        "user",
        "is_active",
        "start_time",
        "end_time",
        "duration_minutes",
        "user_session_count",
    )
    list_filter = ("project", "user", "project__status")
    search_fields = ("note", "project__name", "subprojects__name", "user__username", "user__email")
    autocomplete_fields = ("user", "project")
    inlines = (SessionSubprojectInline,)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("project", "user").prefetch_related("subprojects").annotate(
            _user_session_count=Count("user__sessions", distinct=True)
        )

    def delete_model(self, request, obj):
        SessionMutationService.delete_session(obj.pk, user=obj.user)

    def delete_queryset(self, request, queryset):
        for session_id in queryset.values_list("pk", flat=True):
            SessionMutationService.delete_session(session_id)

    @admin.display(description="Duration (minutes)")
    def duration_minutes(self, obj):
        return obj.duration

    @admin.display(description="User session count", ordering="_user_session_count")
    def user_session_count(self, obj):
        return obj._user_session_count or 0


@admin.register(Commitment)
class CommitmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "target_name",
        "aggregation_type",
        "user",
        "commitment_type",
        "period",
        "target",
        "active",
        "banking_enabled",
        "balance",
        "max_balance",
        "min_balance",
        "last_reconciled",
    )
    list_filter = (
        "aggregation_type",
        "commitment_type",
        "period",
        "active",
        "banking_enabled",
        "user",
    )
    search_fields = (
        "user__username",
        "user__email",
        "project__name",
        "subproject__name",
        "context__name",
        "tag__name",
    )
    readonly_fields = (
        "user",
        "aggregation_type",
        "project",
        "subproject",
        "context",
        "tag",
        "include_projects",
        "exclude_projects",
        "include_subprojects",
        "exclude_subprojects",
        "include_contexts",
        "exclude_contexts",
        "include_tags",
        "exclude_tags",
        "commitment_type",
        "period",
        "start_date",
        "target",
        "banking_enabled",
        "max_balance",
        "min_balance",
        "active",
        "balance",
        "last_reconciled",
        "needs_recompute",
        "ledger_start_at",
        "generation",
        "version",
    )
    list_editable = ()
    actions = ()

    def has_add_permission(self, request):
        return False


@admin.register(Context)
class ContextAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "user", "project_count")
    search_fields = ("name", "description", "user__username", "user__email")
    list_filter = ("user",)
    autocomplete_fields = ("user",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user").annotate(_project_count=Count("projects", distinct=True))

    @admin.display(description="Projects", ordering="_project_count")
    def project_count(self, obj):
        return obj._project_count or 0

    def delete_model(self, request, obj):
        try:
            DestructiveMutationService.delete_context(
                user=obj.user, context_name=obj.name
            )
        except CommitmentTargetProtectedError as exc:
            self.message_user(request, str(exc), messages.ERROR)

    def delete_queryset(self, request, queryset):
        try:
            with transaction.atomic():
                for context in list(queryset):
                    DestructiveMutationService.delete_context(
                        user=context.user, context_name=context.name
                    )
        except CommitmentTargetProtectedError as exc:
            self.message_user(request, str(exc), messages.ERROR)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "color", "user", "project_count")
    search_fields = ("name", "color", "user__username", "user__email")
    list_filter = ("user",)
    autocomplete_fields = ("user",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user").annotate(_project_count=Count("projects", distinct=True))

    @admin.display(description="Projects", ordering="_project_count")
    def project_count(self, obj):
        return obj._project_count or 0

    def delete_model(self, request, obj):
        try:
            DestructiveMutationService.delete_tag(
                user=obj.user, tag_name=obj.name
            )
        except CommitmentTargetProtectedError as exc:
            self.message_user(request, str(exc), messages.ERROR)

    def delete_queryset(self, request, queryset):
        try:
            with transaction.atomic():
                for tag in list(queryset):
                    DestructiveMutationService.delete_tag(
                        user=tag.user, tag_name=tag.name
                    )
        except CommitmentTargetProtectedError as exc:
            self.message_user(request, str(exc), messages.ERROR)
