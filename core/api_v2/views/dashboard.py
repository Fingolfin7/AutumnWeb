from datetime import datetime

from .base import *

from core.api_v2.commitments import serialize_commitment
from core.api_v2.serializers import (
    DashboardResponseSerializer,
    TimelineQuerySerializer,
    TimelineResponseSerializer,
)
from core.services.dashboard import build_dashboard, build_dashboard_timeline
from core.templatetags.markdown_render import markdown as render_markdown
from core.utils import get_active_context


def _serialize_timeline(timeline):
    lanes = []
    for lane in timeline["lanes"]:
        blocks = []
        for block in lane["blocks"]:
            session = block["session"]
            blocks.append(
                {
                    "session_id": session.pk,
                    "is_live": block["is_live"],
                    "start": block["start_local"],
                    "end": block["end_local"],
                    "minutes": round(block["minutes"], 2),
                    "duration_label": block["duration_label"],
                    "label": block["label"],
                    "note_html": render_markdown(session.note or ""),
                    "start_pct": block["start_pct"],
                    "end_pct": block["end_pct"],
                    "width_pct": block["width_pct"],
                }
            )
        lanes.append(
            {
                "project": {
                    "id": lane["project"].pk,
                    "name": lane["project"].name,
                },
                "colour": lane["colour"],
                "total_minutes": round(lane["total_minutes"], 2),
                "live_minutes": round(lane["live_minutes"], 2),
                "total_label": lane["total_label"],
                "live_label": lane["live_label"],
                "blocks": blocks,
            }
        )
    return {
        "range_key": timeline["range_key"],
        "range_title": timeline["range_title"],
        "is_multi_day": timeline["is_multi_day"],
        "tracked_minutes": round(timeline["tracked_minutes"], 2),
        "start_date": timeline["start_day"],
        "end_date": timeline["date"],
        "window_start": datetime.fromisoformat(timeline["window_start_iso"]),
        "window_end": datetime.fromisoformat(timeline["window_end_iso"]),
        "window_start_hour": timeline["window_start_hour"],
        "window_end_hour": timeline["window_end_hour"],
        "ticks": timeline["ticks"],
        "grid_pct": timeline["grid_pct"],
        "lanes": lanes,
        "gaps": timeline["gaps"],
        "now_pct": timeline["now_pct"],
        "now_label": timeline["now_label"],
    }


def _quick_start_payload(session):
    subprojects = list(session.subprojects.all())
    suffix = ", ".join(subproject.name for subproject in subprojects)
    return {
        "project": {"id": session.project_id, "name": session.project.name},
        "subprojects": [
            {"id": subproject.pk, "name": subproject.name}
            for subproject in subprojects
        ],
        "label": f"{session.project.name} · {suffix}" if suffix else session.project.name,
    }


def _dashboard_payload(data):
    recent_days = []
    for date_label, group in data["grouped_sessions"].items():
        recent_days.append(
            {
                "date": datetime.strptime(date_label, "%m-%d-%Y").date(),
                "total_minutes": round(group["total_duration"], 2),
                "sessions": [
                    _serialize(
                        session,
                        include_note=True,
                        include_note_html=True,
                    )
                    for session in group["sessions"]
                ],
            }
        )
    return {
        "today_total": round(data["today_total"], 2),
        "week_total": round(data["week_total"], 2),
        "active_timers_count": data["active_timers_count"],
        "daily_streak": data["daily_streak"],
        "active_timers": [_serialize(timer) for timer in data["active_timers"]],
        "quick_starts": [
            _quick_start_payload(session) for session in data["quick_starts"]
        ],
        "recent_sessions": recent_days,
        "commitments": [
            {
                "commitment": serialize_commitment(
                    item["commitment"], reconcile=False
                ),
                "progress": item["progress"],
                "streak": item["streak"],
            }
            for item in data["commitments_data"]
        ],
        "timeline": _serialize_timeline(data["timeline"]),
    }


class DashboardAPIView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "context",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Context ID or 'all'; defaults to all contexts.",
            )
        ],
        responses=DashboardResponseSerializer,
    )
    def get(self, request):
        context_request = _context_request(request)
        return Response(
            _dashboard_payload(
                build_dashboard(request.user, context=context_request)
            )
        )


class TimelineAPIView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[TimelineQuerySerializer],
        responses=TimelineResponseSerializer,
    )
    def get(self, request):
        query = TimelineQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        context_request = _context_request(request)
        context, _ = get_active_context(context_request)
        timeline = build_dashboard_timeline(
            request.user,
            start_date=query.validated_data.get("start"),
            end_date=query.validated_data.get("end"),
            context=context,
        )
        return Response(_serialize_timeline(timeline))
