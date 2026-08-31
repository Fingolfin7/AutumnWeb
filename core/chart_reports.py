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
from core.attribution import subproject_daily_series, subproject_session_points


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

CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
MARKDOWN_MARKER_RE = re.compile(r"(\*{1,2}|_{1,2}|~{1,2})")
MARKDOWN_HEADING_RE = re.compile(r"#{1,6}\s")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
INLINE_CODE_RE = re.compile(r"`[^`]+`")
WORD_RE = re.compile(r"\b[a-z]+\b")
WORDCLOUD_NOTE_BATCH_SIZE = 1_000


def _duration_expression():
    return ExpressionWrapper(
        F("end_time") - F("start_time"), output_field=DurationField()
    )


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


def _text_words(text):
    """Yield word-cloud terms from a bounded batch of session-note text."""

    clean_text = CODE_BLOCK_RE.sub("", text)
    clean_text = MARKDOWN_MARKER_RE.sub("", clean_text)
    clean_text = MARKDOWN_HEADING_RE.sub("", clean_text)
    clean_text = MARKDOWN_LINK_RE.sub(r"\1", clean_text)
    clean_text = INLINE_CODE_RE.sub("", clean_text)
    return (
        word
        for word in WORD_RE.findall(clean_text.lower())
        if word not in STOP_WORDS and len(word) > 2
    )


def _wordcloud(sessions):
    counts = Counter()
    note_batch = []
    notes = sessions.values_list("note", flat=True).iterator(
        chunk_size=WORDCLOUD_NOTE_BATCH_SIZE
    )
    for note in notes:
        if note:
            note_batch.append(note)
        if len(note_batch) >= WORDCLOUD_NOTE_BATCH_SIZE:
            counts.update(_text_words(" ".join(note_batch)))
            note_batch.clear()
    if note_batch:
        counts.update(_text_words(" ".join(note_batch)))
    return [
        {"text": word, "weight": weight}
        for word, weight in counts.most_common(100)
    ]


def build_chart_payload(chart_type, sessions, *, use_subprojects=False):
    """Build the legacy web-chart payload shape for an already filtered set."""
    if chart_type in SESSION_POINT_CHARTS:
        return _session_points(sessions, use_subprojects)
    elif chart_type in DAILY_SERIES_CHARTS:
        return _daily_series(sessions, use_subprojects)
    elif chart_type in DAILY_TOTAL_CHARTS:
        return _daily_totals(sessions)
    elif chart_type in INTERVAL_CHARTS:
        return _intervals(sessions)
    elif chart_type == "histogram":
        return _histogram(sessions)
    return _wordcloud(sessions)
