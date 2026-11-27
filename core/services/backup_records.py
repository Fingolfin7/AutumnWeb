"""Version 1 backup record types and the account-local references they carry."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from math import isfinite
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.dateparse import parse_date, parse_datetime, parse_time

from core.models import (
    Commitment, CommitmentAdjustment, CommitmentPeriod, CommitmentRevision,
    Context, NotificationPreference, Projects, ScheduledReminder, Sessions,
    SubProjects, Tag,
)
from llm_insights.models import LLMAttachment, LLMChat, LLMMessage
from users.models import Profile, validate_iana_timezone


class BackupError(ValueError):
    """A backup or its contents could not be used."""


@dataclass(frozen=True)
class Section:
    model: type[models.Model]
    fields: str
    refs: dict = field(default_factory=dict)
    many: dict = field(default_factory=dict)
    assets: tuple = ()
    owner: str = "user"
    natural: tuple = ()
    extras: tuple = ()
    singleton: bool = False

    @property
    def scalar_fields(self):
        return [self.model._meta.get_field(name) for name in self.fields.split()]


TARGETS = {"project": "projects", "subproject": "subprojects", "context": "contexts", "tag": "tags"}
FILTERS = {f"{op}_{target}": target for op in ("include", "exclude") for target in TARGETS.values()}
CHAT_FILTERS = {"tags": "tags", "include_projects": "projects", "exclude_projects": "projects"}

# Insertion order is the order in which foreign keys can be resolved.
SECTIONS = {
    "contexts": Section(Context, "name description", natural=("name",)),
    "tags": Section(Tag, "name color", natural=("name",)),
    "projects": Section(
        Projects, "name start_date last_updated status description version",
        refs={"context": "contexts"}, many={"tags": "tags"}, natural=("name",),
    ),
    "subprojects": Section(
        SubProjects, "name start_date last_updated description version",
        refs={"parent_project": "projects"}, natural=("parent_project", "name"),
    ),
    "sessions": Section(
        Sessions, "uuid start_time end_time note version", refs={"project": "projects"},
        extras=("allocations",), natural=("uuid",),
    ),
    "commitments": Section(
        Commitment, "aggregation_type commitment_type period start_date target max_balance min_balance "
        "banking_enabled notifications_enabled active created_at ledger_start_at generation version needs_recompute",
        refs=TARGETS, many=FILTERS, natural=("project", "subproject", "context", "tag"),
    ),
    "commitment_revisions": Section(
        CommitmentRevision, "generation effective_from_instant status aggregation_type target_name "
        "commitment_type cadence target_value banking_enabled max_balance min_balance start_date timezone",
        refs={"commitment": "commitments"}, owner="commitment__user", extras=("target_id", "filters_snapshot"),
    ),
    "commitment_periods": Section(
        CommitmentPeriod, "generation period_start period_end accrued_numerator session_count carryover_in balance_out closed_at",
        refs={"commitment": "commitments", "revision": "commitment_revisions"},
        owner="commitment__user", natural=("commitment", "generation", "period_start"),
    ),
    "commitment_adjustments": Section(
        CommitmentAdjustment, "seq kind amount effective_at reason", refs={"commitment": "commitments"},
        owner="commitment__user", natural=("commitment", "seq"),
    ),
    "profile": Section(
        Profile, "timezone background_dimming automatic_background bing_background nasa_apod_background "
        "luna_recommendation_effort search_ranker default_filter_value default_filter_unit "
        "insights_default_filter_value insights_default_filter_unit default_chart_project_count related_similarity",
        refs={"active_context": "contexts"}, assets=("image", "background_image"), singleton=True,
    ),
    "notification_preferences": Section(
        NotificationPreference, "scheduled_reminders_enabled commitment_checks_enabled weekly_review_enabled "
        "commitment_check_time weekly_review_weekday weekly_review_time", singleton=True,
    ),
    "reminder_schedules": Section(
        ScheduledReminder, "message cadence timezone anchor_date anchor_time active cancelled_at created_at updated_at version",
        refs={field: TARGETS[field] for field in ScheduledReminder.TARGET_FIELDS}, many={"subprojects": "subprojects"},
    ),
    "insight_chats": Section(LLMChat, "title model created_at updated_at", extras=("filters",)),
    "insight_messages": Section(
        LLMMessage, "role content created_at", refs={"chat": "insight_chats"},
        owner="chat__user", extras=("metadata",),
    ),
    "insight_attachments": Section(
        LLMAttachment, "name kind mime size text created_at", refs={"message": "insight_messages"}, assets=("file",),
    ),
}


def encode(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (time, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def uuid_string(value):
    if isinstance(value, str):
        try:
            if str(UUID(value)) == value:
                return value
        except ValueError:
            pass
    raise BackupError("Expected a canonical record UUID.")


def decode(field, value):
    if value is None and field.null:
        return None
    if isinstance(field, models.DateTimeField):
        value = parse_datetime(value)
        if value is None or value.utcoffset() is None:
            raise BackupError("Expected a date and time with a timezone.")
        value = value.astimezone(timezone.utc)
    elif isinstance(field, models.DateField):
        value = parse_date(value)
    elif isinstance(field, models.TimeField):
        value = time.fromisoformat(value)
        if value.tzinfo is not None:
            raise BackupError("Expected a time without a timezone.")
    elif isinstance(field, models.UUIDField):
        value = UUID(uuid_string(value))
    elif isinstance(field, models.BooleanField):
        if type(value) is not bool:
            raise BackupError("Expected true or false.")
    elif isinstance(field, models.IntegerField):
        if type(value) is not int:
            raise BackupError("Expected an integer.")
    elif isinstance(field, models.FloatField):
        if type(value) not in (int, float) or not isfinite(value):
            raise BackupError("Expected a finite number.")
        value = float(value)
    elif not isinstance(value, str):
        raise BackupError("Expected text.")
    if value is None:
        raise BackupError("Invalid date or time.")
    if field.choices and value not in dict(field.flatchoices):
        raise BackupError("Unknown choice.")
    field.run_validators(value)
    return value


def require_keys(value, expected):
    if not isinstance(value, dict) or value.keys() != set(expected):
        raise BackupError("Record fields do not match this backup version.")


def reference_list(value):
    if not isinstance(value, list):
        raise BackupError("Expected a list of record references.")
    entries = [uuid_string(item) for item in value]
    if len(set(entries)) != len(entries):
        raise BackupError("A record has duplicate references.")
    return sorted(entries)


def validate_record(section, row):
    spec = SECTIONS[section]
    fields = spec.scalar_fields
    require_keys(row, ["id", *(f.name for f in fields), *spec.refs, *spec.many, *spec.assets, *spec.extras])
    uuid_string(row["id"])
    for scalar in fields:
        try:
            row[scalar.name] = encode(decode(scalar, row[scalar.name]))
        except (ValueError, TypeError, OverflowError, ValidationError) as exc:
            raise BackupError(f"Invalid {scalar.name} in {section}.") from exc
    for field, target in spec.refs.items():
        if row[field] is not None or not spec.model._meta.get_field(field).null:
            uuid_string(row[field])
    for field in spec.many:
        row[field] = reference_list(row[field])
    if "version" in row and row["version"] < 1:
        raise BackupError("Record versions must be positive.")
    if "timezone" in row:
        validate_iana_timezone(row["timezone"])


def equivalent(section, incoming, current):
    ignored = {"id"}
    if section == "commitments":
        ignored.add("needs_recompute")
    return all(value == current.get(key) for key, value in incoming.items() if key not in ignored)
