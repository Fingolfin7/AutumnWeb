from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from datetime import datetime, timedelta, time
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.views.generic import (
    TemplateView,
)

from core.commitments import (
    calculate_commitment_streak,
    get_commitment_progress,
    reconcile_commitment,
)
from core.models import Sessions, Commitment, TimerReminder
from core.timeline import DEFAULT_RANGE, build_timeline
from core.totals import session_minute_totals_since
from core.utils import (
    calculate_daily_activity_streak,
    filter_by_active_context,
    group_sessions_by_date,
    stop_expired_timers,
)


#: How many "pick up where you left off" chips the start card offers, and how
#: far back to look for them. Small on purpose: the card is an invitation, not
#: a second projects list.
QUICK_START_LIMIT = 3
QUICK_START_LOOKBACK = 40

# The recent-session panel favors a complete latest workday. It only reaches
# into older active dates when that latest day is sparse, and the expansion is
# capped so a few quiet days do not turn the dashboard into a session archive.
RECENT_SESSION_DAY_LIMIT = 3
RECENT_SESSION_EXPANSION_THRESHOLD = 3
RECENT_SESSION_EXPANSION_LIMIT = 5


def greeting_for(moment):
    """Time-of-day greeting for the dashboard title, in the user's timezone."""
    hour = timezone.localtime(moment).hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def _combo_key(session):
    """Identity of a timer combination: one project plus its subprojects."""
    return (session.project_id, frozenset(sub.id for sub in session.subprojects.all()))


def build_quick_starts(recent_sessions, active_timers):
    """Distinct recent project/subproject combinations that aren't running.

    Restarting the thing you were just doing is the overwhelmingly common
    case, so the start card leads with it. Combinations already on the clock
    are dropped — offering to start a timer that is already running is noise.
    """
    running = {_combo_key(timer) for timer in active_timers}
    seen = set()
    quick_starts = []

    for session in recent_sessions:
        key = _combo_key(session)
        if key in running or key in seen:
            continue
        seen.add(key)
        quick_starts.append(session)
        if len(quick_starts) >= QUICK_START_LIMIT:
            break

    return quick_starts


def select_recent_dashboard_sessions(sessions):
    """Select the sessions shown in the dashboard's recent-session panel.

    ``sessions`` must be ordered newest-first by completed ``end_time`` (with
    a stable tie-breaker). Dates are derived from the active Django timezone,
    matching ``group_sessions_by_date`` and the rest of the dashboard.

    The newest active date is always shown in full. If it contains fewer than
    three sessions, append sessions from up to two older distinct active dates,
    stopping at five total sessions during that expansion. This intentionally
    allows a busy newest day to exceed five rows so that day is not presented
    as if it were complete when it has actually been truncated.
    """
    selected = []
    active_dates = []
    newest_date = None
    newest_day_count = 0

    for session in sessions:
        if not session.end_time:
            continue

        session_date = timezone.localtime(session.end_time).date()

        if newest_date is None:
            newest_date = session_date
            active_dates.append(session_date)

        if session_date == newest_date:
            selected.append(session)
            newest_day_count += 1
            continue

        # A non-sparse newest day is complete by itself; do not pull in older
        # dates just because they happen to have more recent-looking rows.
        if newest_day_count >= RECENT_SESSION_EXPANSION_THRESHOLD:
            break

        if session_date not in active_dates:
            if len(active_dates) >= RECENT_SESSION_DAY_LIMIT:
                break
            active_dates.append(session_date)

        if len(selected) >= RECENT_SESSION_EXPANSION_LIMIT:
            break

        selected.append(session)

    return selected


def get_recent_dashboard_sessions(user):
    """Return the completed sessions selected for the dashboard panel."""
    sessions = (
        Sessions.objects.filter(user=user, end_time__isnull=False)
        .select_related("project")
        .prefetch_related("subprojects")
        .order_by("-end_time", "-id")
    )
    return select_recent_dashboard_sessions(sessions.iterator(chunk_size=100))


TIMELINE_FRAGMENT_TEMPLATE = "core/partials/day_timeline.html"


@login_required
def timeline_fragment(request):
    """Render the timeline on its own, for the range tabs and the live poll.

    Two callers, one renderer:

    * the range tabs, which need a different window;
    * dashboard_desk.js, when the set of running timers changes underneath it.

    The client grows live blocks and walks the now-marker by itself between
    polls, so this is only fetched when the *shape* of the chart can have
    changed — not once a second.

    Like the active-timer fragment, this is rendered without context
    processors: the partial needs `timeline` and nothing else.

    Deliberately no ``stop_expired_timers`` call: the five-second timer poll
    already runs it, and this endpoint should not write on a GET to repeat
    work that has just been done.
    """
    timeline = build_timeline(request.user, request.GET.get("range", DEFAULT_RANGE))
    response = HttpResponse(
        render_to_string(TIMELINE_FRAGMENT_TEMPLATE, {"timeline": timeline})
    )
    response["Cache-Control"] = "no-store"
    return response


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        stop_expired_timers(self.request.user)
        context = super().get_context_data(**kwargs)
        context["title"] = "Autumn"
        user = self.request.user

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

        # 3. Adaptive recent completed sessions, favoring the latest active day
        recent_sessions = get_recent_dashboard_sessions(user)
        context["recent_sessions"] = recent_sessions

        context["grouped_sessions"] = group_sessions_by_date(recent_sessions)

        # 4. Quick stats
        now = timezone.now()
        context["greeting"] = greeting_for(now)
        local_today = timezone.localdate(now)
        today_start = timezone.make_aware(datetime.combine(local_today, time.min))
        week_start = today_start - timedelta(days=local_today.weekday())

        # Today's and this week's totals share one database aggregate. The old
        # path loaded every matching session twice and summed them in Python.
        summary_totals = session_minute_totals_since(
            user,
            today_total=today_start,
            week_total=week_start,
        )
        context.update(summary_totals)

        # Active timers count
        active_timers = (
            Sessions.objects.filter(user=user, end_time__isnull=True)
            .select_related("project")
            .prefetch_related(
                "subprojects",
                Prefetch(
                    "reminders",
                    queryset=TimerReminder.objects.filter(active=True)
                    .only(
                        "id",
                        "session_id",
                        "mode",
                        "next_fire_at",
                        "interval_seconds",
                        "message",
                        "last_fired_at",
                    )
                    .order_by("next_fire_at", "id"),
                    to_attr="active_reminders",
                ),
            )
        )
        active_timers = filter_by_active_context(active_timers, self.request)
        context["active_timers_count"] = active_timers.count()

        # 5. Active timers (up to 5)
        active_timers = list(active_timers[:5])
        context["active_timers"] = active_timers

        # 6. Timeline for the hero zone (see core/timeline.py). The range tabs
        # re-fetch it from timeline_fragment; the first paint comes from here.
        context["timeline"] = build_timeline(user, DEFAULT_RANGE)

        # 7. Quick-start chips on the "start something" focus card. Drawn from a
        # wider slice than the three sessions the recent list shows, so the
        # chips still offer three distinct combinations after de-duplication.
        quick_start_source = (
            Sessions.objects.filter(user=user, end_time__isnull=False)
            .select_related("project")
            .prefetch_related("subprojects")
            .order_by("-end_time")[:QUICK_START_LOOKBACK]
        )
        context["quick_starts"] = build_quick_starts(quick_start_source, active_timers)

        return context
