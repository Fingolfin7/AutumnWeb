from datetime import datetime, time, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Count, Prefetch, Q
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
    ContextListResponseSerializer,
    ContextResourceSerializer,
    ContextWriteRequestSerializer,
    CommitmentHistoryWarningSerializer,
    MeSerializer,
    ProjectCreateRequestSerializer,
    ProjectDetailResourceSerializer,
    ProjectListQuerySerializer,
    ProjectListResponseSerializer,
    ProjectMergeRequestSerializer,
    ProjectPatchRequestSerializer,
    ProjectResourceSerializer,
    SessionListQuerySerializer,
    SessionListResponseSerializer,
    SessionPatchRequestSerializer,
    SessionResourceSerializer,
    SessionTrackRequestSerializer,
    SubprojectCreateRequestSerializer,
    SubprojectListResponseSerializer,
    SubprojectMergeRequestSerializer,
    SubprojectPatchRequestSerializer,
    SubprojectResourceSerializer,
    TagListResponseSerializer,
    TagResourceSerializer,
    TagWriteRequestSerializer,
    TimerListResponseSerializer,
    TimerRestartRequestSerializer,
    TimerStartRequestSerializer,
    TimerStopRequestSerializer,
)
from core.commitments import mutation_affects_ledger
from core.models import Commitment, Context, Projects, Sessions, SubProjects, Tag
from core.services import (
    DestructiveMutationService,
    DestructiveOperationError,
    SessionMutationService,
    UNSET,
)
from core.totals import annotate_project_totals, annotate_subproject_totals
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


def _commitment_history_unaffected(user, instants):
    commitments = list(Commitment.objects.filter(user=user, active=True))
    touched = [instant for instant in instants if instant is not None]
    return bool(
        commitments
        and touched
        and all(
            not mutation_affects_ledger(commitment, instant)
            for commitment in commitments
            for instant in touched
        )
    )


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


def _subproject_queryset(user):
    return annotate_subproject_totals(
        SubProjects.objects.filter(user=user).annotate(
            completed_session_count=Count(
                "sessions",
                filter=Q(sessions__end_time__isnull=False),
                distinct=True,
            )
        )
    )


def _project_queryset(user, *, include_subprojects=False):
    queryset = annotate_project_totals(
        Projects.objects.filter(user=user)
        .select_related("context")
        .annotate(
            completed_session_count=Count(
                "sessions",
                filter=Q(sessions__end_time__isnull=False),
                distinct=True,
            )
        )
    ).prefetch_related(
        Prefetch(
            "tags",
            queryset=Tag.objects.order_by("name", "id"),
            to_attr="prefetched_tags",
        )
    )
    if include_subprojects:
        queryset = queryset.prefetch_related(
            Prefetch(
                "subprojects",
                queryset=_subproject_queryset(user).order_by("name", "id"),
                to_attr="prefetched_subprojects",
            )
        )
    return queryset


def _get_project(user, project_id, *, include_subprojects=False):
    try:
        return _project_queryset(
            user, include_subprojects=include_subprojects
        ).get(pk=project_id)
    except Projects.DoesNotExist as exc:
        raise NotFound(f"Project {project_id} not found.") from exc


def _get_subproject(user, subproject_id):
    try:
        return _subproject_queryset(user).get(pk=subproject_id)
    except SubProjects.DoesNotExist as exc:
        raise NotFound(f"Subproject {subproject_id} not found.") from exc


def _resolve_context(user, context_id):
    if context_id is None:
        return None
    try:
        return Context.objects.get(user=user, pk=context_id)
    except Context.DoesNotExist as exc:
        raise ValidationError(
            {"context_id": ["Unknown context or context does not belong to this user."]}
        ) from exc


def _resolve_tags(user, tag_ids):
    requested_ids = set(tag_ids)
    tags = list(Tag.objects.filter(user=user, id__in=requested_ids))
    resolved_ids = {tag.id for tag in tags}
    if resolved_ids != requested_ids:
        raise ValidationError(
            {"tag_ids": ["One or more tags do not belong to this user."]}
        )
    return tags


