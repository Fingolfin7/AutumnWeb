from datetime import datetime, time, timedelta

from django.db.models import Prefetch
from django.utils import timezone

from core.commitments import (
    calculate_commitment_streak,
    get_commitment_progress,
    reconcile_commitment,
)
from core.models import Commitment, Sessions, TimerReminder
from core.timeline import DEFAULT_RANGE, build_timeline
from core.totals import session_minute_totals_since
from core.utils import (
    calculate_daily_activity_streak,
    filter_by_active_context,
    group_sessions_by_date,
    stop_expired_timers,
)


QUICK_START_LIMIT = 3
QUICK_START_LOOKBACK = 40

RECENT_SESSION_DAY_LIMIT = 3
RECENT_SESSION_EXPANSION_THRESHOLD = 3
RECENT_SESSION_EXPANSION_LIMIT = 5


def _combo_key(session):
    return (session.project_id, frozenset(sub.id for sub in session.subprojects.all()))


def build_quick_starts(recent_sessions, active_timers):
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
    sessions = (
        Sessions.objects.filter(user=user, end_time__isnull=False)
        .select_related("project")
        .prefetch_related("subprojects")
        .order_by("-end_time", "-id")
    )
    return select_recent_dashboard_sessions(sessions.iterator(chunk_size=100))


def build_dashboard_timeline(
    user,
    range_key=DEFAULT_RANGE,
    *,
    start_date=None,
    end_date=None,
    context=None,
):
    return build_timeline(
        user,
        range_key,
        end_day=end_date,
        start_day=start_date,
        context=context,
    )


def build_dashboard(user, *, context=None, now=None) -> dict:
    stop_expired_timers(user, now=now)
    now = now or timezone.now()

    commitments_data = []
    commitments = Commitment.objects.filter(user=user, active=True).select_related(
        "project", "subproject", "context", "tag"
    )
    for commitment in commitments:
        reconcile_commitment(commitment)
        progress = get_commitment_progress(commitment)
        streak = calculate_commitment_streak(commitment)
        commitments_data.append(
            {"commitment": commitment, "progress": progress, "streak": streak}
        )
    commitments_data.sort(key=lambda item: item["progress"]["percentage"])

    recent_sessions = get_recent_dashboard_sessions(user)
    local_today = timezone.localdate(now)
    today_start = timezone.make_aware(datetime.combine(local_today, time.min))
    week_start = today_start - timedelta(days=local_today.weekday())
    summary_totals = session_minute_totals_since(
        user,
        today_total=today_start,
        week_total=week_start,
    )

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
    if context is not None:
        active_timers = filter_by_active_context(active_timers, context)
    active_timers_count = active_timers.count()
    active_timers = list(active_timers[:5])

    quick_start_source = (
        Sessions.objects.filter(user=user, end_time__isnull=False)
        .select_related("project")
        .prefetch_related("subprojects")
        .order_by("-end_time")[:QUICK_START_LOOKBACK]
    )

    return {
        "daily_streak": calculate_daily_activity_streak(user, days=30),
        "commitments_data": commitments_data,
        "recent_sessions": recent_sessions,
        "grouped_sessions": group_sessions_by_date(recent_sessions),
        **summary_totals,
        "active_timers_count": active_timers_count,
        "active_timers": active_timers,
        "timeline": build_dashboard_timeline(user),
        "quick_starts": build_quick_starts(quick_start_source, active_timers),
    }
