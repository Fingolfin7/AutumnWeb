from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.db.models import Count, Sum

from core.audit import audit_project_totals_for_user
from .models import Profile


@admin.action(description="Run project/subproject audit for selected users")
def run_audit_for_selected_users(modeladmin, request, queryset):
    audited_users = 0
    audited_projects = 0
    audited_subprojects = 0

    for user in queryset.iterator():
        project_count, subproject_count = audit_project_totals_for_user(user, log=False)
        audited_users += 1
        audited_projects += project_count
        audited_subprojects += subproject_count

    modeladmin.message_user(
        request,
        (
            f"Audit complete for {audited_users} user(s): "
            f"projects={audited_projects}, subprojects={audited_subprojects}."
        ),
        messages.SUCCESS,
    )


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False


class UserAdmin(BaseUserAdmin):
    inlines = (ProfileInline,)
    list_display = (
        "username",
        "email",
        "is_staff",
        "is_active",
        "project_count",
        "session_count",
        "commitment_count",
        "total_logged_minutes",
    )
    list_filter = BaseUserAdmin.list_filter + ("is_staff", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")
    actions = (run_audit_for_selected_users,)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _project_count=Count("projects", distinct=True),
            _session_count=Count("sessions", distinct=True),
            _commitment_count=Count("commitments", distinct=True),
            _total_logged_minutes=Sum("projects__total_time"),
        )

    @admin.display(description="Projects", ordering="_project_count")
    def project_count(self, obj):
        return obj._project_count or 0

    @admin.display(description="Sessions", ordering="_session_count")
    def session_count(self, obj):
        return obj._session_count or 0

    @admin.display(description="Commitments", ordering="_commitment_count")
    def commitment_count(self, obj):
        return obj._commitment_count or 0

    @admin.display(description="Total logged minutes", ordering="_total_logged_minutes")
    def total_logged_minutes(self, obj):
        return round(obj._total_logged_minutes or 0, 2)


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
admin.site.register(Profile)
