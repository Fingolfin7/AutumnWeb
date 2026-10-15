from datetime import datetime, time, timedelta, timezone as datetime_timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Count, FloatField, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api_v2.exceptions import V2APIView, _envelope, related_outcome
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
    ProjectRelatedSummaryQuerySerializer,
    ProjectMergeRequestSerializer,
    ProjectPatchRequestSerializer,
    ProjectResourceSerializer,
    PreferencesRequestSerializer,
    PreferencesResponseSerializer,
    ResourceIncludeQuerySerializer,
    RelatedSummarySerializer,
    SessionListQuerySerializer,
    SessionListResponseSerializer,
    SessionRelatedSummaryQuerySerializer,
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
    TimerNoteRequestSerializer,
    TimerRestartRequestSerializer,
    TimerStartRequestSerializer,
    TimerStopRequestSerializer,
)
from core.commitments import mutation_affects_ledger
from core.models import Commitment, Context, Projects, Sessions, SubProjects, Tag
from core.search import DIRECT, RELATED, SESSION_ORDER, with_extra
from core.services.embedding_sync import request_sync_on_commit
from core.services.semantic_search import (
    SIMILARITY_CEILING,
    SIMILARITY_FLOOR,
    SIMILARITY_MARKS,
    SIMILARITY_STEP,
    loosen_similarity,
    min_similarity,
    related_project_ids,
)
from core.services import (
    DestructiveMutationService,
    DestructiveOperationError,
    SessionMutationService,
    StaleVersionError,
    UNSET,
    even_split_bps,
)
from core.session_canonical import (
    canonical_existing_session,
    canonical_instant,
    canonical_session_content,
)
from core.totals import (
    annotate_project_totals,
    annotate_subproject_totals,
    rounded_session_minutes,
)
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
    # subproject_links prefetch keeps list serialization at O(1) queries
    # (the serializer walks each session's allocations).
    return (
        Sessions.objects.filter(user=user)
        .select_related("project")
        .prefetch_related("subproject_links__subproject")
    )


def _get_session(user, session_id):
    queryset = _session_queryset(user)
    try:
        return queryset.get(pk=session_id)
    except Sessions.DoesNotExist as exc:
        raise NotFound(f"Session {session_id} not found.") from exc


def _serialize(
    session, *, include_note=True, include_note_html=False, include_reminders=False
):
    return SessionResourceSerializer(
        session,
        context={
            "include_note": include_note,
            "include_note_html": include_note_html,
            "include_reminders": include_reminders,
        },
    ).data


def _context_request(request):
    """Return a request-like context selector from the explicit ?context= parameter."""
    raw_value = request.query_params.get("context")
    # API clients (CLI, MCP, the web app) state their scope explicitly. The
    # browser session's header switch must not silently narrow what
    # `autumn status` or an MCP `status` call sees, so no parameter means all.
    if raw_value is None:
        return SimpleNamespace(user=request.user, session={"active_context_id": "all"})
    value = str(raw_value).strip()
    if not value or value.lower() == "all":
        return SimpleNamespace(user=request.user, session={"active_context_id": "all"})
    try:
        context_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            {"context": ["Enter a context ID or 'all'."]}
        ) from exc
    if not Context.objects.filter(user=request.user, pk=context_id).exists():
        raise ValidationError(
            {"context": ["Context does not belong to this user."]}
        )
    return SimpleNamespace(
        user=request.user,
        session={"active_context_id": str(context_id)},
    )


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
    return canonical_instant(value)


def _canonical_existing(session):
    return canonical_existing_session(session)


def _canonical_track_payload(project, allocations, data):
    return canonical_session_content(
        project.name,
        data["start"],
        data["end"],
        data.get("note") or "",
        [(subproject.name, bp) for subproject, bp in allocations],
    )


def _explicit_allocation_pairs(user, project, items):
    ids = [item["subproject_id"] for item in items]
    if len(ids) != len(set(ids)):
        raise ValidationError(
            {"subproject_allocations": ["Subprojects must be unique."]}
        )
    subprojects = _resolve_subprojects(user, project, ids)
    by_id = {subproject.id: subproject for subproject in subprojects}
    allocations = [
        (by_id[item["subproject_id"]], item["allocation_bp"])
        for item in items
    ]
    if sum(bp for _, bp in allocations) > 10000:
        raise ValidationError(
            {
                "subproject_allocations": [
                    "Partitioned allocations must not exceed 10000 basis points."
                ]
            }
        )
    return allocations


def _even_allocation_pairs(subprojects):
    split = even_split_bps(subproject.id for subproject in subprojects)
    return [(subproject, split[subproject.id]) for subproject in subprojects]


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


def _related_summary(user, outcome, requested_similarity):
    default = round(min_similarity(user), 2)
    similarity = default if requested_similarity is None else requested_similarity
    available = outcome.included
    scores = outcome.scores if available else []
    best = outcome.best if available else None
    return {
        "available": available,
        "similarity": similarity,
        "default": default,
        "floor": SIMILARITY_FLOOR,
        "ceiling": SIMILARITY_CEILING,
        "step": SIMILARITY_STEP,
        "marks": [
            {"label": label, "value": value}
            for label, value in SIMILARITY_MARKS
        ],
        "counts": outcome.counts() if available else [],
        "count": sum(1 for score in scores if score >= similarity),
        "best": best,
        "loosen_to": loosen_similarity(best, similarity) if available else None,
    }



__all__ = [name for name in globals() if not name.startswith("__")]
