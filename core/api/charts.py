from __future__ import annotations

import re
from collections import Counter
from datetime import timedelta, timezone as datetime_timezone

from django.db.models import (
    Case,
    Count,
    DurationField,
    ExpressionWrapper,
    F,
    IntegerField,
    Sum,
    Value,
    When,
)
from django.db.models.functions import TruncDate
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api.helpers import _apply_exclude_filters, _apply_tag_filters
from core.attribution import subproject_daily_series, subproject_session_points
from core.models import Sessions
from core.utils import filter_by_active_context, filter_sessions_by_params


SESSION_POINT_CHARTS = {"scatter"}
DAILY_SERIES_CHARTS = {"line", "stacked_area"}
DAILY_TOTAL_CHARTS = {"calendar", "cumulative"}
INTERVAL_CHARTS = {"heatmap"}
SUMMARY_CHARTS = {"histogram", "wordcloud"}
SUPPORTED_CHARTS = (
    SESSION_POINT_CHARTS
    | DAILY_SERIES_CHARTS
    | DAILY_TOTAL_CHARTS
    | INTERVAL_CHARTS
    | SUMMARY_CHARTS
)

HISTOGRAM_LABELS = ["0-15m", "15-30m", "30-60m", "1-2h", "2-4h", "4-8h", "8h+"]

STOP_WORDS = {
    "the", "and", "is", "in", "at", "of", "a", "an", "to", "for", "with",
    "on", "by", "it", "this", "that", "from", "as", "be", "are", "was",
    "were", "has", "have", "had", "but", "or", "not", "which", "we", "you",
    "they", "he", "she", "i", "me", "my", "mine", "your", "yours", "about",
    "if", "so", "then", "there", "here", "where", "when", "how", "can", "will",
    "would", "could", "should", "may", "might", "must", "just", "also", "some",
    "all", "any", "more", "most", "other", "into", "over", "such", "no", "than",
    "too", "very", "only", "own", "same", "now", "been", "being", "each", "few",
    "both", "these", "those", "what", "while", "who", "whom", "why", "did",
    "does", "doing", "done", "get", "got", "getting",
}


def _duration_expression():
    return ExpressionWrapper(
        F("end_time") - F("start_time"), output_field=DurationField()
    )


def _filtered_sessions(request):
    sessions = Sessions.objects.filter(end_time__isnull=False, user=request.user)
    sessions = filter_by_active_context(
        sessions,
        request,
        override_context_id=request.query_params.get("context"),
    )
    sessions = _apply_tag_filters(
        request.query_params, sessions, kind="sessions", user=request.user
    )
    sessions = _apply_exclude_filters(
        request.query_params, sessions, kind="sessions", user=request.user
    )
    sessions = filter_sessions_by_params(request, sessions)
    return Sessions.objects.filter(pk__in=sessions.values("pk")).order_by()


def _duration_hours(duration):
    return duration.total_seconds() / 3600.0 if duration else 0.0


def _session_points(sessions, use_subprojects):
    if use_subprojects:
        rows = subproject_session_points(sessions)
        return [
            {
                "x": row["end_time"],
                "y": _duration_hours(row["duration_value"]),
                "series": row["series"],
            }
            for row in rows
        ]

    rows = (
        sessions.annotate(
            series=F("project__name"),
            duration_value=_duration_expression(),
        )
        .values("end_time", "series", "duration_value")
        .order_by("-end_time", "series")
    )
    return [
        {
            "x": row["end_time"],
            "y": _duration_hours(row["duration_value"]),
            "series": row["series"],
        }
        for row in rows
    ]


def _daily_series(sessions, use_subprojects):
    if use_subprojects:
        rows = subproject_daily_series(sessions)
        return [
            {
                "date": row["date"],
                "series": row["series"],
                "hours": _duration_hours(row["total"]),
            }
            for row in rows
        ]

    rows = (
        sessions.annotate(
            date=TruncDate("start_time", tzinfo=datetime_timezone.utc),
            series=F("project__name"),
        )
        .values("date", "series")
        .annotate(total=Sum(_duration_expression()))
        .order_by("date", "series")
    )
    return [
        {
            "date": row["date"],
            "series": row["series"],
            "hours": _duration_hours(row["total"]),
        }
        for row in rows
    ]


def _daily_totals(sessions):
    rows = (
        sessions.annotate(date=TruncDate("start_time", tzinfo=datetime_timezone.utc))
        .values("date")
        .annotate(total=Sum(_duration_expression()))
        .order_by("date")
    )
    return [
        {"date": row["date"], "hours": _duration_hours(row["total"])}
        for row in rows
    ]


def _intervals(sessions):
    return list(sessions.order_by("-end_time").values("start_time", "end_time"))


def _histogram(sessions):
    rows = (
        sessions.annotate(duration_value=_duration_expression())
        .annotate(
            bucket=Case(
                When(duration_value__lt=timedelta(minutes=15), then=Value(0)),
                When(duration_value__lt=timedelta(minutes=30), then=Value(1)),
                When(duration_value__lt=timedelta(hours=1), then=Value(2)),
                When(duration_value__lt=timedelta(hours=2), then=Value(3)),
                When(duration_value__lt=timedelta(hours=4), then=Value(4)),
                When(duration_value__lt=timedelta(hours=8), then=Value(5)),
                default=Value(6),
                output_field=IntegerField(),
            )
        )
        .values("bucket")
        .annotate(count=Count("pk"))
        .order_by("bucket")
    )
    counts = {row["bucket"]: row["count"] for row in rows}
    if not counts:
        return []
    return [
        {"label": label, "count": counts.get(index, 0)}
        for index, label in enumerate(HISTOGRAM_LABELS)
    ]


def _wordcloud(sessions):
    notes_text = " ".join(
        note or "" for note in sessions.values_list("note", flat=True).iterator()
    )
    clean_text = re.sub(r"```[\s\S]*?```", "", notes_text)
    clean_text = re.sub(r"(\*{1,2}|_{1,2}|~{1,2})", "", clean_text)
    clean_text = re.sub(r"#{1,6}\s", "", clean_text)
    clean_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean_text)
    clean_text = re.sub(r"`[^`]+`", "", clean_text)
    words = re.findall(r"\b[a-z]+\b", clean_text.lower())
    counts = Counter(
        word for word in words if word not in STOP_WORDS and len(word) > 2
    )
    return [
        {"text": word, "weight": weight}
        for word, weight in counts.most_common(100)
    ]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def chart_data(request):
    chart_type = (request.query_params.get("chart_type") or "").strip().lower()
    if chart_type not in SUPPORTED_CHARTS:
        return Response(
            {"detail": "Unsupported chart_type"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    sessions = _filtered_sessions(request)
    use_subprojects = bool((request.query_params.get("project_name") or "").strip())

    if chart_type in SESSION_POINT_CHARTS:
        payload = _session_points(sessions, use_subprojects)
    elif chart_type in DAILY_SERIES_CHARTS:
        payload = _daily_series(sessions, use_subprojects)
    elif chart_type in DAILY_TOTAL_CHARTS:
        payload = _daily_totals(sessions)
    elif chart_type in INTERVAL_CHARTS:
        payload = _intervals(sessions)
    elif chart_type == "histogram":
        payload = _histogram(sessions)
    else:
        payload = _wordcloud(sessions)

    return Response(payload)
