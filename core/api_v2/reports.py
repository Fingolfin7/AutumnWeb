from __future__ import annotations

from django.db.models import Count, DurationField, ExpressionWrapper, F, Sum
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api_helpers import _apply_exclude_filters, _apply_tag_filters
from core.api_v2.exceptions import V2APIView
from core.api_v2.filters import SessionFilterSpec
from core.api_v2.serializers import (
    ChartPayloadRowSerializer,
    ReportHierarchySerializer,
    ReportTalliesSerializer,
    ReportTotalsSerializer,
)
from core.attribution import BASIS_POINTS, hierarchy_child_credit, report_attribution
from core.chart_reports import SUPPORTED_CHARTS, build_chart_payload
from core.models import Context, Projects, Sessions
from core.totals import annotate_project_totals, rounded_session_minutes
from core.utils import filter_by_active_context, filter_sessions_by_params

# Chart types the web page renders from legacy-shaped tallies/hierarchies.
# They moved under this endpoint when the v1 API was removed (S12); the
# payload shapes intentionally match the old v1 endpoints the chart JS
# already consumes.
LEGACY_TALLY_CHARTS = {"pie", "bar", "context", "status", "bubble"}
LEGACY_TREE_CHARTS = {"treemap", "radar"}


TALLY_KINDS = ("project", "subproject", "context", "status", "tag")
FILTER_PARAMETERS = [
    OpenApiParameter(
        name=name,
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=description,
    )
    for name, description in (
        ("project_ids", "Comma-separated project IDs."),
        ("subproject_ids", "Comma-separated subproject IDs."),
        ("context_ids", "Comma-separated context IDs."),
        ("tag_ids", "Comma-separated tag IDs."),
        ("exclude_project_ids", "Comma-separated project IDs to exclude."),
        ("exclude_subproject_ids", "Comma-separated subproject IDs to exclude."),
        ("exclude_tag_ids", "Comma-separated tag IDs to exclude."),
        ("start_date", "Inclusive local date in YYYY-MM-DD format."),
        ("end_date", "Inclusive local date in YYYY-MM-DD format."),
        ("active", "Filter by active state (true or false)."),
        ("note_snippet", "Case-insensitive note substring."),
    )
]


def _duration_expression():
    return ExpressionWrapper(
        F("end_time") - F("start_time"), output_field=DurationField()
    )


def _minutes(duration):
    if not duration:
        return 0.0
    return round(duration.total_seconds() / 60.0, 2)


def _numerator_minutes(numerator):
    return round(numerator / BASIS_POINTS / 60_000_000.0, 2)


def _session_filter(request):
    return SessionFilterSpec.from_query_params(request.query_params, request.user)


def _filtered_completed_sessions(request):
    sessions = Sessions.objects.filter(
        user=request.user,
        end_time__isnull=False,
    )
    sessions = _session_filter(request).apply(sessions)
    return Sessions.objects.filter(pk__in=sessions.order_by().values("pk")).order_by()


def _ordered(entries):
    return sorted(
        entries,
        key=lambda entry: (
            -entry["total_minutes"],
            entry.get("name") or "",
            entry.get("id") or 0,
        ),
    )


class ReportTotalsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=FILTER_PARAMETERS, responses=ReportTotalsSerializer)
    def get(self, request):
        aggregate = _filtered_completed_sessions(request).aggregate(
            total=Sum(_duration_expression()),
            session_count=Count("pk"),
        )
        return Response(
            {
                "total_minutes": _minutes(aggregate["total"]),
                "session_count": aggregate["session_count"],
            }
        )


class ReportTalliesView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            *FILTER_PARAMETERS,
            OpenApiParameter(
                name="by",
                type=OpenApiTypes.STR,
                enum=TALLY_KINDS,
                location=OpenApiParameter.QUERY,
                required=True,
            ),
        ],
        responses=ReportTalliesSerializer,
    )
    def get(self, request):
        tally_kind = (request.query_params.get("by") or "").strip().lower()
        if tally_kind not in TALLY_KINDS:
            raise ValidationError(
                {"by": ["Choose project, subproject, context, status, or tag."]}
            )

        sessions = _filtered_completed_sessions(request)
        if tally_kind == "subproject":
            entries = self._subproject_entries(sessions)
        else:
            entries = self._full_duration_entries(sessions, tally_kind)
        return Response({"by": tally_kind, "entries": _ordered(entries)})

    @staticmethod
    def _subproject_entries(sessions):
        entries = []
        for project in report_attribution(sessions).values():
            for child in project["children"].values():
                entry = {
                    "kind": "subproject",
                    "id": child["id"],
                    "name": child["name"],
                    "project_id": project["id"],
                    "total_minutes": _numerator_minutes(
                        child["total_numerator"]
                    ),
                }
                if project["legacy_overallocated"]:
                    entry["legacy_overallocated"] = True
                entries.append(entry)
            if project["residual_numerator"] > 0:
                entry = {
                    "kind": "residual",
                    "project_id": project["id"],
                    "id": None,
                    "name": None,
                    "total_minutes": _numerator_minutes(
                        project["residual_numerator"]
                    ),
                }
                if project["legacy_overallocated"]:
                    entry["legacy_overallocated"] = True
                entries.append(entry)
        return entries

    @staticmethod
    def _full_duration_entries(sessions, tally_kind):
        fields = {
            "project": ("project_id", "project__name"),
            "context": ("project__context_id", "project__context__name"),
            "status": (None, "project__status"),
            "tag": ("project__tags__id", "project__tags__name"),
        }
        id_field, name_field = fields[tally_kind]
        source = sessions
        if tally_kind == "tag":
            source = source.filter(project__tags__isnull=False)
        value_fields = [name_field]
        if id_field:
            value_fields.insert(0, id_field)
        rows = source.values(*value_fields).annotate(
            total=Sum(_duration_expression()),
            session_count=Count("pk"),
        )
        entries = []
        for row in rows:
            entry_id = row[id_field] if id_field else None
            name = row[name_field]
            if tally_kind == "context" and entry_id is None:
                name = "General"
            entries.append(
                {
                    "id": entry_id,
                    "name": name,
                    "total_minutes": _minutes(row["total"]),
                    "session_count": row["session_count"],
                }
            )
        return entries


