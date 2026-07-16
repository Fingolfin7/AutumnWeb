from datetime import timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api_v2.exceptions import V2APIView, _envelope
from core.api_v2.filters import SessionFilterSpec
from core.api_v2.serializers import (
    MeSerializer,
    SessionListQuerySerializer,
    SessionListResponseSerializer,
    SessionPatchRequestSerializer,
    SessionResourceSerializer,
    SessionTrackRequestSerializer,
    TimerListResponseSerializer,
    TimerRestartRequestSerializer,
    TimerStartRequestSerializer,
    TimerStopRequestSerializer,
)
from core.models import Projects, Sessions, SubProjects
from core.services import SessionMutationService, UNSET
from core.utils import stop_expired_timers


MAX_FUTURE = timedelta(minutes=5)
IF_MATCH_PARAMETER = OpenApiParameter(
    name="If-Match",
    type=OpenApiTypes.INT,
    location=OpenApiParameter.HEADER,
    required=False,
    description="Optional current integer session version.",
)


def _session_queryset(user):
    return Sessions.objects.filter(user=user).select_related("project")


def _get_session(user, session_id):
    queryset = _session_queryset(user)
    try:
        return queryset.get(pk=session_id)
    except Sessions.DoesNotExist as exc:
        raise NotFound(f"Session {session_id} not found.") from exc


def _serialize(session, *, include_note=True):
    return SessionResourceSerializer(
        session, context={"include_note": include_note}
    ).data


def _parse_if_match(request):
    raw_value = request.headers.get("If-Match")
    if raw_value is None:
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"If-Match": ["Enter an integer version."]}) from exc


def _version_conflict(session):
    return Response(
        _envelope(
            "version_conflict",
            "The session has changed since the supplied version.",
            {"current": _serialize(session)},
        ),
        status=status.HTTP_409_CONFLICT,
    )


def _check_version(request, session):
    expected = _parse_if_match(request)
    if expected is not None and expected != session.version:
        return _version_conflict(session)
    return None


def _validate_not_future(value, field_name):
    if value > timezone.now().astimezone(datetime_timezone.utc) + MAX_FUTURE:
        raise ValidationError({field_name: ["The timestamp is in the future."]})


def _resolve_project(user, project_id):
    try:
        return Projects.objects.get(user=user, pk=project_id)
    except Projects.DoesNotExist as exc:
        raise NotFound(f"Project {project_id} not found.") from exc


def _resolve_subprojects(user, project, subproject_ids):
    requested_ids = set(subproject_ids)
    subprojects = list(
        SubProjects.objects.filter(
            user=user,
            parent_project=project,
            id__in=requested_ids,
        ).order_by("id")
    )
    resolved_ids = {subproject.id for subproject in subprojects}
    if resolved_ids != requested_ids:
        invalid_ids = sorted(requested_ids - resolved_ids)
        raise ValidationError(
            {
                "subproject_ids": [
                    "Unknown subprojects or subprojects outside the selected "
                    f"project: {', '.join(map(str, invalid_ids))}."
                ]
            }
        )
    return subprojects


def _canonical_instant(value):
    if value is None:
        return None
    if timezone.is_naive(value):
        value = value.replace(tzinfo=datetime_timezone.utc)
    return value.astimezone(datetime_timezone.utc).replace(microsecond=0)


def _canonical_existing(session):
    allocations = sorted(
        {
            (link.subproject.name, link.allocation_bp)
            for link in session.subproject_links.select_related("subproject")
        }
    )
    return (
        session.project.name,
        _canonical_instant(session.start_time),
        _canonical_instant(session.end_time),
        session.note or "",
        session.allocation_mode,
        tuple(allocations),
    )


def _canonical_track_payload(project, subprojects, data):
    allocations = sorted({(subproject.name, 10000) for subproject in subprojects})
    return (
        project.name,
        _canonical_instant(data["start"]),
        _canonical_instant(data["end"]),
        data.get("note") or "",
        "legacy_full",
        tuple(allocations),
    )


class MeView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        try:
            profile_timezone = request.user.profile.timezone
            ZoneInfo(profile_timezone)
        except (AttributeError, KeyError, ObjectDoesNotExist, ZoneInfoNotFoundError):
            profile_timezone = settings.TIME_ZONE
        return Response(
            {
                "api_version": 2,
                "capabilities": ["timers", "sessions"],
                "user": {
                    "id": request.user.id,
                    "username": request.user.username,
                    "timezone": profile_timezone,
                },
            }
        )


