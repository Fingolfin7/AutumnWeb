from __future__ import annotations
from datetime import date
from django.utils import timezone
from django.core.exceptions import ValidationError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from core.models import Commitment, Projects, SubProjects, Tag, Context
from core.commitments import (
    build_commitment_rule_lines,
    calculate_commitment_streak,
    get_commitment_progress,
    reconcile_commitment,
)
from django.db import transaction
from core.api.helpers import _bool, _coerce_list, _compact, _err, _iso_value, _json_ok


# -----------------------
# Commitments
# -----------------------


_COMMITMENT_RULE_MODELS = {
    "include_projects": Projects,
    "exclude_projects": Projects,
    "include_subprojects": SubProjects,
    "exclude_subprojects": SubProjects,
    "include_contexts": Context,
    "exclude_contexts": Context,
    "include_tags": Tag,
    "exclude_tags": Tag,
}
_COMMITMENT_SUBPROJECT_RULES = {
    "include_subprojects",
    "exclude_subprojects",
}
_COMMITMENT_RULE_DIMENSIONS = {
    "projects": ("include_projects", "exclude_projects"),
    "subprojects": ("include_subprojects", "exclude_subprojects"),
    "contexts": ("include_contexts", "exclude_contexts"),
    "tags": ("include_tags", "exclude_tags"),
}
_COMMITMENT_ALLOWED_RULE_DIMENSIONS = {
    "context": {"tag", "project", "subproject"},
    "tag": {"project", "subproject"},
    "project": {"subproject"},
    "subproject": set(),
}


def _commitment_queryset(user):
    return (
        Commitment.objects.filter(user=user)
        .select_related("project", "subproject__parent_project", "context", "tag")
        .prefetch_related(*_COMMITMENT_RULE_MODELS)
    )


def _serialize_commitment(commitment, compact=True, include_progress=True, include_streak=False):
    progress = _iso_value(get_commitment_progress(commitment)) if include_progress else None
    if compact:
        payload = {
            "id": commitment.id,
            "agg": commitment.aggregation_type,
            "name": commitment.target_name,
            "type": commitment.commitment_type,
            "period": commitment.period,
            "target": commitment.target,
            "bal": commitment.balance,
            "active": commitment.active,
        }
        if progress is not None:
            payload["prog"] = {
                "actual": progress["actual"],
                "pct": progress["percentage"],
                "status": progress["status"],
            }
        if include_streak:
            payload["streak"] = _iso_value(calculate_commitment_streak(commitment))
        return payload

    payload = {
        "id": commitment.id,
        "aggregation_type": commitment.aggregation_type,
        "target_name": commitment.target_name,
        "commitment_type": commitment.commitment_type,
        "period": commitment.period,
        "target": commitment.target,
        "start_date": commitment.start_date.isoformat(),
        "balance": commitment.balance,
        "max_balance": commitment.max_balance,
        "min_balance": commitment.min_balance,
        "banking_enabled": commitment.banking_enabled,
        "active": commitment.active,
        "created_at": commitment.created_at.isoformat(),
        "last_reconciled": (
            commitment.last_reconciled.isoformat()
            if commitment.last_reconciled
            else None
        ),
        "rules": build_commitment_rule_lines(commitment),
    }
    if progress is not None:
        payload["progress"] = progress
    if include_streak:
        payload["streak"] = _iso_value(calculate_commitment_streak(commitment))
    return payload


def _resolve_subproject_name(user, value):
    if not isinstance(value, str) or "/" not in value:
        raise ValidationError("Subproject names must use the format 'Project/Subproject'.")
    project_name, subproject_name = (part.strip() for part in value.split("/", 1))
    if not project_name or not subproject_name:
        raise ValidationError("Subproject names must use the format 'Project/Subproject'.")
    subproject = SubProjects.objects.filter(
        user=user,
        name__iexact=subproject_name,
        parent_project__name__iexact=project_name,
    ).first()
    if not subproject:
        raise ValidationError(f"Subproject '{value}' was not found.")
    return subproject


