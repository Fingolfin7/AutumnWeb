from core.forms import *
from core.utils import *
from django.utils import timezone
from datetime import datetime, timedelta, time
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import (
    TemplateView,
)
from core.commitments import (
    calculate_commitment_streak,
    get_commitment_progress,
    reconcile_commitment,
)
from core.models import Sessions, Commitment


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        stop_expired_timers(self.request.user)
        context = super().get_context_data(**kwargs)
        context["title"] = "Autumn"
        user = self.request.user

        # Import streak functions
        from core.utils import (
            calculate_daily_activity_streak,
            filter_by_active_context,
        )

        # 1. Daily activity streak (precompute 30 days for toggleable view)
        context["daily_streak"] = calculate_daily_activity_streak(user, days=30)

        # 2. Get all active commitments with progress and streak data
        commitments_data = []
        commitments = Commitment.objects.filter(user=user, active=True).select_related(
            "project", "subproject", "context", "tag"
        )

        for commitment in commitments:
            # Reconcile past periods
            reconcile_commitment(commitment)
            # Get current progress
            progress = get_commitment_progress(commitment)
            # Get commitment streak
            streak = calculate_commitment_streak(commitment)

            commitments_data.append(
                {
                    "commitment": commitment,
                    "progress": progress,
                    "streak": streak,
                }
            )

        # Sort by urgency: lowest percentage first (most behind)
        commitments_data.sort(key=lambda x: x["progress"]["percentage"])
        context["commitments_data"] = commitments_data

        # 3. Recent 3 completed sessions
        recent_sessions = (
            Sessions.objects.filter(user=user, is_active=False, end_time__isnull=False)
            .select_related("project")
            .prefetch_related("subprojects")
            .order_by("-end_time")[:3]
        )
        context["recent_sessions"] = recent_sessions

        from core.utils import group_sessions_by_date

        context["grouped_sessions"] = group_sessions_by_date(recent_sessions)

        # 4. Quick stats
        now = timezone.now()
        today_start = timezone.make_aware(datetime.combine(now.date(), time.min))
        week_start = today_start - timedelta(days=now.weekday())

        # Today's total time
        today_sessions = Sessions.objects.filter(
            user=user, is_active=False, end_time__gte=today_start
        )
        today_total = sum(s.duration or 0 for s in today_sessions)
        context["today_total"] = today_total

        # This week's total time
        week_sessions = Sessions.objects.filter(
            user=user, is_active=False, end_time__gte=week_start
        )
        week_total = sum(s.duration or 0 for s in week_sessions)
        context["week_total"] = week_total

        # Active timers count
        active_timers = Sessions.objects.filter(user=user, is_active=True)
        active_timers = filter_by_active_context(active_timers, self.request)
        context["active_timers_count"] = active_timers.count()

        # 5. Active timers (up to 5)
        context["active_timers"] = active_timers[:5]

        return context