class TimersView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=TimerListResponseSerializer)
    def get(self, request):
        stop_expired_timers(request.user)
        timers = list(
            _session_queryset(request.user)
            .filter(end_time__isnull=True)
            .order_by("-start_time", "-id")
        )
        return Response(
            {
                "count": len(timers),
                "timers": [_serialize(timer) for timer in timers],
            }
        )

    @extend_schema(
        request=TimerStartRequestSerializer,
        responses={
            200: SessionResourceSerializer,
            201: SessionResourceSerializer,
        },
    )
    def post(self, request):
        if "uuid" in request.data:
            uuid_field = serializers.UUIDField()
            try:
                client_uuid = uuid_field.run_validation(request.data.get("uuid"))
            except serializers.ValidationError as exc:
                raise ValidationError({"uuid": exc.detail}) from exc
            existing = _session_queryset(request.user).filter(uuid=client_uuid).first()
            if existing is not None:
                return Response(_serialize(existing), status=status.HTTP_200_OK)

        serializer = TimerStartRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        project = _resolve_project(request.user, data["project_id"])
        subprojects = _resolve_subprojects(
            request.user, project, data.get("subproject_ids", [])
        )
        start_time = data.get(
            "start", timezone.now().astimezone(datetime_timezone.utc).replace(microsecond=0)
        )
        _validate_not_future(start_time, "start")
        fields = {
            "user": request.user,
            "project": project,
            "start_time": start_time,
            "auto_stop_at": None,
            "is_active": True,
            "note": data.get("note"),
            "subprojects": subprojects,
        }
        if "uuid" in data:
            fields["uuid"] = data["uuid"]
        if "stop_after_minutes" in data:
            fields["auto_stop_at"] = start_time + timedelta(
                minutes=data["stop_after_minutes"]
            )
        session = SessionMutationService.create_session(**fields)
        return Response(_serialize(session), status=status.HTTP_201_CREATED)


class TimerStopView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=TimerStopRequestSerializer,
        parameters=[IF_MATCH_PARAMETER],
        responses={200: SessionResourceSerializer},
    )
    def post(self, request, session_id):
        session = _get_session(request.user, session_id)
        if session.end_time is not None:
            return Response(_serialize(session), status=status.HTTP_200_OK)
        conflict = _check_version(request, session)
        if conflict is not None:
            return conflict

        serializer = TimerStopRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        end_time = data.get(
            "end", timezone.now().astimezone(datetime_timezone.utc).replace(microsecond=0)
        )
        _validate_not_future(end_time, "end")
        if end_time < session.start_time:
            raise ValidationError(
                {"end": ["End must be on or after the session start."]}
            )
        session = SessionMutationService.mutate_session(
            session.pk,
            user=request.user,
            end_time=end_time,
            is_active=False,
            auto_stop_at=None,
            note=data["note"] if "note" in data else UNSET,
        )
        return Response(_serialize(session), status=status.HTTP_200_OK)


class TimerRestartView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=TimerRestartRequestSerializer,
        parameters=[IF_MATCH_PARAMETER],
        responses={200: SessionResourceSerializer},
    )
    def post(self, request, session_id):
        session = _get_session(request.user, session_id)
        conflict = _check_version(request, session)
        if conflict is not None:
            return conflict

        serializer = TimerRestartRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        restart_time = serializer.validated_data.get(
            "start", timezone.now().astimezone(datetime_timezone.utc).replace(microsecond=0)
        )
        _validate_not_future(restart_time, "start")
        auto_stop_duration = None
        if (
            session.auto_stop_at is not None
            and session.auto_stop_at > session.start_time
        ):
            auto_stop_duration = session.auto_stop_at - session.start_time
        session = SessionMutationService.mutate_session(
            session.pk,
            user=request.user,
            start_time=restart_time,
            end_time=None,
            is_active=True,
            auto_stop_at=(
                restart_time + auto_stop_duration if auto_stop_duration else None
            ),
        )
        return Response(_serialize(session), status=status.HTTP_200_OK)


class TimerDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        parameters=[IF_MATCH_PARAMETER],
        responses={204: OpenApiResponse(description="Timer deleted.")},
    )
    def delete(self, request, session_id):
        session = _session_queryset(request.user).filter(pk=session_id).first()
        if session is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        if session.end_time is not None:
            return Response(
                _envelope(
                    "conflict",
                    f"Session {session_id} is completed; delete it via "
                    f"/api/v2/sessions/{session_id}.",
                ),
                status=status.HTTP_409_CONFLICT,
            )
        conflict = _check_version(request, session)
        if conflict is not None:
            return conflict
        SessionMutationService.delete_session(session.pk, user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SessionsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sessions_list",
        parameters=[SessionListQuerySerializer],
        responses=SessionListResponseSerializer,
    )
    def get(self, request):
        pagination = SessionListQuerySerializer(
            data={
                key: request.query_params[key]
                for key in ("limit", "offset", "include")
                if key in request.query_params
            }
        )
        pagination.is_valid(raise_exception=True)
        limit = pagination.validated_data["limit"]
        offset = pagination.validated_data["offset"]
        include_note = pagination.validated_data.get("include") == "note"

        spec = SessionFilterSpec.from_query_params(request.query_params, request.user)
        queryset = spec.apply(
            _session_queryset(request.user).filter(end_time__isnull=False)
        ).order_by("-end_time", "-id")
        total = queryset.count()
        sessions = list(queryset[offset : offset + limit])
        return Response(
            {
                "count": len(sessions),
                "total": total,
                "sessions": [
                    _serialize(session, include_note=include_note)
                    for session in sessions
                ],
            }
        )

    @extend_schema(
        request=SessionTrackRequestSerializer,
        responses={
            200: SessionResourceSerializer,
            201: SessionResourceSerializer,
        },
    )
    def post(self, request):
        serializer = SessionTrackRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        project = _resolve_project(request.user, data["project_id"])
        subprojects = _resolve_subprojects(
            request.user, project, data.get("subproject_ids", [])
        )
        if data["end"] < data["start"]:
            raise ValidationError({"end": ["End must be on or after start."]})
        _validate_not_future(data["end"], "end")

        if "uuid" in data:
            existing = _session_queryset(request.user).filter(uuid=data["uuid"]).first()
            if existing is not None:
                if _canonical_existing(existing) == _canonical_track_payload(
                    project, subprojects, data
                ):
                    return Response(_serialize(existing), status=status.HTTP_200_OK)
                return Response(
                    _envelope(
                        "uuid_conflict",
                        "The UUID is already assigned to different session content.",
                        {"current": _serialize(existing)},
                    ),
                    status=status.HTTP_409_CONFLICT,
                )

        fields = {
            "user": request.user,
            "project": project,
            "subprojects": subprojects,
            "start_time": data["start"],
            "end_time": data["end"],
            "is_active": False,
            "note": data.get("note"),
        }
        if "uuid" in data:
            fields["uuid"] = data["uuid"]
        session = SessionMutationService.create_session(**fields)
        return Response(_serialize(session), status=status.HTTP_201_CREATED)


class SessionDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="sessions_retrieve", responses=SessionResourceSerializer)
    def get(self, request, session_id):
        return Response(_serialize(_get_session(request.user, session_id)))

    @extend_schema(
        request=SessionPatchRequestSerializer,
        parameters=[IF_MATCH_PARAMETER],
        responses={200: SessionResourceSerializer},
    )
    def patch(self, request, session_id):
        session = _get_session(request.user, session_id)
        conflict = _check_version(request, session)
        if conflict is not None:
            return conflict

        serializer = SessionPatchRequestSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        project = (
            _resolve_project(request.user, data["project_id"])
            if "project_id" in data
            else session.project
        )
        subprojects = (
            _resolve_subprojects(request.user, project, data["subproject_ids"])
            if "subproject_ids" in data
            else list(session.subprojects.all())
        )
        if "project_id" in data and "subproject_ids" not in data:
            subprojects = _resolve_subprojects(
                request.user, project, [subproject.id for subproject in subprojects]
            )

        start_time = data.get("start", session.start_time)
        end_time = data.get("end", session.end_time)
        if end_time is not None and end_time < start_time:
            raise ValidationError({"end": ["End must be on or after start."]})
        if end_time is not None:
            _validate_not_future(end_time, "end")
        session = SessionMutationService.mutate_session(
            session.pk,
            user=request.user,
            project=project if "project_id" in data else UNSET,
            subprojects=subprojects if (
                "project_id" in data or "subproject_ids" in data
            ) else UNSET,
            start_time=data["start"] if "start" in data else UNSET,
            end_time=data["end"] if "end" in data else UNSET,
            is_active=False if "end" in data else UNSET,
            auto_stop_at=None if "end" in data else UNSET,
            note=data["note"] if "note" in data else UNSET,
        )
        return Response(_serialize(session), status=status.HTTP_200_OK)

    @extend_schema(
        request=None,
        parameters=[IF_MATCH_PARAMETER],
        responses={204: OpenApiResponse(description="Session deleted.")},
    )
    def delete(self, request, session_id):
        session = (
            _session_queryset(request.user)
            .filter(pk=session_id)
            .first()
        )
        if session is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        conflict = _check_version(request, session)
        if conflict is not None:
            return conflict
        SessionMutationService.delete_session(session.pk, user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