def _resolve_commitment_target(user, aggregation_type, target_name, project_name=None):
    model_map = {
        "project": Projects,
        "context": Context,
        "tag": Tag,
    }
    if aggregation_type == "subproject":
        if not project_name:
            raise ValidationError("Subproject commitments require 'project' to disambiguate the target.")
        return _resolve_subproject_name(user, f"{project_name}/{target_name}")
    model = model_map.get(aggregation_type)
    if model is None:
        raise ValidationError("aggregation_type must be project, subproject, context, or tag.")
    target = model.objects.filter(user=user, name__iexact=target_name).first()
    if not target:
        raise ValidationError(f"{aggregation_type.title()} '{target_name}' was not found.")
    return target


def _resolve_commitment_rules(user, data, existing=None):
    rules = {}
    for field, model in _COMMITMENT_RULE_MODELS.items():
        if field not in data:
            rules[field] = list(getattr(existing, field).all()) if existing else []
            continue
        values = _coerce_list(data.get(field))
        resolved = []
        for value in values:
            if field in _COMMITMENT_SUBPROJECT_RULES:
                resolved.append(_resolve_subproject_name(user, value))
            else:
                obj = model.objects.filter(user=user, name__iexact=str(value).strip()).first()
                if not obj:
                    label = field.replace("_", " ")
                    raise ValidationError(f"{label.title()} entry '{value}' was not found.")
                resolved.append(obj)
        rules[field] = resolved
    return rules


def _validate_commitment_rules(aggregation_type, rules):
    allowed_dimensions = _COMMITMENT_ALLOWED_RULE_DIMENSIONS[aggregation_type]
    for dimension, fields in _COMMITMENT_RULE_DIMENSIONS.items():
        if dimension.rstrip("s") not in allowed_dimensions:
            for field in fields:
                rules[field] = []

    for dimension, (include_field, exclude_field) in _COMMITMENT_RULE_DIMENSIONS.items():
        include_items = set(rules[include_field])
        exclude_items = set(rules[exclude_field])
        overlap = include_items.intersection(exclude_items)
        if overlap:
            names = ", ".join(sorted(item.name for item in overlap))
            raise ValidationError(
                f"Cannot both include and exclude the same {dimension}: {names}."
            )


def _apply_commitment_rules(commitment, rules):
    for field, objects in rules.items():
        getattr(commitment, field).set(objects)


def _commitment_target_value(data, require=True):
    value = data.get("target_value")
    if value is None and isinstance(data.get("target"), (int, float)):
        value = data["target"]
    if value is None:
        if require:
            raise ValidationError("Missing 'target_value'.")
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValidationError("target_value must be a positive integer.")
    if value <= 0:
        raise ValidationError("target_value must be a positive integer.")
    return value


