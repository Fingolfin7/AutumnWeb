"""Derived project-management totals for read paths.

These totals intentionally use legacy full-credit subproject attribution.  The
weighted analytics helpers in :mod:`core.attribution` have different semantics.
"""

from __future__ import annotations

from django.db.models import DateTimeField, F, FloatField, Func, Max, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from core.models import Projects, Sessions, SessionSubproject, SubProjects


class _RoundedSessionMinutes(Func):
    """Elapsed minutes rounded once per session before aggregation."""

    output_field = FloatField()

    def as_sqlite(self, compiler, connection, **extra_context):
        end_sql, end_params = compiler.compile(self.source_expressions[0])
        start_sql, start_params = compiler.compile(self.source_expressions[1])
        return (
            f"ROUND(django_timestamp_diff({end_sql}, {start_sql}) / 60000000.0, 4)",
            [*end_params, *start_params],
        )

    def as_postgresql(self, compiler, connection, **extra_context):
        end_sql, end_params = compiler.compile(self.source_expressions[0])
        start_sql, start_params = compiler.compile(self.source_expressions[1])
        return (
            "CAST(ROUND(CAST(EXTRACT(EPOCH FROM "
            f"({end_sql} - {start_sql})) / 60.0 AS numeric), 4) AS double precision)",
            [*end_params, *start_params],
        )

    def as_mysql(self, compiler, connection, **extra_context):
        end_sql, end_params = compiler.compile(self.source_expressions[0])
        start_sql, start_params = compiler.compile(self.source_expressions[1])
        return (
            f"ROUND(TIMESTAMPDIFF(MICROSECOND, {start_sql}, {end_sql}) / 60000000.0, 4)",
            [*start_params, *end_params],
        )


def rounded_session_minutes(end_field="end_time", start_field="start_time"):
    """Return the canonical per-session minutes expression."""

    return _RoundedSessionMinutes(F(end_field), F(start_field))


def _project_total_subquery(*, project_ref="pk"):
    return (
        Sessions.objects.filter(
            user_id=OuterRef("user_id"),
            project_id=OuterRef(project_ref),
            end_time__isnull=False,
        )
        .order_by()
        .values("project_id")
        .annotate(total=Sum(rounded_session_minutes()))
        .values("total")
    )


def _project_last_updated_subquery():
    return (
        Sessions.objects.filter(
            user_id=OuterRef("user_id"),
            project_id=OuterRef("pk"),
            end_time__isnull=False,
        )
        .order_by()
        .values("project_id")
        .annotate(latest=Max("end_time"))
        .values("latest")
    )


def _user_total_subquery():
    return (
        Sessions.objects.filter(
            user_id=OuterRef("user_id"),
            end_time__isnull=False,
        )
        .order_by()
        .values("user_id")
        .annotate(total=Sum(rounded_session_minutes()))
        .values("total")
    )


def _subproject_total_subquery():
    return (
        SessionSubproject.objects.filter(
            subproject_id=OuterRef("pk"),
            session__user_id=OuterRef("user_id"),
            session__end_time__isnull=False,
        )
        .order_by()
        .values("subproject_id")
        .annotate(
            total=Sum(
                rounded_session_minutes(
                    "session__end_time", "session__start_time"
                )
            )
        )
        .values("total")
    )


def _subproject_last_updated_subquery():
    return (
        SessionSubproject.objects.filter(
            subproject_id=OuterRef("pk"),
            session__user_id=OuterRef("user_id"),
            session__end_time__isnull=False,
        )
        .order_by()
        .values("subproject_id")
        .annotate(latest=Max("session__end_time"))
        .values("latest")
    )


def annotate_project_totals(queryset, *, include_user_total=False):
    """Annotate a Projects queryset with derived totals in its entity query."""

    annotations = {
        "derived_total_time": Coalesce(
            Subquery(_project_total_subquery(), output_field=FloatField()),
            Value(0.0),
        ),
        "derived_last_updated": Coalesce(
            Subquery(
                _project_last_updated_subquery(), output_field=DateTimeField()
            ),
            F("last_updated"),
        ),
    }
    if include_user_total:
        annotations["derived_user_total_time"] = Coalesce(
            Subquery(_user_total_subquery(), output_field=FloatField()),
            Value(0.0),
        )
    return queryset.annotate(**annotations)


def annotate_subproject_totals(queryset):
    """Annotate a SubProjects queryset with full-credit derived totals."""

    return queryset.annotate(
        derived_total_time=Coalesce(
            Subquery(_subproject_total_subquery(), output_field=FloatField()),
            Value(0.0),
        ),
        derived_last_updated=Coalesce(
            Subquery(
                _subproject_last_updated_subquery(), output_field=DateTimeField()
            ),
            F("last_updated"),
        ),
    )


def derived_project_totals(user, project_ids=None):
    queryset = Projects.objects.filter(user=user)
    if project_ids is not None:
        project_ids = list(project_ids)
        if not project_ids:
            return {}
        queryset = queryset.filter(pk__in=project_ids)
    return dict(
        annotate_project_totals(queryset).values_list("pk", "derived_total_time")
    )


def derived_subproject_totals(user, subproject_ids=None):
    queryset = SubProjects.objects.filter(user=user)
    if subproject_ids is not None:
        subproject_ids = list(subproject_ids)
        if not subproject_ids:
            return {}
        queryset = queryset.filter(pk__in=subproject_ids)
    return dict(
        annotate_subproject_totals(queryset).values_list(
            "pk", "derived_total_time"
        )
    )


def derived_project_last_updated(user, project_ids=None):
    queryset = Projects.objects.filter(user=user)
    if project_ids is not None:
        project_ids = list(project_ids)
        if not project_ids:
            return {}
        queryset = queryset.filter(pk__in=project_ids)
    return dict(
        annotate_project_totals(queryset).values_list(
            "pk", "derived_last_updated"
        )
    )


def derived_subproject_last_updated(user, subproject_ids=None):
    queryset = SubProjects.objects.filter(user=user)
    if subproject_ids is not None:
        subproject_ids = list(subproject_ids)
        if not subproject_ids:
            return {}
        queryset = queryset.filter(pk__in=subproject_ids)
    return dict(
        annotate_subproject_totals(queryset).values_list(
            "pk", "derived_last_updated"
        )
    )
