from django.contrib import admin, messages
from django.db.models import Count, Sum

from .models import Commitment, Context, Projects, Sessions, SubProjects, Tag


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


@admin.action(description="Activate selected commitments")
def activate_commitments(modeladmin, request, queryset):
    updated = queryset.update(active=True)
    modeladmin.message_user(request, f"Activated {updated} commitment(s).", messages.SUCCESS)


@admin.action(description="Deactivate selected commitments")
def deactivate_commitments(modeladmin, request, queryset):
    updated = queryset.update(active=False)
    modeladmin.message_user(request, f"Deactivated {updated} commitment(s).", messages.SUCCESS)


@admin.action(description="Enable banking for selected commitments")
def enable_banking(modeladmin, request, queryset):
    updated = queryset.update(banking_enabled=True)
    modeladmin.message_user(request, f"Enabled banking for {updated} commitment(s).", messages.SUCCESS)


@admin.action(description="Disable banking for selected commitments")
def disable_banking(modeladmin, request, queryset):
    updated = queryset.update(banking_enabled=False)
    modeladmin.message_user(request, f"Disabled banking for {updated} commitment(s).", messages.SUCCESS)


@admin.register(Projects)
class ProjectsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "user",
        "context",
        "status",
        "total_time",
        "user_project_count",
        "user_total_project_minutes",
        "last_updated",
    )
    list_filter = ("status", "context", "tags", "user")
    search_fields = ("name", "description", "user__username", "user__email", "context__name", "tags__name")
    autocomplete_fields = ("user", "context", "tags")
    list_editable = ("status", "context")
    actions = (
        mark_projects_active,
        mark_projects_paused,
        mark_projects_complete,
        mark_projects_archived,
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "context").prefetch_related("tags").annotate(
            _user_project_count=Count("user__projects", distinct=True),
            _user_total_project_minutes=Sum("user__projects__total_time"),
        )

    @admin.display(description="User project count", ordering="_user_project_count")
    def user_project_count(self, obj):
        return obj._user_project_count or 0

    @admin.display(description="User total project minutes", ordering="_user_total_project_minutes")
    def user_total_project_minutes(self, obj):
        return round(obj._user_total_project_minutes or 0, 2)


@admin.register(SubProjects)
class SubProjectsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "user",
        "parent_project",
        "total_time",
        "user_subproject_count",
        "last_updated",
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

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "parent_project").annotate(
            _user_subproject_count=Count("user__subprojects", distinct=True)
        )

    @admin.display(description="User subproject count", ordering="_user_subproject_count")
    def user_subproject_count(self, obj):
        return obj._user_subproject_count or 0


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
    list_filter = ("is_active", "crosses_dst_transition", "project", "user", "project__status")
    search_fields = ("note", "project__name", "subprojects__name", "user__username", "user__email")
    autocomplete_fields = ("user", "project", "subprojects")
    readonly_fields = ("crosses_dst_transition",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("project", "user").prefetch_related("subprojects").annotate(
            _user_session_count=Count("user__sessions", distinct=True)
        )

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
    autocomplete_fields = ("user", "project", "subproject", "context", "tag")
    list_editable = ("active", "banking_enabled", "target", "max_balance", "min_balance")
    actions = (activate_commitments, deactivate_commitments, enable_banking, disable_banking)


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
