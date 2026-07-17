from __future__ import annotations

from copy import deepcopy
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.commitments import (
    _ensure_ledger_initialized,
    snapshot_commitment_definition,
)
from core.models import (
    Commitment,
    CommitmentAdjustment,
    CommitmentRevision,
)
from core.services.sessions import StaleVersionError
from core.utils import get_period_bounds


FILTER_FIELDS = (
    "include_projects",
    "exclude_projects",
    "include_subprojects",
    "exclude_subprojects",
    "include_contexts",
    "exclude_contexts",
    "include_tags",
    "exclude_tags",
)
TARGET_FIELDS = ("project", "subproject", "context", "tag")
RESTART_FIELDS = {
    "aggregation_type",
    *TARGET_FIELDS,
    "commitment_type",
    "period",
    "start_date",
    "timezone",
}
NEXT_BOUNDARY_FIELDS = {
    "target",
    "max_balance",
    "min_balance",
    "banking_enabled",
    *FILTER_FIELDS,
}
IMMEDIATE_FIELDS = {"active"}
ALLOWED_FIELDS = RESTART_FIELDS | NEXT_BOUNDARY_FIELDS | IMMEDIATE_FIELDS


class CommitmentRestartRequired(ValidationError):
    pass


def _profile_timezone(user) -> str:
    name = getattr(getattr(user, "profile", None), "timezone", None)
    try:
        ZoneInfo(name or settings.TIME_ZONE)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return settings.TIME_ZONE
    return name or settings.TIME_ZONE


def _normalize_changes(changes) -> dict:
    normalized = dict(changes or {})
    if "target_value" in normalized:
        if "target" in normalized:
            raise ValidationError("Specify only one of target or target_value.")
        normalized["target"] = normalized.pop("target_value")
    if "cadence" in normalized:
        if "period" in normalized:
            raise ValidationError("Specify only one of period or cadence.")
        normalized["period"] = normalized.pop("cadence")
    unknown = set(normalized) - ALLOWED_FIELDS
    if unknown:
        raise ValidationError(
            "Unknown commitment fields: " + ", ".join(sorted(unknown)) + "."
        )
    return normalized


def _objects(value):
    if value is None:
        return []
    if hasattr(value, "all"):
        return list(value.all())
    return list(value)


def _validate_owned(objects, user, field):
    for obj in objects:
        if getattr(obj, "user_id", None) != user.pk:
            raise ValidationError(f"{field} entries must belong to the same user.")


def _snapshot_filter(objects):
    return [
        {"id": obj.pk, "name": obj.name}
        for obj in sorted(objects, key=lambda obj: obj.pk)
    ]


def _next_boundary(revision, now):
    zone = ZoneInfo(revision.timezone)
    with timezone.override(zone):
        _, boundary = get_period_bounds(revision.cadence, now.astimezone(zone))
    return boundary


def _validate_balances(min_balance, max_balance):
    if min_balance > max_balance:
        raise ValidationError("Min balance cannot be greater than max balance.")
    if min_balance > 0:
        raise ValidationError("Min balance must be zero or negative.")


def _validate_target(target):
    if not isinstance(target, int) or isinstance(target, bool) or target <= 0:
        raise ValidationError("target must be a positive integer.")