def _validate_commitment_balances(commitment):
    if commitment.min_balance > commitment.max_balance:
        raise ValidationError("Min balance cannot be greater than max balance.")
    if commitment.min_balance > 0:
        raise ValidationError("Min balance must be zero or negative.")


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def commitments(request):
    """List or create commitments for the authenticated user.

    GET query params: active=true|false, aggregation_type, progress=true|false,
    streak=true|false, compact=true|false (default true).

    POST JSON body:
      - aggregation_type (required): project, subproject, context, or tag
      - target (required): target name; subprojects also require project
      - target_value (required): positive integer (target may be numeric if target_name is supplied)
      - commitment_type (default time), period (default weekly), start_date (ISO date)
      - banking_enabled, max_balance, min_balance
      - include_projects/exclude_projects, include_subprojects/exclude_subprojects
        (Project/Subproject), include_contexts/exclude_contexts, include_tags/exclude_tags
    """
    compact = _compact(request)
    if request.method == "GET":
        qp = request.query_params
        queryset = _commitment_queryset(request.user).order_by("id")
        active = qp.get("active")
        if active is not None:
            queryset = queryset.filter(active=_bool(active))
        aggregation_type = qp.get("aggregation_type")
        if aggregation_type:
            queryset = queryset.filter(aggregation_type=aggregation_type)
        include_progress = _bool(qp.get("progress"), True)
        include_streak = _bool(qp.get("streak"), False)
        payload = []
        for commitment in queryset:
            if commitment.active and include_progress:
                reconcile_commitment(commitment)
            payload.append(
                _serialize_commitment(
                    commitment,
                    compact=compact,
                    include_progress=include_progress,
                    include_streak=include_streak,
                )
            )
        return Response(_json_ok({"count": len(payload), "commitments": payload}, compact))

    data = request.data
    aggregation_type = data.get("aggregation_type")
    target_name = data.get("target_name") or (
        data.get("target") if isinstance(data.get("target"), str) else None
    )
    if not aggregation_type:
        return _err("Missing 'aggregation_type'.")
    if not target_name:
        return _err("Missing target name.")
    try:
        target = _resolve_commitment_target(
            request.user, aggregation_type, target_name, data.get("project")
        )
        target_value = _commitment_target_value(data)
        start_date = data.get("start_date")
        parsed_start_date = date.fromisoformat(start_date) if start_date else timezone.localdate()
        commitment = Commitment(
            user=request.user,
            aggregation_type=aggregation_type,
            commitment_type=data.get("commitment_type", "time"),
            period=data.get("period", "weekly"),
            start_date=parsed_start_date,
            target=target_value,
            banking_enabled=_bool(data.get("banking_enabled"), True),
            max_balance=data.get("max_balance", 600),
            min_balance=data.get("min_balance", -600),
            **{aggregation_type: target},
        )
        if Commitment.objects.filter(**{aggregation_type: target}).exists():
            return _err(f"This {aggregation_type} already has a commitment.")
        rules = _resolve_commitment_rules(request.user, data)
        _validate_commitment_rules(aggregation_type, rules)
        _validate_commitment_balances(commitment)
        commitment.full_clean()
    except (TypeError, ValueError, ValidationError) as exc:
        return _err(str(exc))

    with transaction.atomic():
        commitment.save()
        _apply_commitment_rules(commitment, rules)
    return Response(
        _json_ok(
            {"commitment": _serialize_commitment(commitment, compact=False)},
            compact=False,
        ),
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def commitment_detail(request, commitment_id):
    """Get, update, or delete one authenticated user's commitment.

    PATCH JSON body may contain commitment_type, period, target_value (or numeric
    target), start_date, banking_enabled, max_balance, min_balance, active, and
    any include/exclude rule lists. aggregation_type and target cannot change.
    """
    commitment = _commitment_queryset(request.user).filter(pk=commitment_id).first()
    if not commitment:
        return _err("Commitment not found.", status.HTTP_404_NOT_FOUND)

    if request.method == "DELETE":
        commitment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    if request.method == "GET":
        if commitment.active:
            reconcile_commitment(commitment)
        return Response(
            _json_ok(
                {
                    "commitment": _serialize_commitment(
                        commitment, compact=False, include_progress=True, include_streak=True
                    )
                },
                compact=False,
            )
        )

    data = request.data
    if "aggregation_type" in data or "target_name" in data or (
        isinstance(data.get("target"), str)
    ):
        return _err("Changing aggregation_type or target is not allowed.")
    allowed_fields = {
        "commitment_type",
        "period",
        "start_date",
        "banking_enabled",
        "max_balance",
        "min_balance",
        "active",
    }
    try:
        for field in allowed_fields.intersection(data.keys()):
            value = data[field]
            if field == "start_date":
                value = date.fromisoformat(value)
            elif field in {"banking_enabled", "active"}:
                value = _bool(value)
            setattr(commitment, field, value)
        target_value = _commitment_target_value(data, require=False)
        if target_value is not None:
            commitment.target = target_value
        rules = _resolve_commitment_rules(request.user, data, existing=commitment)
        _validate_commitment_rules(commitment.aggregation_type, rules)
        _validate_commitment_balances(commitment)
        commitment.full_clean()
    except (TypeError, ValueError, ValidationError) as exc:
        return _err(str(exc))

    with transaction.atomic():
        commitment.save()
        _apply_commitment_rules(commitment, rules)
    return Response(
        _json_ok(
            {"commitment": _serialize_commitment(commitment, compact=False)},
            compact=False,
        )
    )
