# core/api.py
from __future__ import annotations

import os
import re
import json
from datetime import date, datetime, timedelta, time
from collections import defaultdict

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Min, Max
from django.core.exceptions import ValidationError

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .models import Commitment, Projects, SubProjects, Sessions, status_choices, Tag, Context
from .session_ledger import (
    create_session as ledger_create_session,
    delete_session as ledger_delete_session,
    mutate_session as ledger_mutate_session,
)
from .commitments import (
    build_commitment_rule_lines,
    calculate_commitment_streak,
    get_commitment_progress,
    reconcile_commitment,
)
from .serializers import (
    ProjectSerializer,
    SubProjectSerializer,
    SessionSerializer,
)
from .utils import (
    parse_date_or_datetime,
    filter_sessions_by_params,
    tally_project_durations,
    session_exists,
    sessions_get_earliest_latest,
    filter_by_active_context,
    build_project_json_from_sessions,
    json_compress,
    json_decompress,
    parse_stop_after_duration,
    stop_expired_timers,
)
from .importer import run_import
from django.db import transaction

# -----------------------
# Helpers
# -----------------------


def _now() -> datetime:
    return timezone.now()


def _bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "y", "on")


def _compact(request) -> bool:
    qp = getattr(request, "query_params", request.GET)
    return _bool(qp.get("compact"), True)


def _coerce_list(val):
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        if not val:
            return []
        return [v.strip() for v in val.split(",") if v.strip()]
    return list(val)


def _json_ok(extra=None, compact=True):
    base = {"ok": True} if compact else {"ok": True, "message": "success"}
    return {**base, **(extra or {})}


def _err(msg, code=status.HTTP_400_BAD_REQUEST):
    return Response({"ok": False, "error": msg}, status=code)


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


