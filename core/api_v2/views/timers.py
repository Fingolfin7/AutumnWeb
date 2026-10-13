from .base import *
import hashlib

from core.utils import filter_by_active_context
from core.models import TimerReminder
from core.api_v2.serializers import TimerReminderListSerializer


class TimersView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[ResourceIncludeQuerySerializer],
        responses=TimerListResponseSerializer,
    )
    def get(self, request):
        query = ResourceIncludeQuerySerializer(
            data={
                key: request.query_params[key]
                for key in ("include", "context")
                if key in request.query_params
            }
        )
        query.is_valid(raise_exception=True)
        include = set(query.validated_data.get("include", []))
        stop_expired_timers(request.user)
        context_request = _context_request(request)
        timers = list(
            filter_by_active_context(
                _session_queryset(request.user).filter(end_time__isnull=True),
                context_request,
            )
            .order_by("-start_time", "-id")
        )
        context_key = context_request.session.get("active_context_id", "all")
        etag_source = f"{context_key}|" + ",".join(
            f"{timer.pk}:{timer.version}" for timer in timers
        )
        etag = f'W/"{hashlib.sha256(etag_source.encode()).hexdigest()}"'
        if request.headers.get("If-None-Match") == etag:
            response = Response(status=status.HTTP_304_NOT_MODIFIED)
            response["ETag"] = etag
            return response
        response = Response(
            {
                "count": len(timers),
                "timers": [
                    _serialize(
                        timer,
                        include_note_html="note_html" in include,
                    )
                    for timer in timers
                ],
            }
        )
        response["ETag"] = etag
        return response

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
        # Parse (and validate the format of) If-Match here; the comparison
        # itself happens under the row lock inside the mutation service.
        expected_version = _parse_if_match(request)

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
        allocations = None
        if "subproject_allocations" in data:
            allocations = _explicit_allocation_pairs(
                request.user, session.project, data["subproject_allocations"]
            )
        try:
            with transaction.atomic():
                session = SessionMutationService.mutate_session(
                    session.pk,
                    user=request.user,
                    end_time=end_time,
                    is_active=False,
                    auto_stop_at=None,
                    note=data["note"] if "note" in data else UNSET,
                    expected_version=expected_version,
                )
                if allocations is not None:
                    session = SessionMutationService.set_allocations(
                        session.pk,
                        user=request.user,
                        allocations=allocations,
                    )
        except StaleVersionError as exc:
            return _version_conflict(exc.current)
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
        expected_version = _parse_if_match(request)

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
        try:
            session = SessionMutationService.mutate_session(
                session.pk,
                user=request.user,
                start_time=restart_time,
                end_time=None,
                is_active=True,
                auto_stop_at=(
                    restart_time + auto_stop_duration if auto_stop_duration else None
                ),
                expected_version=expected_version,
            )
        except StaleVersionError as exc:
            return _version_conflict(exc.current)
        return Response(_serialize(session), status=status.HTTP_200_OK)


class TimerDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=TimerNoteRequestSerializer,
        parameters=[IF_MATCH_PARAMETER],
        responses={200: SessionResourceSerializer},
    )
    def patch(self, request, session_id):
        session = _get_session(request.user, session_id)
        if session.end_time is not None:
            return Response(
                _envelope(
                    "conflict",
                    f"Session {session_id} is completed; its timer note can no longer be changed.",
                ),
                status=status.HTTP_409_CONFLICT,
            )
        serializer = TimerNoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected_version = _parse_if_match(request)
        try:
            session = SessionMutationService.mutate_session(
                session.pk,
                user=request.user,
                note=serializer.validated_data["note"] or None,
                expected_version=expected_version,
            )
        except StaleVersionError as exc:
            return _version_conflict(exc.current)
        return Response(_serialize(session), status=status.HTTP_200_OK)

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
        expected_version = _parse_if_match(request)
        try:
            SessionMutationService.delete_session(
                session.pk, user=request.user, expected_version=expected_version
            )
        except StaleVersionError as exc:
            return _version_conflict(exc.current)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TimerRemindersView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=TimerReminderListSerializer)
    def get(self, request, session_id):
        _get_session(request.user, session_id)
        reminders = list(
            TimerReminder.objects.filter(
                session_id=session_id,
                session__user=request.user,
                active=True,
            ).order_by("next_fire_at", "id")
        )
        return Response(
            {
                "count": len(reminders),
                "reminders": TimerReminderListSerializer(
                    {"count": len(reminders), "reminders": reminders}
                ).data["reminders"],
            }
        )


class TimerReminderDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={204: OpenApiResponse(description="Reminder cancelled.")},
    )
    def delete(self, request, session_id, reminder_id):
        with transaction.atomic():
            reminder = (
                TimerReminder.objects.select_for_update()
                .filter(
                    pk=reminder_id,
                    session_id=session_id,
                    session__user=request.user,
                    active=True,
                )
                .first()
            )
            if reminder is not None:
                reminder.active = False
                reminder.next_fire_at = None
                reminder.cancelled_at = timezone.now().replace(microsecond=0)
                reminder.save(
                    update_fields=["active", "next_fire_at", "cancelled_at"]
                )
        return Response(status=status.HTTP_204_NO_CONTENT)