class CommitmentEditService:
    @staticmethod
    @transaction.atomic
    def create(user, definition):
        definition = _normalize_changes(definition)
        now = timezone.now()
        timezone_name = definition.get("timezone", _profile_timezone(user))
        try:
            zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValidationError("timezone must be a valid IANA timezone.") from exc

        aggregation_type = definition.get("aggregation_type", "project")
        scalar = {
            "user": user,
            "aggregation_type": aggregation_type,
            "commitment_type": definition.get("commitment_type", "time"),
            "period": definition.get("period", "weekly"),
            "start_date": definition.get(
                "start_date", now.astimezone(zone).date()
            ),
            "target": definition.get("target"),
            "banking_enabled": definition.get("banking_enabled", True),
            "max_balance": definition.get("max_balance", 600),
            "min_balance": definition.get("min_balance", -600),
            "active": definition.get("active", True),
            "balance": 0,
            "generation": 1,
            "ledger_start_at": now,
            "needs_recompute": True,
            "version": 1,
        }
        for field in TARGET_FIELDS:
            scalar[field] = definition.get(field)

        commitment = Commitment(**scalar)
        _validate_target(commitment.target)
        _validate_balances(commitment.min_balance, commitment.max_balance)
        commitment.full_clean()
        commitment.save()

        for field in FILTER_FIELDS:
            values = _objects(definition.get(field, []))
            _validate_owned(values, user, field)
            getattr(commitment, field).set(values)

        snapshot = snapshot_commitment_definition(commitment)
        snapshot["timezone"] = timezone_name
        CommitmentRevision.objects.create(
            commitment=commitment,
            effective_from_instant=now,
            status=CommitmentRevision.STATUS_ACTIVE,
            **snapshot,
        )
        return commitment

    @staticmethod
    @transaction.atomic
    def edit(commitment_id, *, user, changes: dict, expected_version=None):
        changes = _normalize_changes(changes)
        commitment = Commitment.objects.select_for_update().get(
            pk=commitment_id, user=user
        )
        if expected_version is not None and commitment.version != expected_version:
            raise StaleVersionError(commitment)
        now = timezone.now()
        active_revision = _ensure_ledger_initialized(commitment, now)
        pending = commitment.revisions.filter(
            status=CommitmentRevision.STATUS_PENDING
        ).first()

        changed_restart = []
        for field in RESTART_FIELDS.intersection(changes):
            if field == "timezone":
                current = active_revision.timezone
                proposed = changes[field]
            else:
                current = getattr(commitment, field)
                proposed = changes[field]
                if field in TARGET_FIELDS:
                    current = getattr(current, "pk", None)
                    proposed = getattr(proposed, "pk", None)
            if current != proposed:
                changed_restart.append(field)

        if changes.get("active") is True and not commitment.active:
            changed_restart.append("active")

        if changed_restart:
            fields = ", ".join(sorted(changed_restart))
            raise CommitmentRestartRequired(
                f"Changing {fields} requires the restart operation."
            )

        next_changes = {}
        for field in NEXT_BOUNDARY_FIELDS.intersection(changes):
            proposed = changes[field]
            if field in FILTER_FIELDS:
                proposed = _objects(proposed)
                _validate_owned(proposed, user, field)
                current_snapshot = (
                    pending.filters_snapshot if pending else active_revision.filters_snapshot
                )
                current_ids = [
                    value.get("id") if isinstance(value, dict) else value
                    for value in current_snapshot.get(field, [])
                ]
                if current_ids != sorted(obj.pk for obj in proposed):
                    next_changes[field] = proposed
            else:
                revision_field = "target_value" if field == "target" else field
                source = pending or active_revision
                if getattr(source, revision_field) != proposed:
                    next_changes[field] = proposed

        if next_changes:
            source = pending or active_revision
            revision_values = {
                "generation": commitment.generation,
                "aggregation_type": source.aggregation_type,
                "target_id": source.target_id,
                "target_name": source.target_name,
                "filters_snapshot": deepcopy(source.filters_snapshot),
                "commitment_type": source.commitment_type,
                "cadence": source.cadence,
                "target_value": source.target_value,
                "banking_enabled": source.banking_enabled,
                "max_balance": source.max_balance,
                "min_balance": source.min_balance,
                "start_date": source.start_date,
                "timezone": source.timezone,
            }
            for field, value in next_changes.items():
                if field in FILTER_FIELDS:
                    revision_values["filters_snapshot"][field] = _snapshot_filter(value)
                elif field == "target":
                    revision_values["target_value"] = value
                else:
                    revision_values[field] = value
            _validate_balances(
                revision_values["min_balance"], revision_values["max_balance"]
            )
            _validate_target(revision_values["target_value"])
            effective_from = _next_boundary(active_revision, now)
            if pending is None:
                pending = CommitmentRevision.objects.create(
                    commitment=commitment,
                    effective_from_instant=effective_from,
                    status=CommitmentRevision.STATUS_PENDING,
                    **revision_values,
                )
            else:
                for field, value in revision_values.items():
                    setattr(pending, field, value)
                pending.effective_from_instant = effective_from
                pending.save(
                    update_fields=[*revision_values.keys(), "effective_from_instant"]
                )

        if changes.get("active") is False and commitment.active:
            commitment.active = False

        commitment.version += 1
        commitment.needs_recompute = True
        commitment.save(update_fields=["active", "version", "needs_recompute"])
        return commitment

    @staticmethod
    @transaction.atomic
    def restart(
        commitment_id,
        *,
        user,
        keep_balance: bool,
        changes: dict | None,
        expected_version=None,
    ):
        from core.commitments import recompute_commitment

        changes = _normalize_changes(changes)
        commitment = Commitment.objects.select_for_update().get(
            pk=commitment_id, user=user
        )
        if expected_version is not None and commitment.version != expected_version:
            raise StaleVersionError(commitment)
        now = timezone.now()
        prior_generation = commitment.generation
        current_revision = (
            commitment.revisions.filter(
                generation=prior_generation,
                status=CommitmentRevision.STATUS_ACTIVE,
            )
            .order_by("-effective_from_instant", "-pk")
            .first()
        )

        commitment.revisions.filter(
            status=CommitmentRevision.STATUS_PENDING
        ).delete()
        if commitment.active:
            recompute_commitment(commitment)
            commitment.refresh_from_db()

        latest_balance = (
            commitment.period_rows.filter(generation=prior_generation)
            .order_by("-period_end", "-pk")
            .values_list("balance_out", flat=True)
            .first()
        )
        if latest_balance is None:
            latest_balance = commitment.balance

        if "aggregation_type" in changes:
            new_aggregation = changes["aggregation_type"]
            for field in TARGET_FIELDS:
                if field != new_aggregation and field not in changes:
                    setattr(commitment, field, None)

        for field in (
            "aggregation_type",
            *TARGET_FIELDS,
            "commitment_type",
            "period",
            "start_date",
            "target",
            "banking_enabled",
            "max_balance",
            "min_balance",
            "active",
        ):
            if field in changes:
                setattr(commitment, field, changes[field])

        _validate_balances(commitment.min_balance, commitment.max_balance)
        _validate_target(commitment.target)
        commitment.generation = prior_generation + 1
        commitment.ledger_start_at = now
        commitment.balance = latest_balance if keep_balance else 0
        commitment.needs_recompute = True
        commitment.version += 1
        commitment.full_clean()
        commitment.save()

        for field in FILTER_FIELDS:
            if field in changes:
                values = _objects(changes[field])
                _validate_owned(values, user, field)
                getattr(commitment, field).set(values)

        timezone_name = changes.get(
            "timezone",
            current_revision.timezone if current_revision else _profile_timezone(user),
        )
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValidationError("timezone must be a valid IANA timezone.") from exc

        snapshot = snapshot_commitment_definition(commitment)
        snapshot["timezone"] = timezone_name
        CommitmentRevision.objects.create(
            commitment=commitment,
            effective_from_instant=now,
            status=CommitmentRevision.STATUS_ACTIVE,
            **snapshot,
        )

        if keep_balance:
            next_seq = (
                commitment.adjustments.order_by("-seq")
                .values_list("seq", flat=True)
                .first()
                or 0
            ) + 1
            CommitmentAdjustment.objects.create(
                commitment=commitment,
                seq=next_seq,
                kind=CommitmentAdjustment.KIND_RESTART_CARRY,
                amount=latest_balance,
                effective_at=now,
                reason="Balance carried into commitment restart",
            )
        return commitment