def _iso_value(value):
    """Convert dates in commitment-domain results to JSON-safe ISO strings."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _iso_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_iso_value(item) for item in value]
    return value


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


def _get_active_sessions(user, project_name=None):
    stop_expired_timers(user)
    qs = Sessions.objects.filter(is_active=True, user=user).order_by("-start_time")
    if project_name:
        qs = qs.filter(project__name__iexact=project_name)
    return qs


def _pick_target_session(user, session_id=None, project_name=None):
    if session_id:
        return get_object_or_404(Sessions, pk=session_id, user=user)
    qs = _get_active_sessions(user, project_name)
    return qs.first()


def _serialize_session(sess: Sessions, compact=True):
    elapsed = sess.duration
    if compact:
        d = {
            "id": sess.id,
            "p": sess.project.name,
            "pid": sess.project.id,
            "subs": [sp.name for sp in sess.subprojects.all()],
            "start": sess.start_time.isoformat(),
            "end": sess.end_time.isoformat() if sess.end_time else None,
            "stop_at": sess.auto_stop_at.isoformat() if sess.auto_stop_at else None,
            "active": sess.is_active,
            "elapsed": elapsed,
            "crosses_dst_transition": sess.crosses_dst_transition,
        }
        if sess.note:
            d["note"] = sess.note
        return d
    return {
        "id": sess.id,
        "project": sess.project.name,
        "project_id": sess.project.id,
        "subprojects": [sp.name for sp in sess.subprojects.all()],
        "start_time": sess.start_time.isoformat(),
        "end_time": sess.end_time.isoformat() if sess.end_time else None,
        "auto_stop_at": sess.auto_stop_at.isoformat() if sess.auto_stop_at else None,
        "is_active": sess.is_active,
        "elapsed_minutes": elapsed,
        "note": sess.note or "",
        "crosses_dst_transition": sess.crosses_dst_transition,
    }


def _serialize_project_grouped(projects, compact=True):
    # Be tolerant of unexpected/legacy status values.
    # Older data can include 'archived' (and potentially others), so don't assume
    # only active/paused/complete exists.
    groups = {"active": [], "paused": [], "complete": [], "archived": []}
    for p in projects:
        key = getattr(p, "status", None) or "active"
        if key not in groups:
            groups[key] = []

        if compact:
            groups[key].append(p.name)
        else:
            # Calculate session stats
            sessions = p.sessions.filter(is_active=False)
            session_count = sessions.count()
            avg_session = (p.total_time / session_count) if session_count > 0 else 0

            groups[key].append(
                {
                    "id": p.id,
                    "name": p.name,
                    "status": p.status,
                    "total_time": p.total_time,
                    "session_count": session_count,
                    "avg_session_duration": round(avg_session, 1),
                    "start_date": p.start_date.isoformat(),
                    "last_updated": p.last_updated.isoformat(),
                    "description": p.description or "",
                    "context": p.context.name if p.context else None,
                    "tags": [t.name for t in p.tags.all()],
                }
            )

    summary = {
        "active": len(groups.get("active", [])),
        "paused": len(groups.get("paused", [])),
        "complete": len(groups.get("complete", [])),
        "archived": len(groups.get("archived", [])),
        "total": len(projects),
    }
    return {"summary": summary, "projects": groups}


def _parse_track_times(data):
    # Accept either ISO strings:
    #   start, end
    # Or legacy: date + start_time, end_time in %m-%d-%Y / %H:%M:%S formats.
    if data.get("start") and data.get("end"):
        start = parse_date_or_datetime(data["start"])
        end = parse_date_or_datetime(data["end"])
        if timezone.is_naive(start):
            start = timezone.make_aware(start)
        if timezone.is_naive(end):
            end = timezone.make_aware(end)
        return start, end

    date = data.get("date")
    st = data.get("start_time")
    et = data.get("end_time")
    if not (date and st and et):
        raise ValueError(
            "Provide either 'start' and 'end' (ISO or known fmt) or "
            "'date', 'start_time', 'end_time'."
        )

    start = timezone.make_aware(datetime.strptime(f"{date} {st}", "%m-%d-%Y %H:%M:%S"))
    end = timezone.make_aware(datetime.strptime(f"{date} {et}", "%m-%d-%Y %H:%M:%S"))
    return start, end


# -----------------------
# New compact API
# -----------------------


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def timer_start(request):
    """
    Start a new timer.
    JSON: { "project": str, "subprojects": [str]|"a,b", "note": str? }
    """
    compact = _compact(request)
    project_name = request.data.get("project")
    if not project_name:
        return _err("Missing 'project'")

    project = Projects.objects.filter(name=project_name, user=request.user).first()
    if not project:
        return _err("Project not found", status.HTTP_404_NOT_FOUND)

    stop_after_value = request.data.get("stop_after")
    if stop_after_value is None:
        stop_after_value = request.data.get("stop_after_minutes")

    try:
        stop_after = parse_stop_after_duration(stop_after_value)
    except ValueError as exc:
        return _err(str(exc))

    subs = _coerce_list(request.data.get("subprojects"))
    note = request.data.get("note", "").strip()

    # Resolve subprojects (must exist)
    sub_qs = SubProjects.objects.filter(
        parent_project=project, user=request.user, name__in=subs
    )
    if subs and sub_qs.count() != len(set([s.lower() for s in subs])):
        # find missing
        existing = set(sp.name.lower() for sp in sub_qs)
        missing = [s for s in subs if s.lower() not in existing]
        return _err(f"Unknown subprojects: {', '.join(missing)}")

    start_time = _now()
    sess = ledger_create_session(
        user=request.user,
        project=project,
        start_time=start_time,
        auto_stop_at=start_time + stop_after if stop_after else None,
        is_active=True,
        note=note or None,
        subprojects=list(sub_qs),
    )

    return Response(
        _json_ok({"session": _serialize_session(sess, compact)}, compact),
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def timer_stop(request):
    """
    Stop the current timer (or a specific one).
    JSON: { "session_id": int?, "project": str?, "note": str? }
    """
    compact = _compact(request)
    stop_expired_timers(request.user)
    sess = _pick_target_session(
        request.user,
        session_id=request.data.get("session_id"),
        project_name=request.data.get("project"),
    )
    if not sess:
        return _err("No active timer found", status.HTTP_404_NOT_FOUND)
    if not sess.is_active:
        return _err("Session not active", status.HTTP_400_BAD_REQUEST)

    end_time = _now()
    note = sess.note
    if "note" in request.data and request.data["note"] is not None:
        note = str(request.data["note"])
    sess = ledger_mutate_session(
        sess.pk,
        user=request.user,
        end_time=end_time,
        is_active=False,
        auto_stop_at=None,
        note=note,
    )

    return Response(
        _json_ok(
            {
                "session": _serialize_session(sess, compact),
                "duration": sess.duration,
            },
            compact,
        ),
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def timer_status(request):
    """
    Show status of current timer(s).
    Query: session_id?, project?
    """
    stop_expired_timers(request.user)
    compact = _compact(request)
    qp = request.query_params
    session_id = qp.get("session_id")
    project = qp.get("project")
    if session_id:
        try:
            sess = Sessions.objects.get(pk=int(session_id), user=request.user)
            if not sess.is_active:
                return _err("Session not active", status.HTTP_400_BAD_REQUEST)
            return Response(
                _json_ok({"session": _serialize_session(sess, compact)}, compact)
            )
        except Sessions.DoesNotExist:
            return _err("Session not found", status.HTTP_404_NOT_FOUND)

    actives = _get_active_sessions(request.user, project)
    if not actives.exists():
        return Response(_json_ok({"active": 0}, compact))

    payload = (
        [_serialize_session(s, compact) for s in actives]
        if not compact
        else [_serialize_session(s, True) for s in actives]
    )
    return Response(_json_ok({"active": len(payload), "sessions": payload}, compact))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def timer_restart(request):
    """
    Restart current timer (or a specific one): set start_time=now, active=True.
    JSON: { "session_id": int?, "project": str? }
    """
    compact = _compact(request)
    stop_expired_timers(request.user)
    sess = _pick_target_session(
        request.user,
        session_id=request.data.get("session_id"),
        project_name=request.data.get("project"),
    )
    if not sess:
        return _err("No active timer found", status.HTTP_404_NOT_FOUND)

    restart_time = _now()
    auto_stop_duration = None
    if sess.auto_stop_at and sess.start_time and sess.auto_stop_at > sess.start_time:
        auto_stop_duration = sess.auto_stop_at - sess.start_time

    sess = ledger_mutate_session(
        sess.pk,
        user=request.user,
        start_time=restart_time,
        is_active=True,
        end_time=None,
        auto_stop_at=(
            restart_time + auto_stop_duration if auto_stop_duration else None
        ),
    )
    return Response(_json_ok({"session": _serialize_session(sess, compact)}, compact))


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def timer_delete(request):
    """
    Remove a timer without saving a session.
    JSON: { "session_id": int? } or query param session_id
    If not provided, deletes most-recent active session.
    """
    compact = _compact(request)
    session_id = request.data.get("session_id") or request.query_params.get(
        "session_id"
    )
    sess = _pick_target_session(request.user, session_id=session_id)
    if not sess:
        return _err("No active timer found", status.HTTP_404_NOT_FOUND)

    sess_id = sess.id
    ledger_delete_session(sess.pk, user=request.user)
    return Response(_json_ok({"deleted": sess_id}, compact), status=200)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def track_session(request):
    """
    Track a project for a given time period (saved completed session).
    JSON:
      {
        "project": str,
        "subprojects": [str]|"a,b",
        "start": str(iso)?,
        "end": str(iso)?,
        "date": "%m-%d-%Y"?,
        "start_time": "%H:%M:%S"?,
        "end_time": "%H:%M:%S"?,
        "note": str?
      }
    """
    compact = _compact(request)
    project_name = request.data.get("project")
    if not project_name:
        return _err("Missing 'project'")

    project = Projects.objects.filter(name=project_name, user=request.user).first()
    if not project:
        return _err("Project not found", status.HTTP_404_NOT_FOUND)

    try:
        start_time, end_time = _parse_track_times(request.data)
    except ValueError as e:
        return _err(str(e))

    if end_time < start_time:
        # crossed midnight
        start_time -= timedelta(days=1)

    subs = _coerce_list(request.data.get("subprojects"))
    sub_qs = SubProjects.objects.filter(
        parent_project=project, user=request.user, name__in=subs
    )
    if subs and sub_qs.count() != len(set([s.lower() for s in subs])):
        existing = set(sp.name.lower() for sp in sub_qs)
        missing = [s for s in subs if s.lower() not in existing]
        return _err(f"Unknown subprojects: {', '.join(missing)}")

    note = request.data.get("note", "").strip()
    sess = ledger_create_session(
        user=request.user,
        project=project,
        start_time=start_time,
        end_time=end_time,
        is_active=False,
        note=note or None,
        subprojects=list(sub_qs),
    )

    return Response(
        _json_ok({"session": _serialize_session(sess, compact)}, compact),
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def projects_list_grouped(request):
    """
    List all projects grouped by status.
    Query: start_date?, end_date?, compact?, context?, tags?
    """
    compact = _compact(request)
    qp = request.query_params
    start = qp.get("start_date")
    end = qp.get("end_date")

    projects_qs = Projects.objects.filter(user=request.user)
    projects_qs = filter_by_active_context(
        projects_qs, request, override_context_id=qp.get("context")
    )
    projects_qs = _apply_tag_filters(
        qp, projects_qs, kind="projects", user=request.user
    )
    projects_qs = _apply_exclude_filters(qp, projects_qs, kind="projects", user=request.user)

    if start or end:
        projects = in_window(projects_qs, start, end)
    else:
        projects = list(projects_qs)

    return Response(_serialize_project_grouped(projects, compact))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def projects_list_flat(request):
    """
    List all projects as a flat (ungrouped) list with optional filters.

    Query params:
      - status: filter by status (active, paused, complete, archived) - optional
      - context: filter by context id or name - optional
      - tags: filter by tag names (comma-separated) - optional
      - search: search by name (icontains) - optional
      - compact: true/false (default true)

    Returns (compact):
      {"count": int, "projects": ["Project A", "Project B", ...]}
    Returns (full):
      {"count": int, "projects": [{"id", "name", "status", "description",
                                   "total_minutes", "session_count", "avg_session_minutes",
                                   "context", "tags"}, ...]}
    """
    compact = _compact(request)
    qp = request.query_params

    projects_qs = Projects.objects.filter(user=request.user)

    # Filter by status
    status_filter = qp.get("status")
    if status_filter:
        projects_qs = projects_qs.filter(status=status_filter.lower())

    # Filter by context (id or name)
    context_filter = qp.get("context")
    if context_filter:
        try:
            context_id = int(context_filter)
            projects_qs = projects_qs.filter(context_id=context_id)
        except (TypeError, ValueError):
            # Treat as context name
            projects_qs = projects_qs.filter(context__name__iexact=context_filter)

    # Filter by tags
    projects_qs = _apply_tag_filters(qp, projects_qs, kind="projects", user=request.user)

    # Exclude projects
    projects_qs = _apply_exclude_filters(qp, projects_qs, kind="projects", user=request.user)

    # Search by name
    search_term = qp.get("search")
    if search_term:
        projects_qs = projects_qs.filter(name__icontains=search_term)

    projects_qs = projects_qs.order_by("name")

    if compact:
        payload = [p.name for p in projects_qs]
    else:
        payload = []
        for p in projects_qs:
            sessions = p.sessions.filter(is_active=False)
            session_count = sessions.count()
            total_minutes = float(p.total_time or 0.0)
            avg_session_minutes = (
                round(total_minutes / session_count, 2) if session_count > 0 else 0.0
            )
            payload.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "status": p.status,
                    "description": p.description or "",
                    "total_minutes": round(total_minutes, 2),
                    "session_count": session_count,
                    "avg_session_minutes": avg_session_minutes,
                    "context": p.context.name if p.context else None,
                    "tags": [t.name for t in p.tags.all()],
                }
            )

    return Response({"count": len(payload), "projects": payload})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def subprojects_list(request):
    """
    List subprojects for a given project.

    Query params:
      - project (required): project name
      - compact: true/false (default true)

    Returns (compact):
      {"project": str, "subprojects": ["Sub A", "Sub B", ...]}
    Returns (full):
      {"project": str, "project_id": int, "subprojects": [
          {"id", "name", "description", "session_count", "total_minutes"}, ...
      ]}
    """
    project_name = request.query_params.get("project") or request.query_params.get(
        "project_name"
    )
    if not project_name:
        return _err("Missing 'project'")

    project = Projects.objects.filter(name=project_name, user=request.user).first()
    if not project:
        return _err("Project not found", status.HTTP_404_NOT_FOUND)

    subprojects = SubProjects.objects.filter(
        parent_project=project, user=request.user
    ).order_by("name")

    compact = _compact(request)
    if compact:
        return Response(
            {"project": project_name, "subprojects": [s.name for s in subprojects]}
        )

    payload = []
    for sp in subprojects:
        session_count = sp.sessions.filter(is_active=False).count()
        total_minutes = float(sp.total_time or 0.0)
        payload.append(
            {
                "id": sp.id,
                "name": sp.name,
                "description": sp.description or "",
                "session_count": session_count,
                "total_minutes": round(total_minutes, 2),
            }
        )

    return Response(
        {"project": project_name, "project_id": project.id, "subprojects": payload}
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def totals(request):
    """
    Show total time spent on a project and its subprojects.
    Query: project (required), start_date?, end_date?, compact?, context?, tags?
    """
    compact = _compact(request)
    project_name = request.query_params.get("project")
    if not project_name:
        return _err("Missing 'project'")

    sessions = Sessions.objects.filter(is_active=False, user=request.user)
    sessions = sessions.filter(project__name__iexact=project_name)
    sessions = filter_by_active_context(
        sessions, request, override_context_id=request.query_params.get("context")
    )
    sessions = _apply_tag_filters(
        request.query_params, sessions, kind="sessions", user=request.user
    )
    sessions = filter_sessions_by_params(request, sessions)

    # Project total
    proj_total = 0.0
    sub_totals = defaultdict(float)
    for s in sessions:
        dur = s.duration or 0.0
        proj_total += dur
        subs = list(s.subprojects.all())
        if subs:
            for sp in subs:
                sub_totals[sp.name] += dur
        else:
            sub_totals["no subproject"] += dur

    if compact:
        subs = [[k, round(v, 4)] for k, v in sub_totals.items()]
        return Response(
            {"project": project_name, "total": round(proj_total, 4), "subs": subs}
        )
    else:
        return Response(
            {
                "project": project_name,
                "total_minutes": round(proj_total, 4),
                "subprojects": [
                    {"name": k, "total_minutes": round(v, 4)}
                    for k, v in sub_totals.items()
                ],
            }
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def rename_entity(request):
    """
    Rename a project or subproject.
    JSON:
      - Project: { "type": "project", "project": "Old", "new_name": "New" }
      - Subproject: {
          "type": "subproject",
          "project": "Parent",
          "subproject": "OldSub",
          "new_name": "NewSub"
        }
    """
    ent_type = (request.data.get("type") or "").lower()
    new_name = request.data.get("new_name")
    if ent_type not in ("project", "subproject"):
        return _err("type must be 'project' or 'subproject'")
    if not new_name:
        return _err("Missing 'new_name'")

    if ent_type == "project":
        old = request.data.get("project")
        if not old:
            return _err("Missing 'project'")
        proj = get_object_or_404(Projects, name=old, user=request.user)
        if (
            Projects.objects.filter(user=request.user, name=new_name)
            .exclude(pk=proj.pk)
            .exists()
        ):
            return _err("Project name already exists", status.HTTP_409_CONFLICT)
        proj.name = new_name
        proj.save()
        return Response({"ok": True, "project": proj.name})

    # subproject
    parent = request.data.get("project")
    sub = request.data.get("subproject")
    if not parent or not sub:
        return _err("Missing 'project' or 'subproject'")
    proj = get_object_or_404(Projects, name=parent, user=request.user)
    sp = get_object_or_404(
        SubProjects, parent_project=proj, user=request.user, name=sub
    )
    if (
        SubProjects.objects.filter(
            user=request.user, parent_project=proj, name=new_name
        )
        .exclude(pk=sp.pk)
        .exists()
    ):
        return _err("Subproject name already exists", status.HTTP_409_CONFLICT)
    sp.name = new_name
    sp.save()
    return Response({"ok": True, "project": parent, "subproject": sp.name})


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def project_delete_body(request):
    """
    Delete a project via JSON body: { "project": "name" }
    """
    name = request.data.get("project")
    if not name:
        return _err("Missing 'project'")
    proj = get_object_or_404(Projects, name=name, user=request.user)
    proj.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search_sessions(request):
    """
    Search sessions by any of: project, subproject, start_date, end_date,
    note_snippet. At least one of those must be provided.
    Optional:
      - active=true|false (default false -> saved sessions)
      - order (default: '-end_time' for saved, '-start_time' for active)
      - limit, offset
      - compact=true|false (default true)
    Returns compact by default: {"count", "sessions":[{id,p,subs,start,end,dur}]}
    """
    compact = _compact(request)
    qp = request.query_params

    # Require at least one primary search field
    if not any(
        qp.get(k)
        for k in (
            "project",
            "project_name",
            "subproject",
            "start_date",
            "end_date",
            "note_snippet",
        )
    ):
        return _err(
            "Provide at least one of: project|subproject|start_date|"
            "end_date|note_snippet"
        )

    active = _bool(qp.get("active"), False)
    order = qp.get("order") or ("-start_time" if active else "-end_time")
    limit = qp.get("limit")
    offset = qp.get("offset")

    # Normalize alias: project -> project_name for the filter helper
    qp2 = qp.copy()
    if qp2.get("project") and not qp2.get("project_name"):
        qp2["project_name"] = qp2["project"]

    sessions = Sessions.objects.filter(user=request.user)
    sessions = (
        sessions.filter(is_active=True) if active else sessions.filter(is_active=False)
    )

    # context filter (consistent with other endpoints)
    sessions = filter_by_active_context(
        sessions, request, override_context_id=qp.get("context")
    )
    # tag filter
    sessions = _apply_tag_filters(qp, sessions, kind="sessions", user=request.user)

    # Shim request so filter_sessions_by_params sees the normalized params
    shim = type("Req", (), {"query_params": qp2, "GET": qp2})()
    sessions = filter_sessions_by_params(shim, sessions)

    try:
        sessions = sessions.order_by(order)
    except Exception:
        sessions = sessions.order_by("-end_time")

    # lightweight paging
    try:
        if offset is not None:
            sessions = sessions[int(offset) :]
        if limit is not None:
            sessions = sessions[: int(limit)]
    except Exception:
        pass

    if compact:
        payload = [
            {
                "id": s.id,
                "p": s.project.name,
                "pid": s.project.id,
                "subs": [sp.name for sp in s.subprojects.all()],
                "start": s.start_time.isoformat(),
                "end": s.end_time.isoformat() if s.end_time else None,
                "dur": s.duration,  # minutes
                "crosses_dst_transition": s.crosses_dst_transition,
            }
            for s in sessions
        ]
        return Response({"count": len(payload), "sessions": payload})
    else:
        payload = [
            {
                "id": s.id,
                "project": s.project.name,
                "project_id": s.project.id,
                "subprojects": [sp.name for sp in s.subprojects.all()],
                "start_time": s.start_time.isoformat(),
                "end_time": s.end_time.isoformat() if s.end_time else None,
                "duration_minutes": s.duration,
                "note": s.note or "",
                "is_active": s.is_active,
                "crosses_dst_transition": s.crosses_dst_transition,
            }
            for s in sessions
        ]
        return Response({"count": len(payload), "sessions": payload})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def log_activity(request):
    """
    Show activity logs. Supports:
      - period=week|month|day|all
      - start_date?, end_date?
      - project or project_name
      - subproject
      - note_snippet
      - context?
      - tags?
      - compact?
    Defaults to period=week if no start/end/period filters provided by client.
    """
    compact = _compact(request)
    qp = request.query_params
    period = (qp.get("period") or "").lower()

    sessions = Sessions.objects.filter(is_active=False, user=request.user)
    sessions = filter_by_active_context(
        sessions, request, override_context_id=qp.get("context")
    )
    sessions = _apply_tag_filters(qp, sessions, kind="sessions", user=request.user)

    # Default period window if no explicit start/end
    if period in ("day", "week", "month") and not (
        qp.get("start_date") or qp.get("end_date")
    ):
        now = timezone.localtime(_now())
        if period == "day":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            # Trailing 7-day window (inclusive) rather than "since Monday"
            start = (now - timedelta(days=7)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        else:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        sessions = sessions.filter(end_time__gte=start)

    # Normalize alias: project -> project_name for the filter helper
    qp2 = qp.copy()
    if qp2.get("project") and not qp2.get("project_name"):
        qp2["project_name"] = qp2["project"]

    shim = type("Req", (), {"query_params": qp2, "GET": qp2})()
    sessions = filter_sessions_by_params(shim, sessions).order_by("-end_time")

    if compact:
        logs = [
            {
                "id": s.id,
                "p": s.project.name,
                "pid": s.project.id,
                "subs": [sp.name for sp in s.subprojects.all()],
                "start": s.start_time.isoformat(),
                "end": s.end_time.isoformat() if s.end_time else None,
                "dur": s.duration,  # minutes
                "crosses_dst_transition": s.crosses_dst_transition,
            }
            for s in sessions
        ]
    else:
        logs = [
            {
                "id": s.id,
                "project": s.project.name,
                "project_id": s.project.id,
                "subprojects": [sp.name for sp in s.subprojects.all()],
                "start_time": s.start_time.isoformat(),
                "end_time": s.end_time.isoformat() if s.end_time else None,
                "duration_minutes": s.duration,
                "note": s.note or "",
                "crosses_dst_transition": s.crosses_dst_transition,
            }
            for s in sessions
        ]
    return Response({"count": len(logs), "logs": logs})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mark_project(request):
    """
    Mark a project as active, paused, or complete.
    JSON: { "project": str, "status": "active|paused|complete" }
    """
    project_name = request.data.get("project")
    status_val = (request.data.get("status") or "").lower()
    valid = {k for k, _ in status_choices}
    if status_val not in valid:
        return _err("Invalid status (use: active, paused, complete)")
    proj = get_object_or_404(Projects, name=project_name, user=request.user)
    proj.status = status_val
    proj.save()
    return Response({"ok": True, "project": proj.name, "status": proj.status})


# -----------------------
# Existing endpoints (moved here, small fixes), kept for compatibility
# -----------------------


def _clean_required_name(value, label):
    if not isinstance(value, str):
        raise ValueError(f"'{label}' must be a string.")
    value = value.strip()
    if not value:
        raise ValueError(f"Missing '{label}'.")
    if len(value) > 100:
        raise ValueError(f"'{label}' must be 100 characters or fewer.")
    return value


def _clean_optional_text(value, label, *, allow_null=False, max_length=None):
    if value is None and allow_null:
        return None
    if not isinstance(value, str):
        raise ValueError(f"'{label}' must be a string.")
    value = value.strip()
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"'{label}' must be {max_length} characters or fewer.")
    return value


def _resolve_context_name(user, value):
    name = _clean_required_name(value, "context")
    context = Context.objects.filter(user=user, name__iexact=name).first()
    if context:
        return context
    available = list(
        Context.objects.filter(user=user).order_by("name").values_list("name", flat=True)
    )
    available_names = ", ".join(available) if available else "(none)"
    raise ValueError(
        f"Unknown context '{name}'. Available contexts: {available_names}."
    )


def _resolve_tag_names(user, value):
    if not isinstance(value, list):
        raise ValueError("'tags' must be a list of strings.")

    names = [_clean_required_name(raw_name, "tag") for raw_name in _coerce_list(value)]
    tags = []
    for name in names:
        tag = Tag.objects.filter(user=user, name__iexact=name).first()
        if not tag:
            tag = Tag.objects.create(user=user, name=name)
        if tag not in tags:
            tags.append(tag)
    return tags


def _serialize_project_metadata(project, compact):
    context_name = project.context.name if project.context else None
    tag_names = [tag.name for tag in project.tags.all()]
    if compact:
        return {
            "p": project.name,
            "desc": project.description,
            "status": project.status,
            "ctx": context_name,
            "tags": tag_names,
        }
    return {
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "context": context_name,
        "tags": tag_names,
    }


def _serialize_context_for_api(context, user, compact):
    if compact:
        return {"id": context.id, "name": context.name}

    project_count = context.projects.count()
    sessions = Sessions.objects.filter(
        user=user,
        project__context=context,
        is_active=False,
    )
    session_count = sessions.count()
    total_minutes = sum(session.duration or 0 for session in sessions)
    return {
        "id": context.id,
        "name": context.name,
        "description": context.description or "",
        "project_count": project_count,
        "session_count": session_count,
        "total_minutes": round(total_minutes, 2),
        "avg_session_minutes": (
            round(total_minutes / session_count, 2) if session_count > 0 else 0.0
        ),
    }


def _serialize_tag_for_api(tag, user, compact):
    if compact:
        return {"id": tag.id, "name": tag.name}

    project_count = tag.projects.filter(user=user).count()
    sessions = Sessions.objects.filter(
        user=user,
        project__tags=tag,
        is_active=False,
    )
    session_count = sessions.count()
    total_minutes = sum(session.duration or 0 for session in sessions)
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color or "",
        "project_count": project_count,
        "session_count": session_count,
        "total_minutes": round(total_minutes, 2),
        "avg_session_minutes": (
            round(total_minutes / session_count, 2) if session_count > 0 else 0.0
        ),
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_project(request):
    has_context = "context" in request.data
    has_tags = "tags" in request.data
    context = None
    tags = []
    try:
        if has_context:
            context = _resolve_context_name(request.user, request.data.get("context"))
        if has_tags:
            raw_tags = request.data.get("tags")
            if not isinstance(raw_tags, list):
                raise ValueError("'tags' must be a list of strings.")
            [_clean_required_name(tag, "tag") for tag in _coerce_list(raw_tags)]
    except ValueError as exc:
        return _err(str(exc))

    payload = request.data.copy()
    payload.pop("context", None)
    payload.pop("tags", None)
    payload["user"] = request.user.pk
    serializer = ProjectSerializer(data=payload)
    if serializer.is_valid():
        with transaction.atomic():
            project = serializer.save(user=request.user)
            if has_context:
                project.context = context
                project.save(update_fields=["context"])
            if has_tags:
                tags = _resolve_tag_names(request.user, request.data.get("tags"))
                project.tags.set(tags)

        response_payload = serializer.data
        if has_context or has_tags:
            response_payload["context"] = project.context.name if project.context else None
            response_payload["tags"] = [tag.name for tag in project.tags.all()]
        return Response(response_payload)
    return Response(serializer.errors, status=400)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def update_project_metadata(request):
    """Update a project's description, context, and tags without renaming it."""
    compact = _compact(request)
    data = request.data
    disallowed = {"name", "status"}.intersection(data.keys())
    if disallowed:
        return _err(
            f"Use the dedicated endpoint to change {', '.join(sorted(disallowed))}."
        )
    if "project" not in data:
        return _err("Missing 'project'.")
    if not {"description", "context", "tags"}.intersection(data.keys()):
        return _err("Provide at least one of: description, context, tags.")

    try:
        project_name = _clean_required_name(data.get("project"), "project")
    except ValueError as exc:
        return _err(str(exc))
    project = Projects.objects.filter(
        user=request.user, name__iexact=project_name
    ).first()
    if not project:
        return _err("Project not found.", status.HTTP_404_NOT_FOUND)

    fields_to_save = []
    try:
        if "description" in data:
            project.description = _clean_optional_text(
                data.get("description"), "description", allow_null=True
            )
            fields_to_save.append("description")
        if "context" in data:
            context_value = data.get("context")
            if context_value is None or (
                isinstance(context_value, str) and not context_value.strip()
            ):
                project.context = None
            else:
                project.context = _resolve_context_name(request.user, context_value)
            fields_to_save.append("context")
        if "tags" in data:
            tags = _resolve_tag_names(request.user, data.get("tags"))
        else:
            tags = None
    except ValueError as exc:
        return _err(str(exc))

    if fields_to_save:
        # Projects.save() assigns the user's General context when context is None.
        # Preserve a deliberately cleared context even when this PATCH also updates
        # another metadata field.
        if project.context_id is None:
            Projects.objects.filter(pk=project.pk).update(
                **{field: getattr(project, field) for field in fields_to_save}
            )
        else:
            project.save(update_fields=fields_to_save)
    if tags is not None:
        project.tags.set(tags)
    return Response(_json_ok({"project": _serialize_project_metadata(project, compact)}, compact))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_projects(request):
    qp = request.query_params
    if "start_date" in qp and "end_date" in qp:
        start = qp["start_date"]
        end = qp["end_date"]
        projects_qs = Projects.objects.filter(user=request.user)
        projects_qs = filter_by_active_context(
            projects_qs, request, override_context_id=qp.get("context")
        )
        projects = in_window(projects_qs, start, end)
        serializer = ProjectSerializer(projects, many=True)
        return Response(serializer.data)
    elif "start_date" in qp:
        start = qp["start_date"]
        projects_qs = Projects.objects.filter(user=request.user)
        projects_qs = filter_by_active_context(
            projects_qs, request, override_context_id=qp.get("context")
        )
        projects = in_window(projects_qs, start)
        serializer = ProjectSerializer(projects, many=True)
        return Response(serializer.data)

    projects = Projects.objects.filter(user=request.user)
    projects = filter_by_active_context(
        projects, request, override_context_id=qp.get("context")
    )
    serializer = ProjectSerializer(projects, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tally_by_sessions(request):
    sessions = Sessions.objects.filter(is_active=False, user=request.user)
    project = request.query_params.get("project_name")
    if project:
        sessions = sessions.filter(project__name__iexact=project)
    sessions = filter_by_active_context(
        sessions, request, override_context_id=request.query_params.get("context")
    )
    sessions = _apply_tag_filters(
        request.query_params, sessions, kind="sessions", user=request.user
    )
    sessions = filter_sessions_by_params(request, sessions)
    project_durations = tally_project_durations(sessions)
    return Response(project_durations)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tally_by_subprojects(request):
    sessions = Sessions.objects.filter(is_active=False, user=request.user)
    project = request.query_params.get("project_name")
    if project:
        sessions = sessions.filter(project__name__iexact=project)
    sessions = filter_by_active_context(
        sessions, request, override_context_id=request.query_params.get("context")
    )
    sessions = _apply_tag_filters(
        request.query_params, sessions, kind="sessions", user=request.user
    )
    sessions = filter_sessions_by_params(request, sessions)

    sub_durations = {}
    for s in sessions:
        dur = s.duration or 0
        subs = list(s.subprojects.all())
        if subs:
            for sub in subs:
                sub_durations.setdefault(sub.name, 0)
                sub_durations[sub.name] += dur
        else:
            sub_durations.setdefault("no subproject", 0)
            sub_durations["no subproject"] += dur

    payload = [{"name": n, "total_time": t} for n, t in sub_durations.items()]
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tally_by_context(request):
    """Aggregate time by context."""
    sessions = Sessions.objects.filter(is_active=False, user=request.user)
    sessions = filter_sessions_by_params(request, sessions)

    context_durations = {}
    for s in sessions:
        dur = s.duration or 0
        context_name = s.project.context.name if s.project.context else "General"
        context_durations.setdefault(context_name, 0)
        context_durations[context_name] += dur

    payload = [{"name": n, "total_time": t} for n, t in context_durations.items()]
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tally_by_status(request):
    """Aggregate project count and time by status."""
    user = request.user
    projects = Projects.objects.filter(user=user)

    # Apply context filter if provided
    context_id = request.query_params.get("context")
    if context_id:
        projects = projects.filter(context_id=context_id)

    # Apply tag filters to projects
    projects = _apply_tag_filters(
        request.query_params, projects, kind="projects", user=user
    )

    # Apply exclude filter (by ID from web UI)
    exclude_ids = request.query_params.getlist("exclude_projects")
    if exclude_ids:
        projects = projects.exclude(id__in=exclude_ids)

    # Filter sessions by date range and other params to calculate accurate totals
    sessions = Sessions.objects.filter(is_active=False, user=user)
    sessions = filter_sessions_by_params(request, sessions)

    # Build project time lookup from filtered sessions
    project_times = {}
    for s in sessions:
        pid = s.project_id
        dur = s.duration or 0
        project_times[pid] = project_times.get(pid, 0) + dur

    # Aggregate by status using filtered session times
    status_data = {}
    for p in projects:
        st = p.status
        if st not in status_data:
            status_data[st] = {"status": st, "count": 0, "total_time": 0}
        status_data[st]["count"] += 1
        # Use filtered session time instead of stored total
        status_data[st]["total_time"] += project_times.get(p.id, 0)

    payload = list(status_data.values())
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tally_by_tags(request):
    """Aggregate time by tag."""
    user = request.user

    # Filter sessions by date range, context, and other params
    sessions = Sessions.objects.filter(is_active=False, user=user)
    sessions = filter_sessions_by_params(request, sessions)

    # Build tag stats from filtered sessions
    tag_stats = {}  # tag_id -> {total_time, project_ids}
    for s in sessions:
        dur = s.duration or 0
        pid = s.project_id
        # Get tags for this session's project
        project_tags = s.project.tags.all()
        for tag in project_tags:
            if tag.id not in tag_stats:
                tag_stats[tag.id] = {"total_time": 0, "project_ids": set()}
            tag_stats[tag.id]["total_time"] += dur
            tag_stats[tag.id]["project_ids"].add(pid)

    # Get tag objects for the ones that have data
    tags = Tag.objects.filter(user=user, id__in=tag_stats.keys())

    payload = [
        {
            "name": t.name,
            "tag_id": t.id,
            "total_time": tag_stats[t.id]["total_time"],
            "project_count": len(tag_stats[t.id]["project_ids"]),
            "color": t.color or None
        }
        for t in tags
    ]
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def hierarchy_data(request):
    """Return hierarchical Context -> Project -> SubProject structure with times."""
    from django.db.models import Sum

    user = request.user
    contexts = Context.objects.filter(user=user)

    # Apply context filter if provided
    context_id = request.query_params.get("context")
    if context_id:
        contexts = contexts.filter(id=context_id)

    # Apply date filters to sessions for time calculation
    sessions = Sessions.objects.filter(is_active=False, user=user)
    sessions = filter_sessions_by_params(request, sessions)

    # Build session duration lookup by project and subproject
    project_times = {}
    subproject_times = {}
    for s in sessions:
        dur = s.duration or 0
        pid = s.project_id
        project_times[pid] = project_times.get(pid, 0) + dur
        for sub in s.subprojects.all():
            subproject_times[sub.id] = subproject_times.get(sub.id, 0) + dur

    hierarchy = {
        "name": "All",
        "children": []
    }

    for ctx in contexts:
        ctx_children = []
        ctx_projects = Projects.objects.filter(user=user, context=ctx)

        # Apply tag filters to projects
        ctx_projects = _apply_tag_filters(
            request.query_params, ctx_projects, kind="projects", user=user
        )

        # Apply exclude filter (by ID from web UI)
        exclude_ids = request.query_params.getlist("exclude_projects")
        if exclude_ids:
            ctx_projects = ctx_projects.exclude(id__in=exclude_ids)

        for proj in ctx_projects:
            proj_time = project_times.get(proj.id, 0)
            if proj_time == 0:
                continue  # Skip projects with no time in range

            proj_children = []
            for sub in proj.subprojects.all():
                sub_time = subproject_times.get(sub.id, 0)
                if sub_time > 0:
                    proj_children.append({
                        "name": sub.name,
                        "subproject_id": sub.id,
                        "total_time": sub_time
                    })

            ctx_children.append({
                "name": proj.name,
                "project_id": proj.id,
                "total_time": proj_time,
                "children": proj_children
            })

        if ctx_children:
            hierarchy["children"].append({
                "name": ctx.name,
                "context_id": ctx.id,
                "children": ctx_children
            })

    return Response(hierarchy)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def projects_with_stats(request):
    """Return projects with additional stats for radar chart."""
    from django.utils import timezone

    user = request.user
    projects = Projects.objects.filter(user=user)

    # Apply context filter if provided
    context_id = request.query_params.get("context")
    if context_id:
        projects = projects.filter(context_id=context_id)

    # Apply tag filters
    projects = _apply_tag_filters(
        request.query_params, projects, kind="projects", user=user
    )

    # Apply exclude filter (by ID from web UI)
    exclude_ids = request.query_params.getlist("exclude_projects")
    if exclude_ids:
        projects = projects.exclude(id__in=exclude_ids)

    # Filter sessions by date range and other params
    sessions = Sessions.objects.filter(is_active=False, user=user)
    sessions = filter_sessions_by_params(request, sessions)

    # Build project stats lookup from filtered sessions
    project_stats = {}
    for s in sessions:
        pid = s.project_id
        dur = s.duration or 0
        if pid not in project_stats:
            project_stats[pid] = {"total_time": 0, "session_count": 0}
        project_stats[pid]["total_time"] += dur
        project_stats[pid]["session_count"] += 1

    now = timezone.now()
    payload = []
    for p in projects:
        stats = project_stats.get(p.id, {"total_time": 0, "session_count": 0})
        subproject_count = p.subprojects.count()
        days_since_update = (now - p.last_updated).days if p.last_updated else 999

        payload.append({
            "name": p.name,
            "total_time": stats["total_time"],
            "computed_total_time": stats["total_time"],
            "persisted_total_time": p.total_time,
            "session_count": stats["session_count"],
            "subproject_count": subproject_count,
            "days_since_update": days_since_update,
            "status": p.status
        })

    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search_projects(request):
    term = request.query_params.get("search_term", "")
    if "status" in request.query_params:
        st = request.query_params["status"]
        projects = Projects.objects.filter(
            name__icontains=term, status=st, user=request.user
        )
    else:
        projects = Projects.objects.filter(name__icontains=term, user=request.user)
    serializer = ProjectSerializer(projects, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_project(request, project_name):
    project = get_object_or_404(Projects, name=project_name, user=request.user)
    serializer = ProjectSerializer(project)
    return Response(serializer.data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_project(request, project_name):
    project = get_object_or_404(Projects, name=project_name, user=request.user)
    project.delete()
    return Response(status=204)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_subproject(request):
    parent_raw = request.data.get("parent_project")
    if not parent_raw:
        return _err("Missing 'parent_project'")

    parent_project = None
    if isinstance(parent_raw, int) or (
        isinstance(parent_raw, str) and parent_raw.isdigit()
    ):
        parent_project = Projects.objects.filter(
            pk=int(parent_raw), user=request.user
        ).first()
    else:
        parent_project = Projects.objects.filter(
            name=str(parent_raw), user=request.user
        ).first()

    if parent_project is None:
        return Response(
            {"error": f"Parent project {parent_raw} does not exist"}, status=400
        )

    payload = request.data.copy()
    payload["parent_project"] = parent_project.pk
    payload["user"] = request.user.pk
    serializer = SubProjectSerializer(data=payload)
    if serializer.is_valid():
        serializer.save(user=request.user, parent_project=parent_project)
        return Response(serializer.data)
    return Response(serializer.errors, status=400)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_subprojects(request, **kwargs):
    project_name = request.query_params.get("project_name") or kwargs.get(
        "project_name"
    )
    subprojects = SubProjects.objects.filter(
        parent_project__name=project_name, user=request.user
    )
    serializer = SubProjectSerializer(subprojects, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search_subprojects(request):
    parent_project = (
        request.query_params.get("project_name")
        or request.query_params.get("project")
    )
    if not parent_project:
        return _err("Missing 'project_name' or 'project'")
    search_term = request.query_params.get("search_term", "")
    subprojects = SubProjects.objects.filter(
        parent_project__name=parent_project,
        name__icontains=search_term,
        user=request.user,
    )
    if not subprojects.exists():
        subprojects = SubProjects.objects.filter(
            parent_project__name=parent_project, user=request.user
        )
    serializer = SubProjectSerializer(subprojects, many=True)
    return Response(serializer.data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_subproject(request, project_name, subproject_name):
    subproject = get_object_or_404(
        SubProjects,
        name=subproject_name,
        parent_project__name=project_name,
        user=request.user,
    )
    subproject.delete()
    return Response(status=204)


# Back-compat shims (mapping to new compact endpoints)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_session(request):
    # delegate to timer_start
    return timer_start(request)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def restart_session(request):
    # delegate to timer_restart
    return timer_restart(request)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def end_session(request):
    # delegate to timer_stop
    return timer_stop(request)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def log_session(request):
    # delegate to track_session
    return track_session(request)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_session(request, session_id):
    try:
        session_id = int(session_id)
    except (TypeError, ValueError):
        return _err("Invalid session id", status.HTTP_400_BAD_REQUEST)
    if session_id <= 0:
        return _err("Session not found", status.HTTP_404_NOT_FOUND)

    sess = Sessions.objects.filter(pk=session_id, user=request.user).first()
    if not sess:
        return _err("Session not found", status.HTTP_404_NOT_FOUND)
    ledger_delete_session(sess.pk, user=request.user)
    return Response(status=204)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def edit_session(request, session_id):
    """
    Edit an existing completed session in place, preserving its ID.

    JSON body (all optional, only provided fields are updated):
      - project: str (project name to reassign session to)
      - subprojects: [str] (list of subproject names)
      - start: str (ISO timestamp)
      - end: str (ISO timestamp)
      - note: str

    Query params:
      - compact: true/false (default true)

    Returns the updated session object with the same ID.
    """
    compact = _compact(request)
    try:
        session_id = int(session_id)
    except (TypeError, ValueError):
        return _err("Invalid session id", status.HTTP_400_BAD_REQUEST)
    if session_id <= 0:
        return _err("Session not found", status.HTTP_404_NOT_FOUND)

    current_session = (
        Sessions.objects.select_for_update()
        .filter(pk=session_id, user=request.user)
        .first()
    )
    if not current_session:
        return _err("Session not found", status.HTTP_404_NOT_FOUND)

    # Only allow editing completed sessions
    if current_session.is_active:
        return _err("Cannot edit active sessions. Stop the timer first.")

    # Collect current values as defaults
    project = current_session.project
    start_time = current_session.start_time
    end_time = current_session.end_time
    note = current_session.note
    current_subs = list(current_session.subprojects.all())

    # Apply updates from request body
    data = request.data

    # Update project if provided
    if "project" in data and data["project"]:
        project = Projects.objects.filter(
            name=data["project"], user=request.user
        ).first()
        if not project:
            return _err("Project not found", status.HTTP_404_NOT_FOUND)

    # Update start/end times if provided
    if "start" in data and data["start"]:
        try:
            start_time = parse_date_or_datetime(data["start"])
            if timezone.is_naive(start_time):
                start_time = timezone.make_aware(start_time)
        except Exception as e:
            return _err(f"Invalid start time: {e}")

    if "end" in data and data["end"]:
        try:
            end_time = parse_date_or_datetime(data["end"])
            if timezone.is_naive(end_time):
                end_time = timezone.make_aware(end_time)
        except Exception as e:
            return _err(f"Invalid end time: {e}")

    # Validate times
    if end_time and start_time and end_time < start_time:
        return _err("End time cannot be earlier than start time")

    # Update note if provided (allow empty string to clear note)
    if "note" in data:
        note = data["note"] if data["note"] else None

    # Resolve subprojects if provided
    sub_qs = None
    if "subprojects" in data:
        subs = _coerce_list(data.get("subprojects"))
        if subs:
            sub_qs = SubProjects.objects.filter(
                parent_project=project, user=request.user, name__in=subs
            )
            if sub_qs.count() != len(set([s.lower() for s in subs])):
                existing = set(sp.name.lower() for sp in sub_qs)
                missing = [s for s in subs if s.lower() not in existing]
                return _err(f"Unknown subprojects: {', '.join(missing)}")
        else:
            sub_qs = SubProjects.objects.none()

    # Resolve the final subproject set before changing the existing row.
    if sub_qs is not None:
        final_subprojects = list(sub_qs)
    else:
        # Keep existing subprojects (filtering to those valid for the new project)
        final_subprojects = [
            sp for sp in current_subs if sp.parent_project_id == project.id
        ]

    current_session = ledger_mutate_session(
        current_session.pk,
        user=request.user,
        project=project,
        subprojects=final_subprojects,
        start_time=start_time,
        end_time=end_time,
        note=note,
        is_active=False,
    )

    return Response(
        _json_ok({"session": _serialize_session(current_session, compact)}, compact),
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_sessions(request):
    sessions = Sessions.objects.filter(is_active=False, user=request.user)
    sessions = filter_by_active_context(
        sessions, request, override_context_id=request.query_params.get("context")
    )
    sessions = _apply_tag_filters(
        request.query_params, sessions, kind="sessions", user=request.user
    )
    sessions = _apply_exclude_filters(
        request.query_params, sessions, kind="sessions", user=request.user
    )
    sessions = filter_sessions_by_params(request, sessions)
    serializer = SessionSerializer(sessions, many=True)
    # to_representation already compacts project/subprojects as names
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_active_sessions(request):
    stop_expired_timers(request.user)
    sessions = Sessions.objects.filter(is_active=True, user=request.user)
    sessions = filter_by_active_context(
        sessions, request, override_context_id=request.query_params.get("context")
    )
    serializer = SessionSerializer(sessions, many=True)
    return Response(serializer.data)


# Needed by list_projects
def in_window(data, start=None, end=None):
    from .utils import in_window as _inw

    return _inw(data, start, end)


def _apply_tag_filters(qp, qs, *, kind: str, user=None):
    """Apply tag filtering from query params.

    Query param: tags="a,b" or tags=["a","b"]

    kind:
      - "projects": expects Projects queryset
      - "sessions": expects Sessions queryset (filters via project__tags)
    """
    try:
        tags = _coerce_list(qp.get("tags"))
    except Exception:
        tags = []

    if not tags:
        return qs

    # Ensure tags belong to the same user (avoid leaking tag names across users)
    # This also normalizes case by using iexact matches if needed.
    if user is not None:
        tags = list(
            Tag.objects.filter(user=user, name__in=tags).values_list("name", flat=True)
        )

    if not tags:
        return qs

    if kind == "projects":
        return qs.filter(tags__name__in=tags).distinct()
    if kind == "sessions":
        return qs.filter(project__tags__name__in=tags).distinct()

    return qs


def _apply_exclude_filters(qp, qs, *, kind: str, user=None):
    """Exclude projects by name from query params.

    Query param: exclude="ProjectA,ProjectB" or exclude=["ProjectA","ProjectB"]

    kind:
      - "projects": expects Projects queryset
      - "sessions": expects Sessions queryset (excludes via project__name)
    """
    try:
        names = _coerce_list(qp.get("exclude"))
    except Exception:
        names = []

    if not names:
        return qs

    if user is not None:
        names = list(
            Projects.objects.filter(user=user, name__in=names).values_list("name", flat=True)
        )

    if not names:
        return qs

    if kind == "projects":
        return qs.exclude(name__in=names)
    if kind == "sessions":
        return qs.exclude(project__name__in=names)

    return qs


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def merge_projects_api(request):
    """
    API endpoint to merge two projects into one new project.
    Moves all sessions and subprojects from both projects to the new merged project.
    """
    project1_name = request.data.get("project1")
    project2_name = request.data.get("project2")
    new_project_name = request.data.get("new_project_name")

    if not all([project1_name, project2_name, new_project_name]):
        return Response(
            {"error": "project1, project2, and new_project_name are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if project1_name == project2_name:
        return Response(
            {"error": "Cannot merge a project with itself"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Get the projects to merge
        project1 = get_object_or_404(Projects, name=project1_name, user=request.user)
        project2 = get_object_or_404(Projects, name=project2_name, user=request.user)

        # Check if new project name already exists
        if Projects.objects.filter(user=request.user, name=new_project_name).exists():
            return Response(
                {"error": f'Project with name "{new_project_name}" already exists'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create merged description
        merged_description = f"Merged from '{project1.name}' and '{project2.name}'\n\n"

        if project1.description:
            merged_description += (
                f"--- {project1.name} Description ---\n{project1.description}\n\n"
            )

        if project2.description:
            merged_description += (
                f"--- {project2.name} Description ---\n{project2.description}\n\n"
            )

        # Remove trailing newlines
        merged_description = merged_description.strip()

        # Create the new merged project
        merged_project = Projects.objects.create(
            user=request.user,
            name=new_project_name,
            start_date=min(project1.start_date, project2.start_date),
            last_updated=max(project1.last_updated, project2.last_updated),
            total_time=0.0,  # Will be calculated by audit function
            status="active",  # Default to active
            description=merged_description,
        )

        # Move all sessions from both projects to the merged project
        project1_sessions = project1.sessions.all()
        project2_sessions = project2.sessions.all()

        for session in project1_sessions:
            session.project = merged_project
            session.save()

        for session in project2_sessions:
            session.project = merged_project
            session.save()

        # Move all subprojects from both projects to the merged project
        # Handle potential name conflicts by renaming duplicates
        project1_subprojects = list(project1.subprojects.all())
        project2_subprojects = list(project2.subprojects.all())

        # Get existing subproject names in the merged project
        existing_subproject_names = set()

        # First, move all subprojects from project1
        for subproject in project1_subprojects:
            original_name = subproject.name
            new_name = original_name

            # If name conflict exists, append project name to make it unique
            if new_name in existing_subproject_names:
                new_name = f"{original_name} ({project1.name})"
                counter = 1
                while new_name in existing_subproject_names:
                    new_name = f"{original_name} ({project1.name}) {counter}"
                    counter += 1

            subproject.name = new_name
            subproject.parent_project = merged_project
            subproject.save()
            existing_subproject_names.add(new_name)

        # Then, move all subprojects from project2
        for subproject in project2_subprojects:
            original_name = subproject.name
            new_name = original_name

            # If name conflict exists, append project name to make it unique
            if new_name in existing_subproject_names:
                new_name = f"{original_name} ({project2.name})"
                counter = 1
                while new_name in existing_subproject_names:
                    new_name = f"{original_name} ({project2.name}) {counter}"
                    counter += 1

            subproject.name = new_name
            subproject.parent_project = merged_project
            subproject.save()
            existing_subproject_names.add(new_name)

        # Audit total time for the merged project and all its subprojects
        merged_project.audit_total_time(log=False)
        for subproject in merged_project.subprojects.all():
            subproject.audit_total_time(log=False)

        # Delete the original projects
        project1.delete()
        project2.delete()

        # Serialize and return the merged project
        serializer = ProjectSerializer(merged_project)
        return Response(
            {
                "message": f'Successfully merged "{project1_name}" and "{project2_name}" into "{new_project_name}"',
                "project": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )

    except Exception as e:
        return Response(
            {"error": f"An error occurred while merging projects: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def merge_subprojects_api(request):
    """
    API endpoint to merge two subprojects into one new subproject.
    Moves all sessions from both subprojects to the new merged subproject.
    """
    subproject1_name = request.data.get("subproject1")
    subproject2_name = request.data.get("subproject2")
    new_subproject_name = request.data.get("new_subproject_name")
    project_id = request.data.get("project_id")

    if not all([subproject1_name, subproject2_name, new_subproject_name, project_id]):
        return Response(
            {
                "error": "subproject1, subproject2, new_subproject_name, and project_id are required"
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if subproject1_name == subproject2_name:
        return Response(
            {"error": "Cannot merge a subproject with itself"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Get the parent project
        parent_project = get_object_or_404(Projects, id=project_id, user=request.user)

        # Get the subprojects to merge (must belong to the same parent project)
        subproject1 = get_object_or_404(
            SubProjects,
            name=subproject1_name,
            parent_project=parent_project,
            user=request.user,
        )
        subproject2 = get_object_or_404(
            SubProjects,
            name=subproject2_name,
            parent_project=parent_project,
            user=request.user,
        )

        # Check if new subproject name already exists in the same project
        if SubProjects.objects.filter(
            user=request.user, name=new_subproject_name, parent_project=parent_project
        ).exists():
            return Response(
                {
                    "error": f'Subproject with name "{new_subproject_name}" already exists in this project'
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create merged description
        merged_description = (
            f"Merged from '{subproject1.name}' and '{subproject2.name}'\n\n"
        )

        if subproject1.description:
            merged_description += (
                f"--- {subproject1.name} Description ---\n{subproject1.description}\n\n"
            )

        if subproject2.description:
            merged_description += (
                f"--- {subproject2.name} Description ---\n{subproject2.description}\n\n"
            )

        # Remove trailing newlines
        merged_description = merged_description.strip()

        # Create the new merged subproject
        merged_subproject = SubProjects.objects.create(
            user=request.user,
            name=new_subproject_name,
            parent_project=parent_project,
            start_date=min(subproject1.start_date, subproject2.start_date),
            last_updated=max(subproject1.last_updated, subproject2.last_updated),
            total_time=0.0,  # Will be calculated by audit function
            description=merged_description,
        )

        # Move all sessions from both subprojects to the merged subproject
        subproject1_sessions = subproject1.sessions.all()
        subproject2_sessions = subproject2.sessions.all()

        for session in subproject1_sessions:
            session.subprojects.remove(subproject1)
            session.subprojects.add(merged_subproject)

        for session in subproject2_sessions:
            session.subprojects.remove(subproject2)
            session.subprojects.add(merged_subproject)

        # Audit total time for the merged subproject
        merged_subproject.audit_total_time(log=False)

        # Delete the original subprojects
        subproject1.delete()
        subproject2.delete()

        # Serialize and return the merged subproject
        serializer = SubProjectSerializer(merged_subproject)
        return Response(
            {
                "message": f'Successfully merged "{subproject1_name}" and "{subproject2_name}" into "{new_subproject_name}"',
                "subproject": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )

    except Exception as e:
        return Response(
            {"error": f"An error occurred while merging subprojects: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def export_json_api(request):
    """Export sessions/projects as JSON (API form of the export page).

    Accepts filters via either query params (GET) or JSON body (POST):
      - project_name: str (icontains)
      - start_date: YYYY-MM-DD (inclusive)
      - end_date:   YYYY-MM-DD (inclusive)
      - context: context id
      - tags: list of tag ids (or comma-separated string)
      - compress: bool (wrap with json_compress)
      - autumn_compatible: bool (CLI compatibility format)

    Returns JSON data (not a file download).
    """
    compact = _compact(request)

    # Read from query params for GET, body for POST (but allow either in both)
    qp = getattr(request, "query_params", request.GET)
    data = {}
    try:
        if hasattr(request, "data") and isinstance(request.data, dict):
            data = request.data
    except Exception:
        data = {}

    def _get(key, default=None):
        if key in data and data.get(key) not in (None, ""):
            return data.get(key)
        return qp.get(key, default)

    project_name = (_get("project_name") or _get("project") or "").strip()
    start_date_s = (_get("start_date") or "").strip()
    end_date_s = (_get("end_date") or "").strip()
    context_id = _get("context")
    tag_ids_raw = _get("tags") or _get("tag_ids")

    compress = _bool(_get("compress"), False)
    autumn_compatible = _bool(_get("autumn_compatible"), False)

    # Parse dates (date-only, inclusive like export_view)
    start_dt = None
    end_dt = None
    if start_date_s:
        try:
            d = parse_date_or_datetime(start_date_s)
            if isinstance(d, datetime):
                d = d.date()
            start_dt = timezone.make_aware(datetime.combine(d, time.min))
        except Exception:
            return _err("Invalid start_date; expected YYYY-MM-DD")

    if end_date_s:
        try:
            d = parse_date_or_datetime(end_date_s)
            if isinstance(d, datetime):
                d = d.date()
            end_dt = timezone.make_aware(datetime.combine(d, time.max))
        except Exception:
            return _err("Invalid end_date; expected YYYY-MM-DD")

    qs = Sessions.objects.filter(is_active=False, user=request.user)

    if project_name:
        qs = qs.filter(project__name__icontains=project_name)
    if start_dt is not None:
        qs = qs.filter(end_time__gte=start_dt)
    if end_dt is not None:
        qs = qs.filter(end_time__lte=end_dt)

    if context_id:
        try:
            qs = qs.filter(project__context__id=int(context_id))
        except (TypeError, ValueError):
            # ignore invalid context
            pass

    tag_ids = _coerce_list(tag_ids_raw)
    # Allow comma-separated string, or repeated query params like ?tags=1&tags=2
    if isinstance(tag_ids_raw, str):
        tag_ids = _coerce_list(tag_ids_raw)

    # If query params had repeated tags=, _get() only returns first; handle manually.
    if not tag_ids and hasattr(qp, "getlist"):
        tag_ids = qp.getlist("tags")

    try:
        tag_ids = [int(t) for t in tag_ids if str(t).strip()]
    except ValueError:
        tag_ids = []

    if tag_ids:
        qs = qs.filter(project__tags__id__in=tag_ids).distinct()

    qs = qs.select_related("project", "project__context").prefetch_related(
        "subprojects",
        "project__tags",
    )

    export_dict = build_project_json_from_sessions(qs, autumn_compatible)
    payload = json_compress(export_dict) if compress else export_dict

    # API should return JSON object (not string)
    return Response(payload, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def import_json_api(request):
    """Import project/session JSON produced by :func:`export_json_api`."""
    try:
        body = request.data
    except Exception:
        return _err("Invalid JSON request body.")

    if not isinstance(body, dict):
        return _err("JSON request body must be an object.")

    has_data = "data" in body
    has_compressed = "data_compressed" in body
    if has_data == has_compressed:
        return _err("Provide exactly one of data or data_compressed.")

    if has_compressed:
        compressed = body.get("data_compressed")
        if not isinstance(compressed, (str, dict)):
            return _err("data_compressed must be a compressed JSON string.")
        try:
            compressed_data = json.loads(compressed) if isinstance(compressed, str) else compressed
            zipjson_key = "base64(zip(o))"
            if (
                not isinstance(compressed_data, dict)
                or set(compressed_data) != {zipjson_key}
                or not compressed_data[zipjson_key]
            ):
                raise ValueError
            import_data = json_decompress(compressed_data)
        except Exception:
            return _err("Could not decompress data_compressed.")
    else:
        import_data = body.get("data")

    if not isinstance(import_data, dict):
        return _err("Import data must be an object.")

    tolerance = body.get("tolerance", 2)
    if isinstance(tolerance, bool) or not isinstance(tolerance, int):
        return _err("tolerance must be an integer number of minutes.")
    if tolerance < 0:
        return _err("tolerance must be zero or greater.")

    import_into_context = None
    context_name = body.get("context")
    if context_name is not None:
        if not isinstance(context_name, str):
            return _err("context must be a context name.")
        context_name = context_name.strip()
        if context_name:
            import_into_context = Context.objects.filter(
                user=request.user,
                name__iexact=context_name,
            ).first()
            if import_into_context is None:
                import_into_context = Context.objects.create(
                    user=request.user,
                    name=context_name,
                )

    try:
        summary = run_import(
            request.user,
            import_data,
            force=_bool(body.get("force"), False),
            merge=_bool(body.get("merge"), False),
            tolerance=tolerance,
            autumn_import=_bool(body.get("autumn_import"), False),
            import_into_context=import_into_context,
        )
    except Exception as exc:
        return _err(f"Invalid import data: {exc}")

    return Response(_json_ok({"summary": summary}), status=status.HTTP_200_OK)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def contexts_list(request):
    """List contexts for the authenticated user.

    Query params:
      - compact=true|false (default true)

    Returns (compact):
      {"count": int, "contexts": [{"id": int, "name": str}]}
    Returns (full):
      {"count": int, "contexts": [{"id", "name", "description", "project_count",
                                   "session_count", "total_minutes", "avg_session_minutes"}]}
    """
    compact = _compact(request)
    if request.method == "POST":
        try:
            name = _clean_required_name(request.data.get("name"), "name")
            description = (
                _clean_optional_text(request.data.get("description"), "description")
                if "description" in request.data
                else None
            )
        except ValueError as exc:
            return _err(str(exc))
        if Context.objects.filter(user=request.user, name__iexact=name).exists():
            return _err("You already have a context with this name.")
        context = Context.objects.create(
            user=request.user, name=name, description=description
        )
        return Response(
            _json_ok(
                {"context": _serialize_context_for_api(context, request.user, compact)},
                compact,
            ),
            status=status.HTTP_201_CREATED,
        )

    qs = request.user.contexts.all().order_by("name")

    if compact:
        payload = [{"id": c.id, "name": c.name} for c in qs]
    else:
        payload = []
        for c in qs:
            project_count = c.projects.count()
            # Get all completed sessions for projects in this context
            sessions = Sessions.objects.filter(
                user=request.user,
                project__context=c,
                is_active=False,
            )
            session_count = sessions.count()
            total_minutes = sum(s.duration or 0 for s in sessions)
            avg_session_minutes = (
                round(total_minutes / session_count, 2) if session_count > 0 else 0.0
            )
            payload.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "description": c.description or "",
                    "project_count": project_count,
                    "session_count": session_count,
                    "total_minutes": round(total_minutes, 2),
                    "avg_session_minutes": avg_session_minutes,
                }
            )

    return Response({"count": len(payload), "contexts": payload})


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def context_detail(request, context_id):
    context = Context.objects.filter(user=request.user, pk=context_id).first()
    if not context:
        return _err("Context not found.", status.HTTP_404_NOT_FOUND)
    if request.method == "DELETE":
        context.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    data = request.data
    if not {"name", "description"}.intersection(data.keys()):
        return _err("Provide at least one of: name, description.")
    try:
        if "name" in data:
            name = _clean_required_name(data.get("name"), "name")
            if Context.objects.filter(user=request.user, name__iexact=name).exclude(
                pk=context.pk
            ).exists():
                return _err("You already have a context with this name.")
            context.name = name
        if "description" in data:
            context.description = _clean_optional_text(
                data.get("description"), "description"
            )
    except ValueError as exc:
        return _err(str(exc))
    context.save()
    compact = _compact(request)
    return Response(
        _json_ok(
            {"context": _serialize_context_for_api(context, request.user, compact)},
            compact,
        )
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def tags_list(request):
    """List tags for the authenticated user.

    Query params:
      - compact=true|false (default true)

    Returns (compact):
      {"count": int, "tags": [{"id": int, "name": str}]}
    Returns (full):
      {"count": int, "tags": [{"id", "name", "color", "project_count",
                              "session_count", "total_minutes", "avg_session_minutes"}]}
    """
    compact = _compact(request)
    if request.method == "POST":
        try:
            name = _clean_required_name(request.data.get("name"), "name")
            color = (
                _clean_optional_text(
                    request.data.get("color"), "color", max_length=20
                )
                if "color" in request.data
                else None
            )
        except ValueError as exc:
            return _err(str(exc))
        if Tag.objects.filter(user=request.user, name__iexact=name).exists():
            return _err("You already have a tag with this name.")
        tag = Tag.objects.create(user=request.user, name=name, color=color)
        return Response(
            _json_ok({"tag": _serialize_tag_for_api(tag, request.user, compact)}, compact),
            status=status.HTTP_201_CREATED,
        )

    qs = request.user.tags.all().order_by("name")

    if compact:
        payload = [{"id": t.id, "name": t.name} for t in qs]
    else:
        payload = []
        for t in qs:
            project_count = t.projects.filter(user=request.user).count()
            # Get all completed sessions for projects with this tag
            sessions = Sessions.objects.filter(
                user=request.user,
                project__tags=t,
                is_active=False,
            )
            session_count = sessions.count()
            total_minutes = sum(s.duration or 0 for s in sessions)
            avg_session_minutes = (
                round(total_minutes / session_count, 2) if session_count > 0 else 0.0
            )
            payload.append(
                {
                    "id": t.id,
                    "name": t.name,
                    "color": t.color or "",
                    "project_count": project_count,
                    "session_count": session_count,
                    "total_minutes": round(total_minutes, 2),
                    "avg_session_minutes": avg_session_minutes,
                }
            )

    return Response({"count": len(payload), "tags": payload})


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def tag_detail(request, tag_id):
    tag = Tag.objects.filter(user=request.user, pk=tag_id).first()
    if not tag:
        return _err("Tag not found.", status.HTTP_404_NOT_FOUND)
    if request.method == "DELETE":
        tag.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    data = request.data
    if not {"name", "color"}.intersection(data.keys()):
        return _err("Provide at least one of: name, color.")
    try:
        if "name" in data:
            name = _clean_required_name(data.get("name"), "name")
            if Tag.objects.filter(user=request.user, name__iexact=name).exclude(
                pk=tag.pk
            ).exists():
                return _err("You already have a tag with this name.")
            tag.name = name
        if "color" in data:
            tag.color = _clean_optional_text(data.get("color"), "color", max_length=20)
    except ValueError as exc:
        return _err(str(exc))
    tag.save()
    compact = _compact(request)
    return Response(
        _json_ok({"tag": _serialize_tag_for_api(tag, request.user, compact)}, compact)
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def audit(request):
    """Recompute total_time for all of the user's projects and subprojects.

    Send {"dry_run": true} or ?dry_run=true to preview without persisting.
    """
    dry_run = _bool(
        request.data.get("dry_run")
        if hasattr(request, "data") and "dry_run" in request.data
        else request.query_params.get("dry_run"),
        False,
    )
    projects = Projects.objects.filter(user=request.user)

    proj_total_delta = 0.0
    proj_changed = 0
    changed_projects = []
    for p in projects:
        before = float(p.total_time or 0.0)
        after = float(
            sum(
                session.duration
                for session in p.sessions.filter(is_active=False)
                if session.duration is not None
            )
        )
        delta = after - before
        if abs(delta) > 1e-9:
            proj_changed += 1
            proj_total_delta += delta
            changed_projects.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "before": round(before, 4),
                    "after": round(after, 4),
                    "delta": round(delta, 4),
                }
            )
            if not dry_run:
                p.total_time = after
                p.save(update_fields=["total_time"])

    subprojects = SubProjects.objects.filter(user=request.user)

    sub_total_delta = 0.0
    sub_changed = 0
    changed_subprojects = []
    for sp in subprojects:
        before = float(sp.total_time or 0.0)
        after = float(
            sum(
                session.duration
                for session in sp.sessions.filter(is_active=False)
                if session.duration is not None
            )
        )
        delta = after - before
        if abs(delta) > 1e-9:
            sub_changed += 1
            sub_total_delta += delta
            changed_subprojects.append(
                {
                    "id": sp.id,
                    "name": sp.name,
                    "project_id": sp.parent_project_id,
                    "project": sp.parent_project.name,
                    "before": round(before, 4),
                    "after": round(after, 4),
                    "delta": round(delta, 4),
                }
            )
            if not dry_run:
                sp.total_time = after
                sp.save(update_fields=["total_time"])

    return Response(
        {
            "ok": True,
            "dry_run": dry_run,
            "projects": {
                "count": projects.count(),
                "changed": proj_changed,
                "delta": round(proj_total_delta, 4),
            },
            "changed_projects": changed_projects,
            "subprojects": {
                "count": subprojects.count(),
                "changed": sub_changed,
                "delta": round(sub_total_delta, 4),
            },
            "changed_subprojects": changed_subprojects,
        },
        status=200,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    """Return info about the authenticated user.

    Includes active_session_count for status indicators.
    """
    u = request.user
    active_session_count = Sessions.objects.filter(user=u, is_active=True).count()
    return Response(
        {
            "ok": True,
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "first_name": getattr(u, "first_name", "") or "",
            "last_name": getattr(u, "last_name", "") or "",
            "active_session_count": active_session_count,
        }
    )
