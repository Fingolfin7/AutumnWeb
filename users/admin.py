from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.db.models import Count, FloatField, OuterRef, Subquery, Sum

from core.models import Sessions
from core.totals import rounded_session_minutes
from .models import Profile


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    fieldsets = (
        (
            "Account traits",
            {
                "fields": ("ai_features_enabled",),
            },
        ),
        (
            None,
            {
                "fields": (
                    "image",
                    "background_image",
                    "background_dimming",
                    "automatic_background",
                    "bing_background",
                    "nasa_apod_background",
                ),
            },
        ),
        (
            "Defaults",
            {
                "fields": (
                    "default_filter_value",
                    "default_filter_unit",
                    "insights_default_filter_value",
                    "insights_default_filter_unit",
                    "default_chart_project_count",
                ),
            },
        ),
    )


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
        total_minutes = (
            Sessions.objects.filter(
                user_id=OuterRef("pk"), end_time__isnull=False
            )
            .order_by()
            .values("user_id")
            .annotate(total=Sum(rounded_session_minutes()))
            .values("total")
        )
        return super().get_queryset(request).annotate(
            _project_count=Count("projects", distinct=True),
            _session_count=Count("sessions", distinct=True),
            _commitment_count=Count("commitments", distinct=True),
            _total_logged_minutes=Subquery(
                total_minutes, output_field=FloatField()
            ),
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


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "user_email", "ai_features_enabled")
    list_filter = ("ai_features_enabled",)
    search_fields = ("user__username", "user__email")

    @admin.display(description="Email", ordering="user__email")
    def user_email(self, obj):
        return obj.user.email
