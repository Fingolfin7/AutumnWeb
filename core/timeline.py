"""Day-timeline data for the Focus Desk dashboard.

Turns a user's sessions for one calendar day into project lanes of blocks
positioned on an hour axis, plus the gaps between them and a "now" marker.

Everything is expressed in **percentages of the visible window** so the
template can position blocks with plain CSS custom properties and the chart
reflows at any width without JS.

Timezone: all arithmetic happens in the *currently active* timezone.
``users.middleware`` activates the user's profile timezone for every request,
so inside a view ``timezone.localtime()`` is already user-local. Tests should
activate a timezone explicitly rather than passing one in.
"""

from datetime import datetime, time, timedelta

from django.utils import timezone

from core.models import Sessions

#: Hours the axis always shows, even on an empty or tightly-packed day. The
#: window widens beyond this when sessions fall outside it (see _window_for).
DEFAULT_WINDOW_START = 6
DEFAULT_WINDOW_END = 22

#: Gaps shorter than this are visual noise between back-to-back sessions.
MIN_GAP_MINUTES = 20

#: Lane colours. The semantic convention fixes "project = red", so lanes are
#: shades of red rather than an arbitrary categorical palette — hue-value
#: identifies the project without breaking the convention.
LANE_COLOURS = ["#d0796f", "#c2665e", "#a8564f", "#b8746a", "#94473f", "#cf8a76"]


def _day_bounds(day):
    """Aware datetimes for the local start and end of ``day``."""
    start = timezone.make_aware(datetime.combine(day, time.min))
    return start, start + timedelta(days=1)


def _window_for(spans, now_local, is_today):
    """Pick the axis window (start_hour, end_hour) covering everything shown.

    Starts from the default 06:00-22:00 and widens to fit any session — and
    the now-marker — that falls outside it, so nothing is ever drawn off the
    edge of the chart.
    """
    start_hour, end_hour = DEFAULT_WINDOW_START, DEFAULT_WINDOW_END

    for span_start, span_end in spans:
        start_hour = min(start_hour, span_start.hour)
        # a session ending at 22:30 needs the axis to reach 23
        end_hour = max(end_hour, span_end.hour + (1 if span_end.minute or span_end.second else 0))

    if is_today:
        start_hour = min(start_hour, now_local.hour)
        end_hour = max(end_hour, now_local.hour + 1)

    return max(0, start_hour), min(24, max(end_hour, start_hour + 1))


def _pct(moment, window_start, window_minutes):
    """Position of ``moment`` as a percentage across the window."""
    offset = (moment - window_start).total_seconds() / 60.0
    return round(max(0.0, min(100.0, offset / window_minutes * 100.0)), 4)


def _collect_gaps(spans, window_start, window_minutes):
    """Untracked stretches between the first and last activity of the day.

    Spans are merged first, so overlapping sessions on different projects
    don't manufacture a gap that wasn't there.
    """
    if not spans:
        return []

    merged = []
    for span_start, span_end in sorted(spans):
        if merged and span_start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], span_end)
        else:
            merged.append([span_start, span_end])

    gaps = []
    for (_, prev_end), (next_start, _) in zip(merged, merged[1:]):
        minutes = (next_start - prev_end).total_seconds() / 60.0
        if minutes < MIN_GAP_MINUTES:
            continue
        start_pct = _pct(prev_end, window_start, window_minutes)
        gaps.append({
            "minutes": int(round(minutes)),
            "start_pct": start_pct,
            "width_pct": round(_pct(next_start, window_start, window_minutes) - start_pct, 4),
        })
    return gaps


def build_day_timeline(user, day=None):
    """Lanes, gaps and a now-marker for ``user`` on ``day`` (default: today).

    Returns a dict shaped for direct template consumption. ``lanes`` is empty
    when the day has no activity; callers should render an empty state rather
    than an empty chart.
    """
    day = day or timezone.localdate()
    day_start, day_end = _day_bounds(day)
    now = timezone.now()
    now_local = timezone.localtime(now)
    is_today = day == timezone.localdate()

    sessions = (
        Sessions.objects
        .filter(user=user, start_time__lt=day_end)
        .filter(models_q_overlapping(day_start))
        .select_related("project")
        .prefetch_related("subprojects")
        .order_by("start_time")
    )

    entries = []
    spans = []
    for session in sessions:
        running = session.end_time is None
        # A running timer is drawn up to now; a session crossing midnight is
        # clipped to the day being shown, so widths always match the axis.
        raw_end = now if running else session.end_time
        block_start = max(timezone.localtime(session.start_time), timezone.localtime(day_start))
        block_end = min(timezone.localtime(raw_end), timezone.localtime(day_end))
        if block_end <= block_start:
            continue
        entries.append((session, block_start, block_end, running))
        spans.append((block_start, block_end))

    window_start_hour, window_end_hour = _window_for(spans, now_local, is_today)
    window_start = timezone.make_aware(datetime.combine(day, time(hour=window_start_hour)))
    if window_end_hour >= 24:
        window_end = day_start + timedelta(days=1)
    else:
        window_end = timezone.make_aware(datetime.combine(day, time(hour=window_end_hour)))
    window_minutes = (window_end - window_start).total_seconds() / 60.0

    lanes_by_project = {}
    for session, block_start, block_end, running in entries:
        minutes = (block_end - block_start).total_seconds() / 60.0
        start_pct = _pct(block_start, window_start, window_minutes)
        lane = lanes_by_project.setdefault(session.project_id, {
            "project": session.project,
            "total_minutes": 0.0,
            "live_minutes": 0.0,
            "blocks": [],
        })
        lane["blocks"].append({
            "session": session,
            "is_live": running,
            "minutes": minutes,
            "start_pct": start_pct,
            "width_pct": round(_pct(block_end, window_start, window_minutes) - start_pct, 4),
            "label": ", ".join(sub.name for sub in session.subprojects.all()),
            "start_local": block_start,
            "end_local": None if running else block_end,
        })
        if running:
            lane["live_minutes"] += minutes
        else:
            lane["total_minutes"] += minutes

    lanes = sorted(
        lanes_by_project.values(),
        key=lambda lane: lane["total_minutes"] + lane["live_minutes"],
        reverse=True,
    )
    for index, lane in enumerate(lanes):
        lane["colour"] = LANE_COLOURS[index % len(LANE_COLOURS)]

    now_pct = None
    if is_today and window_start <= now <= window_end:
        now_pct = _pct(now, window_start, window_minutes)

    return {
        "date": day,
        "window_start_hour": window_start_hour,
        "window_end_hour": window_end_hour,
        "hours": [
            {
                "hour": hour,
                "label": "{:02d}".format(hour % 24),
                "x_pct": round((hour - window_start_hour) / (window_end_hour - window_start_hour) * 100.0, 4),
            }
            for hour in range(window_start_hour, window_end_hour + 1)
        ],
        "lanes": lanes,
        "gaps": _collect_gaps(spans, window_start, window_minutes),
        "now_pct": now_pct,
        "now_label": timezone.localtime(now).strftime("%H:%M") if now_pct is not None else None,
    }


def models_q_overlapping(day_start):
    """Sessions that are unfinished, or that ended on/after ``day_start``.

    Split out so the filter reads clearly at the call site: a session belongs
    to the day if it overlaps it, not merely if it started in it.
    """
    from django.db.models import Q

    return Q(end_time__isnull=True) | Q(end_time__gt=day_start)
