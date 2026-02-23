from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.db.models import Count, Sum

from .models import Profile


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
