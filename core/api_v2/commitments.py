from datetime import datetime, timezone as datetime_timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api_v2.exceptions import V2APIView, _envelope
from core.api_v2.serializers import (
    CommitmentAdjustmentRequestSerializer,
    CommitmentAdjustmentResponseSerializer,
    CommitmentChangesRequestSerializer,
    CommitmentCreateRequestSerializer,
    CommitmentListResponseSerializer,
    CommitmentPeriodListResponseSerializer,
    CommitmentPeriodsQuerySerializer,
    CommitmentResourceSerializer,
    CommitmentRestartRequestSerializer,
)
from core.commitments import (
    _revision_accrual,
    calculate_commitment_streak,
    get_commitment_progress,
    reconcile_commitment,
)
from core.api_helpers import _iso_value
from core.models import (
    Commitment,
    CommitmentAdjustment,
    CommitmentRevision,
    Context,
    Projects,
    SubProjects,
    Tag,
)
from core.services import CommitmentEditService, CommitmentRestartRequired
from core.utils import get_period_bounds


COMMITMENT_IF_MATCH_PARAMETER = OpenApiParameter(
    name="If-Match",
    type=OpenApiTypes.INT,
    location=OpenApiParameter.HEADER,
    required=False,
    description="Optional current integer commitment version.",
)

TARGET_MODELS = {
    "project": Projects,
    "subproject": SubProjects,
    "context": Context,
    "tag": Tag,
}
FILTER_MODELS = {
    "include_project_ids": ("include_projects", Projects),
    "exclude_project_ids": ("exclude_projects", Projects),
    "include_subproject_ids": ("include_subprojects", SubProjects),
    "exclude_subproject_ids": ("exclude_subprojects", SubProjects),
    "include_context_ids": ("include_contexts", Context),
    "exclude_context_ids": ("exclude_contexts", Context),
    "include_tag_ids": ("include_tags", Tag),
    "exclude_tag_ids": ("exclude_tags", Tag),
}


def _commitment_queryset(user):
    return (
        Commitment.objects.filter(user=user)
        .select_related("project", "subproject", "context", "tag")
        .prefetch_related(
            "include_projects",
            "exclude_projects",
            "include_subprojects",
            "exclude_subprojects",
            "include_contexts",
            "exclude_contexts",
            "include_tags",
            "exclude_tags",
        )
    )


def _get_commitment(user, commitment_id):
    try:
        return _commitment_queryset(user).get(pk=commitment_id)
    except Commitment.DoesNotExist as exc:
        raise NotFound(f"Commitment {commitment_id} not found.") from exc


def _parse_if_match(request):
    raw_value = request.headers.get("If-Match")
    if raw_value is None:
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"If-Match": ["Enter an integer version."]}) from exc


def _service_message(exc):
    messages = getattr(exc, "messages", None)
    return messages[0] if messages else str(exc)


def _service_validation(exc):
    message_dict = getattr(exc, "message_dict", None)
    if message_dict:
        raise ValidationError(message_dict) from exc
    raise ValidationError({"non_field_errors": getattr(exc, "messages", [str(exc)])}) from exc


def _prepare_for_read(commitment):
    if commitment.active:
        reconcile_commitment(commitment)
        commitment.refresh_from_db()
    return commitment


def _active_revision(commitment):
    revision = (
        commitment.revisions.filter(
            generation=commitment.generation,
            status=CommitmentRevision.STATUS_ACTIVE,
        )
        .order_by("-effective_from_instant", "-pk")
        .first()
    )
    if revision is not None:
        return revision
    profile_timezone = getattr(
        getattr(commitment.user, "profile", None), "timezone", None
    ) or timezone.get_default_timezone_name()
    target = commitment.target_object
    return SimpleNamespace(
        aggregation_type=commitment.aggregation_type,
        target_id=getattr(target, "pk", None),
        target_name=getattr(target, "name", ""),
        commitment_type=commitment.commitment_type,
        cadence=commitment.period,
        target_value=commitment.target,
        banking_enabled=commitment.banking_enabled,
        max_balance=commitment.max_balance,
        min_balance=commitment.min_balance,
        start_date=commitment.start_date,
        timezone=profile_timezone,
        filters_snapshot={},
        commitment=commitment,
    )


def _unit_value(commitment_type, value):
    if commitment_type == "time":
        return round(float(value), 2)
    return int(value)


def _iso(value):
    if value is None:
        return None
    if timezone.is_naive(value):
        value = value.replace(tzinfo=datetime_timezone.utc)
    return value.astimezone(datetime_timezone.utc).isoformat()