class ReportHierarchyView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=FILTER_PARAMETERS, responses=ReportHierarchySerializer)
    def get(self, request):
        projects = []
        for project in report_attribution(
            _filtered_completed_sessions(request)
        ).values():
            children = [
                {
                    "kind": "subproject",
                    "id": child["id"],
                    "name": child["name"],
                    "total_minutes": _numerator_minutes(
                        child["total_numerator"]
                    ),
                }
                for child in project["children"].values()
            ]
            if project["residual_numerator"] > 0:
                children.append(
                    {
                        "kind": "residual",
                        "project_id": project["id"],
                        "id": None,
                        "name": None,
                        "total_minutes": _numerator_minutes(
                            project["residual_numerator"]
                        ),
                    }
                )
            children = _ordered(children)
            projects.append(
                {
                    "id": project["id"],
                    "name": project["name"],
                    "total_minutes": _numerator_minutes(
                        project["total_numerator"]
                    ),
                    "children": children,
                    "legacy_overallocated": project["legacy_overallocated"],
                }
            )
        projects = _ordered(projects)
        return Response({"projects": projects})


class ReportChartsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            *FILTER_PARAMETERS,
            OpenApiParameter(
                name="chart_type",
                type=OpenApiTypes.STR,
                enum=sorted(SUPPORTED_CHARTS),
                location=OpenApiParameter.QUERY,
                required=True,
            ),
            OpenApiParameter("project_name", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("context", OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter("tags", OpenApiTypes.INT, OpenApiParameter.QUERY, many=True),
            OpenApiParameter(
                "exclude_projects",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                many=True,
            ),
        ],
        responses=ChartPayloadRowSerializer(many=True),
    )
    def get(self, request):
        chart_type = (request.query_params.get("chart_type") or "").strip().lower()
        if chart_type not in SUPPORTED_CHARTS | LEGACY_TALLY_CHARTS | LEGACY_TREE_CHARTS:
            raise ValidationError({"chart_type": ["Unsupported chart_type."]})

        sessions = Sessions.objects.filter(
            user=request.user,
            end_time__isnull=False,
        )
        sessions = _session_filter(request).apply(sessions)

        # The web page still selects projects by name and uses its established
        # context/tag/exclusion controls. Dates are deliberately omitted here:
        # SessionFilterSpec above is their sole parser and applies user-TZ days.
        legacy_params = request.query_params.copy()
        legacy_params.pop("start_date", None)
        legacy_params.pop("end_date", None)
        sessions = filter_by_active_context(
            sessions,
            request,
            override_context_id=request.query_params.get("context"),
        )
        sessions = _apply_tag_filters(
            request.query_params,
            sessions,
            kind="sessions",
            user=request.user,
        )
        sessions = _apply_exclude_filters(
            request.query_params,
            sessions,
            kind="sessions",
            user=request.user,
        )
        sessions = filter_sessions_by_params(
            request,
            sessions,
            params_override=legacy_params,
        )
        sessions = Sessions.objects.filter(
            pk__in=sessions.order_by().values("pk")
        ).order_by()

        want_subprojects = bool(
            (request.query_params.get("project_name") or "").strip()
        )
        if chart_type in LEGACY_TALLY_CHARTS:
            return Response(
                self._legacy_tally_payload(
                    chart_type, sessions, want_subprojects, request.user
                )
            )
        if chart_type == "treemap":
            return Response(self._legacy_hierarchy_payload(request, sessions))
        if chart_type == "radar":
            return Response(self._legacy_radar_payload(request, sessions))

        payload = build_chart_payload(
            chart_type,
            sessions,
            use_subprojects=want_subprojects,
        )
        return Response(payload)

    @staticmethod
    def _legacy_tally_payload(chart_type, sessions, want_subprojects, user):
        """[{"name", "total_time"}] rows exactly as the removed v1 tallies."""
        if chart_type in ("pie", "bar") and want_subprojects:
            entries = ReportTalliesView._subproject_entries(sessions)
            buckets: dict[str, float] = {}
            for entry in entries:
                name = entry["name"] if entry["kind"] != "residual" else "no subproject"
                buckets[name] = buckets.get(name, 0.0) + entry["total_minutes"]
            return [
                {"name": name, "total_time": total}
                for name, total in buckets.items()
            ]
        if chart_type == "status":
            # v1 shape: per-status project counts plus session time.
            from django.db.models import Min

            status_counts = list(
                Projects.objects.filter(user=user)
                .order_by()
                .values("status")
                .annotate(count=Count("pk", distinct=True), first=Min("name"))
                .order_by("first", "status")
            )
            status_times = {
                row["project__status"]: _minutes(row["total"])
                for row in sessions.values("project__status").annotate(
                    total=Sum(_duration_expression())
                )
            }
            return [
                {
                    "status": row["status"],
                    "count": row["count"],
                    "total_time": status_times.get(row["status"], 0),
                }
                for row in status_counts
            ]
        if chart_type == "bubble":
            # v1 shape: tag rows with project counts and colors.
            return [
                {
                    "name": row["project__tags__name"],
                    "tag_id": row["project__tags__id"],
                    "total_time": _minutes(row["total"]),
                    "project_count": row["project_count"],
                    "color": row["project__tags__color"] or None,
                }
                for row in sessions.filter(project__tags__isnull=False)
                .values(
                    "project__tags__id",
                    "project__tags__name",
                    "project__tags__color",
                )
                .annotate(
                    total=Sum(_duration_expression()),
                    project_count=Count("project_id", distinct=True),
                )
                .order_by("project__tags__name")
            ]
        kind = {"pie": "project", "bar": "project", "context": "context"}[chart_type]
        entries = ReportTalliesView._full_duration_entries(sessions, kind)
        return [
            {"name": entry["name"], "total_time": entry["total_minutes"]}
            for entry in entries
        ]

    @staticmethod
    def _legacy_hierarchy_payload(request, sessions):
        """The removed v1 hierarchy shape consumed by the treemap chart."""
        user = request.user
        project_times = {
            row["project_id"]: _minutes(row["total"])
            for row in sessions.values("project_id").annotate(
                total=Sum(_duration_expression())
            )
        }
        subproject_times = {
            row["subproject_id"]: _numerator_minutes(row["total_numerator"])
            for row in hierarchy_child_credit(sessions)
        }

        projects = Projects.objects.filter(user=user)
        exclude_ids = request.query_params.getlist("exclude_projects")
        if exclude_ids:
            projects = projects.exclude(id__in=exclude_ids)

        projects_by_context: dict = {}
        for project in projects.prefetch_related("subprojects"):
            projects_by_context.setdefault(project.context_id, []).append(project)

        hierarchy = {"name": "All", "children": []}
        contexts = list(Context.objects.filter(user=user)) + [None]
        for ctx in contexts:
            ctx_id = ctx.id if ctx else None
            ctx_children = []
            for proj in projects_by_context.get(ctx_id, []):
                proj_time = project_times.get(proj.id, 0)
                if proj_time == 0:
                    continue
                proj_children = [
                    {
                        "name": sub.name,
                        "subproject_id": sub.id,
                        "total_time": subproject_times.get(sub.id, 0),
                    }
                    for sub in proj.subprojects.all()
                    if subproject_times.get(sub.id, 0) > 0
                ]
                ctx_children.append(
                    {
                        "name": proj.name,
                        "project_id": proj.id,
                        "total_time": proj_time,
                        "children": proj_children,
                    }
                )
            if ctx_children:
                hierarchy["children"].append(
                    {
                        "name": ctx.name if ctx else "General",
                        "children": ctx_children,
                    }
                )
        return hierarchy

    @staticmethod
    def _legacy_radar_payload(request, sessions):
        """The removed v1 projects_with_stats rows the radar chart reads."""
        from django.utils import timezone as dj_timezone

        user = request.user
        projects = Projects.objects.filter(user=user)
        exclude_ids = request.query_params.getlist("exclude_projects")
        if exclude_ids:
            projects = projects.exclude(id__in=exclude_ids)
        projects = (
            annotate_project_totals(projects)
            .annotate(aggregated_subproject_count=Count("subprojects", distinct=True))
            .order_by("name")
        )

        project_stats = {
            row["project_id"]: {
                "total_time": float(row["total"] or 0.0),
                "session_count": row["session_count"],
            }
            for row in sessions.values("project_id").annotate(
                total=Sum(rounded_session_minutes()), session_count=Count("pk")
            )
        }

        now = dj_timezone.now()
        payload = []
        for p in projects:
            stats = project_stats.get(p.id, {"total_time": 0, "session_count": 0})
            latest_activity = p.derived_last_updated
            days_since_update = (
                (now - latest_activity).days if latest_activity else 999
            )
            payload.append(
                {
                    "name": p.name,
                    "total_time": stats["total_time"],
                    "session_count": stats["session_count"],
                    "subproject_count": p.aggregated_subproject_count,
                    "days_since_update": days_since_update,
                    "status": p.status,
                }
            )
        return payload