def _parse_owned_filter_ids(raw_value, *, field_name, model, user):
    if raw_value in (None, ""):
        return None
    try:
        parts = raw_value.split(",")
        if any(not part.strip() for part in parts):
            raise ValueError
        values = frozenset(int(part.strip()) for part in parts)
        if any(value <= 0 for value in values):
            raise ValueError
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValidationError(
            {field_name: ["Enter comma-separated positive integer IDs."]}
        ) from exc
    owned_ids = frozenset(
        model.objects.filter(user=user, id__in=values).values_list("id", flat=True)
    )
    if owned_ids != values:
        raise ValidationError(
            {field_name: ["One or more IDs do not belong to this user."]}
        )
    return values


def _conflict(exc):
    return Response(
        _envelope("conflict", str(exc)),
        status=status.HTTP_409_CONFLICT,
    )


def _as_start_datetime(value):
    return timezone.make_aware(
        datetime.combine(value, time.min), timezone.get_current_timezone()
    )


def _delete_target_or_none(model, user, object_id, label):
    target = model.objects.filter(user=user, pk=object_id).first()
    if target is not None:
        return target
    if model.objects.filter(pk=object_id).exists():
        raise NotFound(f"{label} {object_id} not found.")
    return None


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
                "capabilities": [
                    "timers",
                    "sessions",
                    "projects",
                    "subprojects",
                    "contexts",
                    "tags",
                    "reports",
                    "commitments",
                ],
                "user": {
                    "id": request.user.id,
                    "username": request.user.username,
                    "email": request.user.email,
                    "timezone": profile_timezone,
                },
            }
        )


def _named_count_payload(target):
    payload = {
        "id": target.id,
        "name": target.name,
        "project_count": target.project_count,
    }
    if isinstance(target, Context):
        payload["description"] = target.description
    else:
        payload["color"] = target.color
    return payload


def _apply_named_write(target, validated, *, extra_field):
    """Set name and the model-specific extra field from validated data."""
    update_fields = []
    if "name" in validated:
        target.name = validated["name"]
        update_fields.append("name")
    if extra_field in validated:
        setattr(target, extra_field, validated[extra_field])
        update_fields.append(extra_field)
    target.save(update_fields=update_fields)


def _named_count_queryset(model, user):
    return (
        model.objects.filter(user=user)
        .annotate(
            project_count=Count(
                "projects",
                filter=Q(projects__user=user),
            )
        )
        .order_by("name", "id")
    )


def _get_named_count_target(model, user, object_id, label):
    try:
        return _named_count_queryset(model, user).get(pk=object_id)
    except model.DoesNotExist as exc:
        raise NotFound(f"{label} {object_id} not found.") from exc


class ContextsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="contexts_list",
        responses=ContextListResponseSerializer,
    )
    def get(self, request):
        contexts = list(_named_count_queryset(Context, request.user))
        return Response(
            {
                "count": len(contexts),
                "contexts": ContextResourceSerializer(contexts, many=True).data,
            }
        )

    @extend_schema(
        operation_id="contexts_create",
        request=ContextWriteRequestSerializer,
        responses={201: ContextResourceSerializer},
    )
    def post(self, request):
        serializer = ContextWriteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data.get("name")
        if not name:
            raise ValidationError({"name": ["This field is required."]})
        if Context.objects.filter(user=request.user, name__iexact=name).exists():
            return _conflict(
                DestructiveOperationError(
                    "You already have a context with this name."
                )
            )
        context = Context.objects.create(
            user=request.user,
            name=name,
            description=serializer.validated_data.get("description"),
        )
        return Response(
            {
                "id": context.id,
                "name": context.name,
                "description": context.description,
                "project_count": 0,
            },
            status=status.HTTP_201_CREATED,
        )


class ContextDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="contexts_partial_update",
        request=ContextWriteRequestSerializer,
        responses={200: ContextResourceSerializer},
    )
    def patch(self, request, context_id):
        context = _get_named_count_target(
            Context, request.user, context_id, "Context"
        )
        serializer = ContextWriteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data.get("name")
        if name and (
            Context.objects.filter(user=request.user, name__iexact=name)
            .exclude(pk=context.pk)
            .exists()
        ):
            return _conflict(
                DestructiveOperationError(
                    "You already have a context with this name."
                )
            )
        _apply_named_write(
            context, serializer.validated_data, extra_field="description"
        )
        return Response(_named_count_payload(context))

    @extend_schema(
        operation_id="contexts_destroy",
        request=None,
        responses={204: OpenApiResponse(description="Context deleted.")},
    )
    def delete(self, request, context_id):
        context = _delete_target_or_none(
            Context, request.user, context_id, "Context"
        )
        if context is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        try:
            DestructiveMutationService.delete_context(
                user=request.user, context_name=context.name
            )
        except DestructiveOperationError as exc:
            return _conflict(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TagsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="tags_list",
        responses=TagListResponseSerializer,
    )
    def get(self, request):
        tags = list(_named_count_queryset(Tag, request.user))
        return Response(
            {
                "count": len(tags),
                "tags": TagResourceSerializer(tags, many=True).data,
            }
        )

    @extend_schema(
        operation_id="tags_create",
        request=TagWriteRequestSerializer,
        responses={201: TagResourceSerializer},
    )
    def post(self, request):
        serializer = TagWriteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data.get("name")
        if not name:
            raise ValidationError({"name": ["This field is required."]})
        if Tag.objects.filter(user=request.user, name__iexact=name).exists():
            return _conflict(
                DestructiveOperationError("You already have a tag with this name.")
            )
        tag = Tag.objects.create(
            user=request.user,
            name=name,
            color=serializer.validated_data.get("color"),
        )
        return Response(
            {
                "id": tag.id,
                "name": tag.name,
                "color": tag.color,
                "project_count": 0,
            },
            status=status.HTTP_201_CREATED,
        )


class TagDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="tags_partial_update",
        request=TagWriteRequestSerializer,
        responses={200: TagResourceSerializer},
    )
    def patch(self, request, tag_id):
        tag = _get_named_count_target(Tag, request.user, tag_id, "Tag")
        serializer = TagWriteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data.get("name")
        if name and (
            Tag.objects.filter(user=request.user, name__iexact=name)
            .exclude(pk=tag.pk)
            .exists()
        ):
            return _conflict(
                DestructiveOperationError("You already have a tag with this name.")
            )
        _apply_named_write(tag, serializer.validated_data, extra_field="color")
        return Response(_named_count_payload(tag))

    @extend_schema(
        operation_id="tags_destroy",
        request=None,
        responses={204: OpenApiResponse(description="Tag deleted.")},
    )
    def delete(self, request, tag_id):
        tag = _delete_target_or_none(Tag, request.user, tag_id, "Tag")
        if tag is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        try:
            DestructiveMutationService.delete_tag(
                user=request.user, tag_name=tag.name
            )
        except DestructiveOperationError as exc:
            return _conflict(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


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
        history_unaffected = _commitment_history_unaffected(
            request.user,
            (session.start_time, session.end_time, start_time, end_time),
        )
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
        payload = _serialize(session)
        if history_unaffected:
            payload["commitment_history_unaffected"] = True
        return Response(payload, status=status.HTTP_200_OK)

    @extend_schema(
        request=None,
        parameters=[IF_MATCH_PARAMETER],
        responses={
            200: CommitmentHistoryWarningSerializer,
            204: OpenApiResponse(description="Session deleted."),
        },
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
        history_unaffected = _commitment_history_unaffected(
            request.user, (session.start_time, session.end_time)
        )
        SessionMutationService.delete_session(session.pk, user=request.user)
        if history_unaffected:
            return Response({"commitment_history_unaffected": True})
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="projects_list",
        parameters=[ProjectListQuerySerializer],
        responses=ProjectListResponseSerializer,
    )
    def get(self, request):
        serializer = ProjectListQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        context_ids = _parse_owned_filter_ids(
            request.query_params.get("context_ids"),
            field_name="context_ids",
            model=Context,
            user=request.user,
        )
        tag_ids = _parse_owned_filter_ids(
            request.query_params.get("tag_ids"),
            field_name="tag_ids",
            model=Tag,
            user=request.user,
        )
        excluded_ids = _parse_owned_filter_ids(
            request.query_params.get("exclude_project_ids"),
            field_name="exclude_project_ids",
            model=Projects,
            user=request.user,
        )

        queryset = _project_queryset(request.user)
        if "status" in data:
            queryset = queryset.filter(status=data["status"])
        if data.get("search"):
            queryset = queryset.filter(name__icontains=data["search"])
        if context_ids is not None:
            queryset = queryset.filter(context_id__in=context_ids)
        if tag_ids is not None:
            queryset = queryset.filter(tags__id__in=tag_ids).distinct()
        if excluded_ids is not None:
            queryset = queryset.exclude(pk__in=excluded_ids)
        ordering = data["ordering"]
        queryset = (
            queryset.order_by(ordering, "id")
            if ordering == "name"
            else queryset.order_by("id")
        )

        total = queryset.count()
        offset = data["offset"]
        projects = list(queryset[offset : offset + data["limit"]])
        return Response(
            {
                "count": len(projects),
                "total": total,
                "projects": ProjectResourceSerializer(projects, many=True).data,
            }
        )

    @extend_schema(
        operation_id="projects_create",
        request=ProjectCreateRequestSerializer,
        responses={201: ProjectResourceSerializer},
    )
    def post(self, request):
        serializer = ProjectCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if Projects.objects.filter(user=request.user, name=data["name"]).exists():
            return _conflict(DestructiveOperationError("Project name already exists"))
        context = (
            _resolve_context(request.user, data["context_id"])
            if "context_id" in data
            else None
        )
        tags = (
            _resolve_tags(request.user, data["tag_ids"])
            if "tag_ids" in data
            else []
        )
        with transaction.atomic():
            project = Projects.objects.create(
                user=request.user,
                name=data["name"],
                description=data.get("description", ""),
                status=data["status"],
                context=context,
            )
            if "context_id" in data and context is None:
                Projects.objects.filter(pk=project.pk).update(context=None)
            if "tag_ids" in data:
                project.tags.set(tags)
        project = _get_project(request.user, project.pk)
        return Response(
            ProjectResourceSerializer(project).data,
            status=status.HTTP_201_CREATED,
        )


class ProjectDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="projects_retrieve",
        responses=ProjectDetailResourceSerializer,
    )
    def get(self, request, project_id):
        project = _get_project(
            request.user, project_id, include_subprojects=True
        )
        return Response(ProjectDetailResourceSerializer(project).data)

    @extend_schema(
        operation_id="projects_partial_update",
        request=ProjectPatchRequestSerializer,
        responses={200: ProjectResourceSerializer},
    )
    def patch(self, request, project_id):
        project = _get_project(request.user, project_id)
        serializer = ProjectPatchRequestSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        context = (
            _resolve_context(request.user, data["context_id"])
            if "context_id" in data
            else None
        )
        tags = (
            _resolve_tags(request.user, data["tag_ids"])
            if "tag_ids" in data
            else None
        )
        try:
            with transaction.atomic():
                if "name" in data:
                    project = DestructiveMutationService.rename_project(
                        user=request.user,
                        project_name=project.name,
                        new_name=data["name"],
                    )
                updates = {}
                if "description" in data:
                    updates["description"] = data["description"]
                if "status" in data:
                    updates["status"] = data["status"]
                if "context_id" in data:
                    updates["context_id"] = context.pk if context else None
                if "start_date" in data:
                    updates["start_date"] = _as_start_datetime(data["start_date"])
                if updates:
                    Projects.objects.filter(pk=project.pk).update(**updates)
                if tags is not None:
                    project.tags.set(tags)
        except DestructiveOperationError as exc:
            return _conflict(exc)
        project = _get_project(request.user, project.pk)
        return Response(ProjectResourceSerializer(project).data)

    @extend_schema(
        operation_id="projects_destroy",
        request=None,
        responses={204: OpenApiResponse(description="Project deleted.")},
    )
    def delete(self, request, project_id):
        project = _delete_target_or_none(
            Projects, request.user, project_id, "Project"
        )
        if project is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        try:
            DestructiveMutationService.delete_project(
                user=request.user, project_name=project.name
            )
        except DestructiveOperationError as exc:
            return _conflict(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectMergeView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="projects_merge",
        request=ProjectMergeRequestSerializer,
        responses={201: ProjectResourceSerializer},
    )
    def post(self, request):
        serializer = ProjectMergeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        sources = [
            _resolve_project(request.user, project_id)
            for project_id in data["source_ids"]
        ]
        try:
            merged, _ = DestructiveMutationService.merge_projects(
                user=request.user,
                project1_name=sources[0].name,
                project2_name=sources[1].name,
                new_project_name=data["new_name"],
            )
        except DestructiveOperationError as exc:
            return _conflict(exc)
        merged = _get_project(request.user, merged.pk)
        return Response(
            ProjectResourceSerializer(merged).data,
            status=status.HTTP_201_CREATED,
        )


class ProjectSubprojectsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="project_subprojects_list",
        responses=SubprojectListResponseSerializer,
    )
    def get(self, request, project_id):
        project = _resolve_project(request.user, project_id)
        subprojects = list(
            _subproject_queryset(request.user)
            .filter(parent_project=project)
            .order_by("name", "id")
        )
        return Response(
            {
                "count": len(subprojects),
                "subprojects": SubprojectResourceSerializer(
                    subprojects, many=True
                ).data,
            }
        )

    @extend_schema(
        operation_id="project_subprojects_create",
        request=SubprojectCreateRequestSerializer,
        responses={201: SubprojectResourceSerializer},
    )
    def post(self, request, project_id):
        project = _resolve_project(request.user, project_id)
        serializer = SubprojectCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if SubProjects.objects.filter(
            user=request.user, parent_project=project, name=data["name"]
        ).exists():
            return _conflict(
                DestructiveOperationError("Subproject name already exists")
            )
        subproject = SubProjects.objects.create(
            user=request.user,
            parent_project=project,
            name=data["name"],
            description=data.get("description", ""),
        )
        subproject = _get_subproject(request.user, subproject.pk)
        return Response(
            SubprojectResourceSerializer(subproject).data,
            status=status.HTTP_201_CREATED,
        )


class SubprojectDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="subprojects_retrieve",
        responses=SubprojectResourceSerializer,
    )
    def get(self, request, subproject_id):
        return Response(
            SubprojectResourceSerializer(
                _get_subproject(request.user, subproject_id)
            ).data
        )

    @extend_schema(
        operation_id="subprojects_partial_update",
        request=SubprojectPatchRequestSerializer,
        responses={200: SubprojectResourceSerializer},
    )
    def patch(self, request, subproject_id):
        subproject = _get_subproject(request.user, subproject_id)
        serializer = SubprojectPatchRequestSerializer(
            data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            with transaction.atomic():
                if "name" in data:
                    subproject = DestructiveMutationService.rename_subproject(
                        user=request.user,
                        project_name=subproject.parent_project.name,
                        subproject_name=subproject.name,
                        new_name=data["name"],
                    )
                if "description" in data:
                    SubProjects.objects.filter(pk=subproject.pk).update(
                        description=data["description"]
                    )
        except DestructiveOperationError as exc:
            return _conflict(exc)
        return Response(
            SubprojectResourceSerializer(
                _get_subproject(request.user, subproject.pk)
            ).data
        )

    @extend_schema(
        operation_id="subprojects_destroy",
        request=None,
        responses={204: OpenApiResponse(description="Subproject deleted.")},
    )
    def delete(self, request, subproject_id):
        subproject = _delete_target_or_none(
            SubProjects, request.user, subproject_id, "Subproject"
        )
        if subproject is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        try:
            DestructiveMutationService.delete_subproject(
                user=request.user,
                project_name=subproject.parent_project.name,
                subproject_name=subproject.name,
            )
        except DestructiveOperationError as exc:
            return _conflict(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SubprojectMergeView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="subprojects_merge",
        request=SubprojectMergeRequestSerializer,
        responses={201: SubprojectResourceSerializer},
    )
    def post(self, request):
        serializer = SubprojectMergeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        project = _resolve_project(request.user, data["project_id"])
        sources = []
        for subproject_id in data["source_ids"]:
            try:
                sources.append(
                    SubProjects.objects.get(
                        user=request.user,
                        parent_project=project,
                        pk=subproject_id,
                    )
                )
            except SubProjects.DoesNotExist as exc:
                raise NotFound(
                    f"Subproject {subproject_id} not found."
                ) from exc
        try:
            merged = DestructiveMutationService.merge_subprojects(
                user=request.user,
                project_id=project.pk,
                name1=sources[0].name,
                name2=sources[1].name,
                new_name=data["new_name"],
            )
        except DestructiveOperationError as exc:
            return _conflict(exc)
        return Response(
            SubprojectResourceSerializer(
                _get_subproject(request.user, merged.pk)
            ).data,
            status=status.HTTP_201_CREATED,
        )