def _filter_payload(commitment):
    return {
        api_field: list(
            getattr(commitment, model_field)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        for api_field, (model_field, _) in FILTER_MODELS.items()
    }


def _pending_payload(commitment, active_revision):
    pending = commitment.revisions.filter(
        generation=commitment.generation,
        status=CommitmentRevision.STATUS_PENDING,
    ).first()
    if pending is None:
        return None

    changes = {}
    for field in ("target_value", "banking_enabled", "max_balance", "min_balance"):
        value = getattr(pending, field)
        if value != getattr(active_revision, field):
            changes[field] = _unit_value(pending.commitment_type, value)
    for api_field, (model_field, _) in FILTER_MODELS.items():
        pending_ids = sorted(
            item.get("id") if isinstance(item, dict) else item
            for item in pending.filters_snapshot.get(model_field, [])
        )
        active_ids = sorted(
            item.get("id") if isinstance(item, dict) else item
            for item in active_revision.filters_snapshot.get(model_field, [])
        )
        if pending_ids != active_ids:
            changes[api_field] = pending_ids
    return {
        "effective_from": _iso(pending.effective_from_instant),
        "changes": changes,
    }


def _current_period_payload(commitment, revision):
    zone = ZoneInfo(revision.timezone)
    now = timezone.now()
    with timezone.override(zone):
        period_start, period_end = get_period_bounds(
            revision.cadence, now.astimezone(zone)
        )
    start_at = datetime.combine(
        revision.start_date, datetime.min.time(), tzinfo=zone
    )
    effective_start = max(period_start, start_at, commitment.ledger_start_at)
    if effective_start >= period_end:
        accrued_numerator, session_count = 0, 0
    else:
        accrued_numerator, session_count = _revision_accrual(
            revision, effective_start, period_end
        )
    accrued = (
        round(accrued_numerator / 10000, 2)
        if revision.commitment_type == "time"
        else session_count
    )
    target = _unit_value(revision.commitment_type, revision.target_value)
    # percentage/status reuse the v1 progress semantics (five temporal
    # states) so client displays carry over unchanged.
    progress = get_commitment_progress(commitment)
    return {
        "start": _iso(period_start),
        "end": _iso(period_end),
        "accrued": accrued,
        "target": target,
        "met": accrued >= target,
        "percentage": progress.get("percentage"),
        "status": progress.get("status"),
    }


def serialize_commitment(commitment, *, reconcile=True, include_streak=False):
    if reconcile:
        _prepare_for_read(commitment)
    revision = _active_revision(commitment)
    target = commitment.target_object
    return {
        "id": commitment.pk,
        "version": commitment.version,
        "active": commitment.active,
        "aggregation_type": commitment.aggregation_type,
        "target": {
            "kind": commitment.aggregation_type,
            "id": target.pk,
            "name": target.name,
        },
        "commitment_type": commitment.commitment_type,
        "period": commitment.period,
        "start_date": commitment.start_date.isoformat(),
        "timezone": revision.timezone,
        "generation": commitment.generation,
        "target_value": _unit_value(commitment.commitment_type, commitment.target),
        "banking_enabled": commitment.banking_enabled,
        "max_balance": _unit_value(commitment.commitment_type, commitment.max_balance),
        "min_balance": _unit_value(commitment.commitment_type, commitment.min_balance),
        "balance": _unit_value(commitment.commitment_type, commitment.balance),
        "filters": _filter_payload(commitment),
        "current_period": _current_period_payload(commitment, revision),
        "pending_revision": _pending_payload(commitment, revision),
        "ledger_start_at": _iso(commitment.ledger_start_at),
        **(
            {"streak": _iso_value(calculate_commitment_streak(commitment))}
            if include_streak
            else {}
        ),
    }


def _version_conflict(commitment):
    return Response(
        _envelope(
            "version_conflict",
            "The commitment has changed since the supplied version.",
            {"current": serialize_commitment(commitment)},
        ),
        status=status.HTTP_409_CONFLICT,
    )


def _check_version(request, commitment):
    expected = _parse_if_match(request)
    if expected is not None and expected != commitment.version:
        return _version_conflict(commitment)
    return None


def _resolve_owned_ids(user, ids, *, api_field, model):
    requested = set(ids)
    objects = list(model.objects.filter(user=user, pk__in=requested).order_by("pk"))
    if {obj.pk for obj in objects} != requested:
        raise ValidationError(
            {api_field: ["One or more IDs do not belong to this user."]}
        )
    return objects


def _definition_from_api(user, data, *, current_aggregation=None):
    definition = {}
    aggregation_type = data.get("aggregation_type", current_aggregation)
    target_fields = [
        field
        for field in ("project_id", "subproject_id", "context_id", "tag_id")
        if field in data
    ]
    if target_fields:
        target_field = target_fields[0]
        target_kind = target_field.removesuffix("_id")
        if aggregation_type != target_kind:
            raise ValidationError(
                {target_field: ["Target ID must match aggregation_type."]}
            )
        model = TARGET_MODELS[target_kind]
        try:
            definition[target_kind] = model.objects.get(
                user=user, pk=data[target_field]
            )
        except model.DoesNotExist as exc:
            raise NotFound(
                f"{target_kind.title()} {data[target_field]} not found."
            ) from exc

    scalar_mapping = {
        "aggregation_type": "aggregation_type",
        "commitment_type": "commitment_type",
        "period": "period",
        "start_date": "start_date",
        "timezone": "timezone",
        "target_value": "target",
        "banking_enabled": "banking_enabled",
        "max_balance": "max_balance",
        "min_balance": "min_balance",
        "active": "active",
    }
    for api_field, service_field in scalar_mapping.items():
        if api_field in data:
            definition[service_field] = data[api_field]
    for api_field, (service_field, model) in FILTER_MODELS.items():
        if api_field in data:
            definition[service_field] = _resolve_owned_ids(
                user, data[api_field], api_field=api_field, model=model
            )
    return definition


def _target_conflict(changes, *, excluding_id=None):
    for target_kind in TARGET_MODELS:
        target = changes.get(target_kind)
        if target is None:
            continue
        queryset = Commitment.objects.filter(**{target_kind: target})
        if excluding_id is not None:
            queryset = queryset.exclude(pk=excluding_id)
        if queryset.exists():
            return Response(
                _envelope(
                    "conflict", f"This {target_kind} already has a commitment."
                ),
                status=status.HTTP_409_CONFLICT,
            )
    return None


class CommitmentsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="commitments_list",
        responses=CommitmentListResponseSerializer,
    )
    def get(self, request):
        include_streak = request.query_params.get("include") == "streak"
        commitments = list(_commitment_queryset(request.user).order_by("pk"))
        return Response(
            {
                "count": len(commitments),
                "commitments": [
                    serialize_commitment(item, include_streak=include_streak)
                    for item in commitments
                ],
            }
        )

    @extend_schema(
        operation_id="commitments_create",
        request=CommitmentCreateRequestSerializer,
        responses={201: CommitmentResourceSerializer},
    )
    def post(self, request):
        serializer = CommitmentCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        aggregation_type = data["aggregation_type"]
        definition = _definition_from_api(request.user, data)
        target = definition[aggregation_type]
        conflict_message = f"This {aggregation_type} already has a commitment."
        if Commitment.objects.filter(**{aggregation_type: target}).exists():
            return Response(
                _envelope("conflict", conflict_message),
                status=status.HTTP_409_CONFLICT,
            )
        try:
            commitment = CommitmentEditService.create(request.user, definition)
        except IntegrityError:
            return Response(
                _envelope("conflict", conflict_message),
                status=status.HTTP_409_CONFLICT,
            )
        except DjangoValidationError as exc:
            _service_validation(exc)
        return Response(
            serialize_commitment(commitment), status=status.HTTP_201_CREATED
        )


class CommitmentDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="commitments_retrieve",
        responses=CommitmentResourceSerializer,
    )
    def get(self, request, commitment_id):
        return Response(
            serialize_commitment(
                _get_commitment(request.user, commitment_id), include_streak=True
            )
        )

    @extend_schema(
        operation_id="commitments_partial_update",
        request=CommitmentChangesRequestSerializer,
        parameters=[COMMITMENT_IF_MATCH_PARAMETER],
        responses={200: CommitmentResourceSerializer},
    )
    def patch(self, request, commitment_id):
        commitment = _get_commitment(request.user, commitment_id)
        conflict = _check_version(request, commitment)
        if conflict is not None:
            return conflict
        serializer = CommitmentChangesRequestSerializer(
            data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        changes = _definition_from_api(
            request.user,
            serializer.validated_data,
            current_aggregation=commitment.aggregation_type,
        )
        try:
            commitment = CommitmentEditService.edit(
                commitment.pk, user=request.user, changes=changes
            )
        except CommitmentRestartRequired as exc:
            return Response(
                _envelope("restart_required", _service_message(exc)),
                status=status.HTTP_400_BAD_REQUEST,
            )
        except DjangoValidationError as exc:
            _service_validation(exc)
        return Response(serialize_commitment(commitment))

    @extend_schema(
        operation_id="commitments_destroy",
        request=None,
        parameters=[COMMITMENT_IF_MATCH_PARAMETER],
        responses={204: OpenApiResponse(description="Commitment deleted.")},
    )
    def delete(self, request, commitment_id):
        commitment = _commitment_queryset(request.user).filter(pk=commitment_id).first()
        if commitment is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        conflict = _check_version(request, commitment)
        if conflict is not None:
            return conflict
        commitment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CommitmentRestartView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="commitments_restart",
        request=CommitmentRestartRequestSerializer,
        parameters=[COMMITMENT_IF_MATCH_PARAMETER],
        responses={200: CommitmentResourceSerializer},
    )
    def post(self, request, commitment_id):
        commitment = _get_commitment(request.user, commitment_id)
        conflict = _check_version(request, commitment)
        if conflict is not None:
            return conflict
        serializer = CommitmentRestartRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        changes = _definition_from_api(
            request.user,
            data.get("changes", {}),
            current_aggregation=commitment.aggregation_type,
        )
        target_conflict = _target_conflict(changes, excluding_id=commitment.pk)
        if target_conflict is not None:
            return target_conflict
        try:
            commitment = CommitmentEditService.restart(
                commitment.pk,
                user=request.user,
                keep_balance=data["keep_balance"],
                changes=changes,
            )
        except IntegrityError as exc:
            return Response(
                _envelope(
                    "conflict",
                    "The requested target already has a commitment.",
                ),
                status=status.HTTP_409_CONFLICT,
            )
        except DjangoValidationError as exc:
            _service_validation(exc)
        return Response(serialize_commitment(commitment))


class CommitmentAdjustmentsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="commitments_adjustments_create",
        request=CommitmentAdjustmentRequestSerializer,
        responses={201: CommitmentAdjustmentResponseSerializer},
    )
    @transaction.atomic
    def post(self, request, commitment_id):
        serializer = CommitmentAdjustmentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        commitment = (
            Commitment.objects.select_for_update()
            .filter(user=request.user, pk=commitment_id)
            .first()
        )
        if commitment is None:
            raise NotFound(f"Commitment {commitment_id} not found.")
        data = serializer.validated_data
        next_seq = (
            commitment.adjustments.order_by("-seq")
            .values_list("seq", flat=True)
            .first()
            or 0
        ) + 1
        effective_at = timezone.now()
        adjustment = CommitmentAdjustment.objects.create(
            commitment=commitment,
            seq=next_seq,
            kind=CommitmentAdjustment.KIND_MANUAL,
            amount=data["amount"],
            effective_at=effective_at,
            reason=data.get("reason", ""),
        )
        commitment.needs_recompute = True
        commitment.version += 1
        commitment.save(update_fields=["needs_recompute", "version"])
        reconcile_commitment(commitment, force=True)
        commitment.refresh_from_db()
        return Response(
            {
                "seq": adjustment.seq,
                "amount": adjustment.amount,
                "effective_at": _iso(adjustment.effective_at),
                "reason": adjustment.reason,
                "balance": _unit_value(
                    commitment.commitment_type, commitment.balance
                ),
            },
            status=status.HTTP_201_CREATED,
        )


class CommitmentPeriodsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="commitments_periods_list",
        parameters=[CommitmentPeriodsQuerySerializer],
        responses=CommitmentPeriodListResponseSerializer,
    )
    def get(self, request, commitment_id):
        serializer = CommitmentPeriodsQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        commitment = _get_commitment(request.user, commitment_id)
        _prepare_for_read(commitment)
        generation = data.get("generation", commitment.generation)
        rows = commitment.period_rows.filter(generation=generation).select_related(
            "revision"
        ).order_by("-period_start", "-pk")
        total = rows.count()
        page = list(rows[data["offset"] : data["offset"] + data["limit"]])
        periods = []
        for row in page:
            unit_type = row.revision.commitment_type
            accrued = (
                round(row.accrued_numerator / 10000, 2)
                if unit_type == "time"
                else row.session_count
            )
            periods.append(
                {
                    "generation": row.generation,
                    "period_start": _iso(row.period_start),
                    "period_end": _iso(row.period_end),
                    "accrued": accrued,
                    "session_count": row.session_count,
                    "carryover_in": _unit_value(unit_type, row.carryover_in),
                    "balance_out": _unit_value(unit_type, row.balance_out),
                    "closed_at": _iso(row.closed_at),
                    "revision_id": row.revision_id,
                }
            )
        return Response({"count": len(periods), "total": total, "periods": periods})
