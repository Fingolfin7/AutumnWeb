"""Query helpers for weighted subproject attribution.

All weighted paths aggregate elapsed microseconds multiplied by basis points as
BIGINT numerators.  Division by ``BASIS_POINTS`` happens before callers perform
their existing minutes/hours conversion.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta, timezone as datetime_timezone

from django.db.models import (
    BigIntegerField,
    Case,
    ExpressionWrapper,
    F,
    Func,
    IntegerField,
    Max,
    OuterRef,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Cast, Coalesce, TruncDate

from core.models import Sessions, SessionSubproject


BASIS_POINTS = 10000
NO_SUBPROJECT = "no subproject"


class _ElapsedMicroseconds(Func):
    """Portable BIGINT elapsed-time expression for supported databases."""

    output_field = BigIntegerField()

    def as_sqlite(self, compiler, connection, **extra_context):
        end_sql, end_params = compiler.compile(self.source_expressions[0])
        start_sql, start_params = compiler.compile(self.source_expressions[1])
        return (
            f"django_timestamp_diff({end_sql}, {start_sql})",
            [*end_params, *start_params],
        )

    def as_postgresql(self, compiler, connection, **extra_context):
        end_sql, end_params = compiler.compile(self.source_expressions[0])
        start_sql, start_params = compiler.compile(self.source_expressions[1])
        return (
            "CAST(EXTRACT(EPOCH FROM "
            f"({end_sql} - {start_sql})) * 1000000 AS bigint)",
            [*end_params, *start_params],
        )


def _elapsed_microseconds():
    return _ElapsedMicroseconds(F("end_time"), F("start_time"))


def _duration_numerator(duration):
    if duration is None:
        return 0
    microseconds = (
        (duration.days * 86400 + duration.seconds) * 1000000
        + duration.microseconds
    )
    return microseconds * BASIS_POINTS


def duration_from_numerator(numerator):
    """Divide the BIGINT numerator before the existing unit conversion."""

    if not numerator:
        return timedelta(0)
    whole_microseconds, remainder = divmod(numerator, BASIS_POINTS)
    if remainder == 0:
        return timedelta(microseconds=whole_microseconds)
    return timedelta(microseconds=numerator / BASIS_POINTS)


def _reanchor(sessions_qs):
    return Sessions.objects.filter(
        pk__in=sessions_qs.order_by().values("pk")
    ).order_by()


def _with_allocation_total(sessions):
    allocation_totals = (
        SessionSubproject.objects.filter(session_id=OuterRef("pk"))
        .order_by()
        .values("session_id")
        .annotate(total=Sum("allocation_bp"))
        .values("total")
    )
    return sessions.annotate(
        _allocation_total=Coalesce(
            Subquery(allocation_totals, output_field=IntegerField()),
            Value(0),
        )
    )


def _with_link_numerator(sessions):
    return (
        sessions.filter(subproject_links__isnull=False)
        .annotate(
            _weighted_numerator=ExpressionWrapper(
                _elapsed_microseconds() * F("subproject_links__allocation_bp"),
                output_field=BigIntegerField(),
            )
        )
    )


def _with_residual_numerator(sessions):
    return (
        _with_allocation_total(sessions)
        .annotate(
            _residual_bp=Case(
                When(_allocation_total=0, then=Value(BASIS_POINTS)),
                When(
                    _allocation_total__lt=BASIS_POINTS,
                    then=Value(BASIS_POINTS) - F("_allocation_total"),
                ),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .filter(_residual_bp__gt=0)
        .annotate(
            _weighted_numerator=ExpressionWrapper(
                _elapsed_microseconds() * F("_residual_bp"),
                output_field=BigIntegerField(),
            )
        )
    )


def _latest_first(rows, secondary_key):
    rows.sort(key=secondary_key)
    rows.sort(
        key=lambda row: row["latest_end_time"]
        or row.get("end_time")
        or row.get("date"),
        reverse=True,
    )
    return rows


def subproject_tally(sessions_qs, *, group_by_id=False):
    """Return weighted subproject totals, including the residual bucket.

    ``group_by_id`` preserves the older ``totals`` endpoint's ID-based bucket
    ordering.  The default groups by name exactly like ``tally_by_subprojects``.
    """

    sessions = _reanchor(sessions_qs)
    link_sessions = _with_link_numerator(sessions)
    if group_by_id:
        link_rows = list(
            link_sessions.annotate(
                subproject_id=F("subproject_links__subproject_id"),
                name=F("subproject_links__subproject__name"),
            )
            .values("subproject_id", "name")
            .annotate(
                total_numerator=Cast(
                    Sum("_weighted_numerator"), BigIntegerField()
                ),
                latest_end_time=Max("end_time"),
            )
        )
        row_key = lambda row: row["subproject_id"]
        secondary_key = lambda row: (
            row["subproject_id"] is not None,
            row["subproject_id"] or 0,
        )
    else:
        link_rows = list(
            link_sessions.annotate(
                name=F("subproject_links__subproject__name")
            )
            .values("name")
            .annotate(
                total_numerator=Cast(
                    Sum("_weighted_numerator"), BigIntegerField()
                ),
                latest_end_time=Max("end_time"),
            )
        )
        row_key = lambda row: row["name"]
        secondary_key = lambda row: row["name"]

    rows_by_key = {row_key(row): row for row in link_rows}
    residual = _with_residual_numerator(sessions).aggregate(
        total_numerator=Cast(Sum("_weighted_numerator"), BigIntegerField()),
        latest_end_time=Max("end_time"),
    )
    if residual["total_numerator"]:
        residual_key = None if group_by_id else NO_SUBPROJECT
        if residual_key in rows_by_key:
            row = rows_by_key[residual_key]
            row["total_numerator"] += residual["total_numerator"]
            row["latest_end_time"] = max(
                row["latest_end_time"], residual["latest_end_time"]
            )
        else:
            row = {
                "name": NO_SUBPROJECT,
                "total_numerator": residual["total_numerator"],
                "latest_end_time": residual["latest_end_time"],
            }
            if group_by_id:
                row["subproject_id"] = None
            rows_by_key[residual_key] = row

    rows = list(rows_by_key.values())
    for row in rows:
        row["total"] = duration_from_numerator(row["total_numerator"])
    return _latest_first(rows, secondary_key)


def subproject_session_points(sessions_qs):
    """Return one weighted scatter point per session/subproject bucket."""

    sessions = _reanchor(sessions_qs)
    link_rows = list(
        _with_link_numerator(sessions)
        .annotate(series=F("subproject_links__subproject__name"))
        .values("pk", "end_time", "series", "_weighted_numerator")
    )
    rows_by_key = {
        (row["pk"], row["series"]): {
            "end_time": row["end_time"],
            "series": row["series"],
            "duration_numerator": row["_weighted_numerator"],
        }
        for row in link_rows
    }
    for row in _with_residual_numerator(sessions).values(
        "pk", "end_time", "_weighted_numerator"
    ):
        key = (row["pk"], NO_SUBPROJECT)
        if key in rows_by_key:
            rows_by_key[key]["duration_numerator"] += row[
                "_weighted_numerator"
            ]
        else:
            rows_by_key[key] = {
                "end_time": row["end_time"],
                "series": NO_SUBPROJECT,
                "duration_numerator": row["_weighted_numerator"],
            }

    rows = list(rows_by_key.values())
    for row in rows:
        row["duration_value"] = duration_from_numerator(
            row["duration_numerator"]
        )
    rows.sort(key=lambda row: row["series"])
    rows.sort(key=lambda row: row["end_time"], reverse=True)
    return rows


def subproject_daily_series(sessions_qs):
    """Return weighted UTC-day/subproject aggregates, including residuals."""

    sessions = _reanchor(sessions_qs)
    date_expression = TruncDate(
        "start_time", tzinfo=datetime_timezone.utc
    )
    link_rows = list(
        _with_link_numerator(sessions)
        .annotate(
            date=date_expression,
            series=F("subproject_links__subproject__name"),
        )
        .values("date", "series")
        .annotate(
            total_numerator=Cast(
                Sum("_weighted_numerator"), BigIntegerField()
            )
        )
    )
    rows_by_key = {(row["date"], row["series"]): row for row in link_rows}
    residual_rows = (
        _with_residual_numerator(sessions)
        .annotate(date=date_expression)
        .values("date")
        .annotate(
            total_numerator=Cast(
                Sum("_weighted_numerator"), BigIntegerField()
            )
        )
    )
    for residual in residual_rows:
        key = (residual["date"], NO_SUBPROJECT)
        if key in rows_by_key:
            rows_by_key[key]["total_numerator"] += residual[
                "total_numerator"
            ]
        else:
            rows_by_key[key] = {
                "date": residual["date"],
                "series": NO_SUBPROJECT,
                "total_numerator": residual["total_numerator"],
            }

    rows = list(rows_by_key.values())
    for row in rows:
        row["total"] = duration_from_numerator(row["total_numerator"])
    rows.sort(key=lambda row: (row["date"], row["series"]))
    return rows


def hierarchy_child_credit(sessions_qs):
    """Return weighted link credit by subproject ID, with no residual row."""

    sessions = _reanchor(sessions_qs)
    rows = list(
        _with_link_numerator(sessions)
        .annotate(subproject_id=F("subproject_links__subproject_id"))
        .values("subproject_id")
        .annotate(
            total_numerator=Cast(
                Sum("_weighted_numerator"), BigIntegerField()
            )
        )
        .order_by()
    )
    for row in rows:
        row["total"] = duration_from_numerator(row["total_numerator"])
    return rows


def report_attribution(sessions_qs):
    """Partition filtered sessions into per-project link and residual credit.

    Values stay as integer ``duration microseconds * basis points`` numerators
    until report views convert them to minutes.
    """

    projects = {}
    sessions = (
        _reanchor(sessions_qs)
        .select_related("project")
        .prefetch_related("subproject_links__subproject")
    )
    for session in sessions.iterator(chunk_size=500):
        project = projects.setdefault(
            session.project_id,
            {
                "id": session.project_id,
                "name": session.project.name,
                "total_numerator": 0,
                "children": defaultdict(
                    lambda: {"id": None, "name": None, "total_numerator": 0}
                ),
                "residual_numerator": 0,
            },
        )
        duration_numerator = _duration_numerator(
            session.end_time - session.start_time
        )
        project["total_numerator"] += duration_numerator

        links = list(session.subproject_links.all())
        allocation_total = sum(link.allocation_bp for link in links)
        for link in links:
            child = project["children"][link.subproject_id]
            child["id"] = link.subproject_id
            child["name"] = link.subproject.name
            child["total_numerator"] += (
                duration_numerator * link.allocation_bp // BASIS_POINTS
            )

        residual_bp = 0
        if not links:
            residual_bp = BASIS_POINTS
        elif allocation_total < BASIS_POINTS:
            residual_bp = BASIS_POINTS - allocation_total
        project["residual_numerator"] += (
            duration_numerator * residual_bp // BASIS_POINTS
        )

    for project in projects.values():
        project["children"] = dict(project["children"])
    return projects
