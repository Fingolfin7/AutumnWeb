"""Build and restore portable account snapshots without replacing user data."""

import hashlib
import json
import logging
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlsplit
from uuid import uuid4, uuid5

from django.contrib.auth.models import User
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, connection, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from core.models import BackupIdentity, Commitment, NotificationPreference, SessionSubproject, Sessions
from core.services.backup_archive import (
    FORMAT, VERSION, asset_path, clean_rollback_files, describe_asset, make_archive,
)
from core.services.backup_records import (
    CHAT_FILTERS, FILTERS, SECTIONS, TARGETS, BackupError, decode, encode,
    equivalent, require_keys, uuid_string, validate_record,
)
from core.services.proactive_notifications import (
    _next_reminder_slot, local_wall_to_utc, reschedule_notification_preferences,
)
from llm_insights.attachments import MAX_STORED_BYTES_PER_USER
from llm_insights.models import LLMAttachment
from users.models import Profile


INSIGHTS = ("insight_chats", "insight_messages", "insight_attachments")
MAX_REPORTED_CONFLICTS = 100
PREVIEW_SALT = "core.account_backup.preview"
PREVIEW_MAX_AGE = 60 * 60
STALE_PREVIEW = "This account changed since the preview, so nothing was restored. Preview the backup again."
logger = logging.getLogger(__name__)


class RestoreConflict(Exception):
    """The restore can't apply the preview it was given; nothing was written."""

    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report


def _query(section, user, lock=False):
    spec = SECTIONS[section]
    queryset = spec.model.objects.filter(**{spec.owner: user}).order_by("pk")
    if section == "sessions":
        queryset = queryset.filter(end_time__isnull=False).prefetch_related("subproject_links")
    if section == "insight_attachments":
        queryset = queryset.filter(message__chat__user=user)
    if spec.many:
        queryset = queryset.prefetch_related(*spec.many)
    if lock:
        queryset = queryset.select_for_update(of=("self",))
    return queryset


def attachment_summary(user):
    return _query("insight_attachments", user).aggregate(
        attachment_count=Count("pk"), attachment_bytes=Sum("size", default=0),
    )


class Identities:
    """Use native IDs where available and remember foreign backup IDs on restore."""

    def __init__(self, user, namespace):
        self.user = user
        self.namespace = namespace
        self.by_portable = defaultdict(dict)
        self.by_local = defaultdict(dict)
        self.preferred = defaultdict(dict)
        self.pending = []
        for row in BackupIdentity.objects.filter(user=user).order_by("pk"):
            self.by_portable[row.section][str(row.portable_id)] = row.local_id
            self.by_local[row.section].setdefault(row.local_id, str(row.portable_id))

    def initial(self, section, pk, obj=None):
        if section == "sessions" and obj:
            return str(obj.uuid)
        if section in ("insight_chats", "insight_attachments"):
            return str(pk)
        return str(uuid5(self.namespace, f"{section}:{pk}"))

    def portable(self, section, pk, obj=None):
        return (
            self.preferred[section].get(str(pk)) or self.by_local[section].get(str(pk))
            or self.initial(section, pk, obj)
        )

    def bind(self, section, portable, pk):
        local_id = str(pk)
        if self.by_portable[section].get(portable) != local_id:
            self.pending.append(BackupIdentity(user=self.user, section=section, portable_id=portable, local_id=local_id))
            self.by_portable[section][portable] = local_id
            self.by_local[section].setdefault(local_id, portable)

    def persist(self):
        BackupIdentity.objects.bulk_create(
            self.pending, update_conflicts=True, update_fields=["local_id"],
            unique_fields=["user", "section", "portable_id"],
        )

    def encode_historical(self, section, pk):
        if pk is None:
            return None
        if int(pk) < 0:
            return self.portable(f"deleted:{section}", pk)
        return self.portable(section, pk)

    def decode_historical(self, section, portable, matched):
        if portable is None:
            return None
        if portable in matched[section]:
            return matched[section][portable].pk
        tombstones = f"deleted:{section}"
        # Negative integers cannot match the positive primary keys allocated
        # by the database. Keep a reversible mapping for later exports.
        digest = hashlib.sha256(portable.encode("ascii")).digest()
        placeholder = -1 - (int.from_bytes(digest[:8], "big") >> 1)
        self.bind(tombstones, portable, placeholder)
        return placeholder


def _revision_snapshot(snapshot, convert):
    return {
        key: [
            {"id": convert(FILTERS[key], item["id"]), "name": item["name"]}
            if isinstance(item, dict) else convert(FILTERS[key], item)
            for item in items
        ]
        for key, items in snapshot.items() if key in FILTERS
    }


def _numeric_key(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _encode_chat_filters(filters, convert):
    portable = dict(filters)
    for key, target in CHAT_FILTERS.items():
        if key in portable:
            portable[key] = [
                convert(target, pk) for value in portable[key] if (pk := _numeric_key(value)) is not None
            ]
    context = _numeric_key(portable.get("context"))
    if context is not None:
        portable["context"] = {"id": convert("contexts", context)}
    return portable


def _decode_chat_filters(filters, convert):
    local = dict(filters)
    for key, target in CHAT_FILTERS.items():
        if key in local:
            local[key] = [str(convert(target, item)) for item in local[key]]
    if isinstance(local.get("context"), dict):
        local["context"] = str(convert("contexts", local["context"]["id"]))
    return local


def _record(section, obj, ids, *, record_id=None, archive=None, known=None):
    spec = SECTIONS[section]
    portable = record_id or ids.portable(section, obj.pk, obj)

    def link(target, pk):
        if pk is None:
            return None
        ref = ids.portable(target, pk)
        if known is not None and ref not in known[target]:
            raise BackupError(f"A {section} record has a reference outside this backup.")
        return ref

    record = {"id": portable, **{field.name: encode(getattr(obj, field.name)) for field in spec.scalar_fields}}
    for key, target in spec.refs.items():
        record[key] = link(target, getattr(obj, f"{key}_id"))
    for key, target in spec.many.items():
        record[key] = sorted(link(target, item.pk) for item in getattr(obj, key).all())
    for key in spec.assets:
        record[key] = describe_asset(getattr(obj, key), asset_path(section, portable, key), archive)
    if section == "sessions":
        record["allocations"] = sorted(
            ({"subproject": link("subprojects", entry.subproject_id), "basis_points": entry.allocation_bp}
             for entry in obj.subproject_links.all()),
            key=lambda item: item["subproject"],
        )
    elif section == "commitment_revisions":
        record["target_id"] = ids.encode_historical(TARGETS[obj.aggregation_type], obj.target_id)
        record["filters_snapshot"] = _revision_snapshot(obj.filters_snapshot, ids.encode_historical)
    elif section == "insight_chats":
        record["filters"] = _encode_chat_filters(obj.filters, ids.encode_historical)
    elif section == "insight_messages":
        record["metadata"] = obj.metadata
    return record


def build_backup(user, *, include_insights=True, include_attachments=False):
    if include_attachments and not include_insights:
        raise BackupError("Include Insights chats to back up their attachments.")

    namespace = _ensure_namespace(user)

    def manifest(archive):
        ids = Identities(user, namespace)
        known = defaultdict(set)
        records = {}
        for section in SECTIONS:
            if section in INSIGHTS and not include_insights or section == "insight_attachments" and not include_attachments:
                records[section] = []
                continue
            objects = list(_query(section, user))
            if section == "notification_preferences" and not objects:
                objects = [NotificationPreference(user=user)]
            records[section] = [_record(section, obj, ids, archive=archive, known=known) for obj in objects]
            known[section].update(row["id"] for row in records[section])
        return {
            "format": FORMAT, "version": VERSION,
            "source": {"account_id": str(ids.namespace), "username": user.username},
            "includes_insights": include_insights, "includes_attachments": include_attachments,
            "records": records,
        }

    outermost = not connection.in_atomic_block
    with transaction.atomic():
        if outermost and connection.vendor == "postgresql":
            # One snapshot for every section's query, so an edit made while a
            # large backup is written can't leave a reference half-included.
            # Must be the transaction's first statement.
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        return make_archive(manifest)


def _check_target(row, names, expected=None):
    selected = [field for field in names if row[field] is not None]
    if len(selected) != 1 or expected is not None and selected[0] != expected:
        raise BackupError("A record has an invalid target.")


def _validate_revision(row):
    value = row["target_id"]
    if value is not None:
        uuid_string(value)
    snapshot = row["filters_snapshot"]
    if not isinstance(snapshot, dict) or not snapshot.keys() <= FILTERS.keys():
        raise BackupError("Invalid commitment revision filters.")
    for items in snapshot.values():
        if not isinstance(items, list):
            raise BackupError("Invalid commitment revision filters.")
        for item in items:
            if isinstance(item, dict):
                require_keys(item, ("id", "name"))
                uuid_string(item["id"])
                if not isinstance(item["name"], str) or len(item["name"]) > 255:
                    raise BackupError("Invalid commitment revision filter name.")
            else:
                uuid_string(item)


def _validate_chat_filters(filters):
    if not isinstance(filters, dict):
        raise BackupError("Invalid Insights filters.")
    context = filters.get("context")
    if isinstance(context, dict):
        require_keys(context, ("id",))
        uuid_string(context["id"])
    elif context is not None and (not isinstance(context, str) or _numeric_key(context) is not None):
        raise BackupError("Invalid Insights context filter.")
    for field in CHAT_FILTERS.keys() & filters.keys():
        if not isinstance(filters[field], list):
            raise BackupError("Invalid Insights filters.")
        for value in filters[field]:
            uuid_string(value)


def _validate_message(row):
    if row["role"] not in {"system", "user", "assistant"} or not isinstance(row["metadata"], dict):
        raise BackupError("Invalid Insights message.")
    sources = row["metadata"].get("sources", [])
    if not isinstance(sources, list):
        raise BackupError("Invalid Insights message sources.")
    for source in sources:
        if not isinstance(source, dict):
            raise BackupError("Invalid Insights message source.")
        # Sources are rendered as links. Providers sometimes return one with no
        # link, and that must still restore; a script or data URL must not.
        link = source.get("link")
        if link is None or link == "":
            continue
        if not isinstance(link, str) or urlsplit(link).scheme.lower() not in {"", "http", "https"}:
            raise BackupError("An Insights message has an unsupported source link.")


def _validate_links(section, row, indexed):
    spec = SECTIONS[section]
    for key, target in spec.refs.items():
        if row[key] is not None and row[key] not in indexed[target]:
            raise BackupError(f"A {section} record references a missing {target} record.")
    for key, target in spec.many.items():
        if any(item not in indexed[target] for item in row[key]):
            raise BackupError(f"A {section} record references a missing {target} record.")
    if section == "sessions":
        allocations = row["allocations"]
        if not isinstance(allocations, list):
            raise BackupError("Invalid session allocations.")
        chosen = set()
        total = 0
        for allocation in allocations:
            require_keys(allocation, ("subproject", "basis_points"))
            subproject_id = uuid_string(allocation["subproject"])
            subproject = indexed["subprojects"].get(subproject_id)
            points = allocation["basis_points"]
            if (
                not subproject or subproject["parent_project"] != row["project"] or subproject_id in chosen
                or type(points) is not int or not 1 <= points <= 10000
            ):
                raise BackupError("Invalid session allocation or subproject.")
            chosen.add(subproject_id)
            total += points
        if total > 10000 or row["end_time"] is None or row["end_time"] < row["start_time"]:
            raise BackupError("Invalid session allocation total or time range.")
        allocations.sort(key=lambda item: item["subproject"])
    elif section == "commitments":
        _check_target(row, TARGETS, row["aggregation_type"])
        if row["generation"] < 1 or row["min_balance"] > row["max_balance"]:
            raise BackupError("Invalid commitment generation or balance bounds.")
    elif section == "commitment_revisions":
        _validate_revision(row)
        if not 1 <= row["generation"] <= indexed["commitments"][row["commitment"]]["generation"]:
            raise BackupError("Invalid commitment revision generation.")
    elif section == "commitment_periods":
        revision = indexed["commitment_revisions"][row["revision"]]
        if (
            revision["commitment"] != row["commitment"] or revision["generation"] != row["generation"]
            or row["period_start"] >= row["period_end"] or row["session_count"] < 0
        ):
            raise BackupError("Invalid commitment period or revision link.")
    elif section == "notification_preferences":
        fields = {field.name: decode(field, row[field.name]) for field in spec.scalar_fields}
        NotificationPreference(**fields).clean()
    elif section == "profile" and not 0 <= row["background_dimming"] <= 85:
        raise BackupError("Invalid profile background dimming.")
    elif section == "reminder_schedules":
        _check_target(row, ("project", "context", "tag"))
        if row["active"] and row["cancelled_at"] is not None:
            raise BackupError("An active reminder cannot be cancelled.")
        if any(indexed["subprojects"][item]["parent_project"] != row["project"] for item in row["subprojects"]):
            raise BackupError("A reminder includes a subproject outside its target.")
    elif section == "insight_chats":
        _validate_chat_filters(row["filters"])
    elif section == "insight_messages":
        _validate_message(row)


def _validate_manifest(reader, manifest):
    records = manifest["records"]
    require_keys(records, SECTIONS)
    indexed = defaultdict(dict)
    for section, spec in SECTIONS.items():
        rows = records[section]
        if not isinstance(rows, list) or spec.singleton and len(rows) != 1:
            raise BackupError(f"Invalid list of {section} records.")
        if rows and (
            section in INSIGHTS and not manifest["includes_insights"]
            or section == "insight_attachments" and not manifest["includes_attachments"]
        ):
            raise BackupError("The ZIP contains records excluded by its backup options.")
        keys = set()
        for row in rows:
            validate_record(section, row)
            _validate_links(section, row, indexed)
            if row["id"] in indexed[section]:
                raise BackupError(f"Duplicate {section} record UUID.")
            if spec.natural:
                key = tuple(row[field] for field in spec.natural)
                if key in keys:
                    raise BackupError(f"Duplicate {section} record.")
                keys.add(key)
            if section == "commitment_revisions" and row["status"] == "pending":
                if row["commitment"] in keys:
                    raise BackupError("A commitment has more than one pending revision.")
                keys.add(row["commitment"])
            for asset in spec.assets:
                reader.validate_asset(section, row, asset)
            indexed[section][row["id"]] = row
    reader.check_members()


def validate_backup(reader):
    manifest = reader.manifest()
    try:
        _validate_manifest(reader, manifest)
    except BackupError:
        raise
    except (ValueError, TypeError, ValidationError) as exc:
        raise BackupError("The manifest contains an invalid record or reference.") from exc
    return manifest


def _natural_key(section, row, matches):
    spec = SECTIONS[section]
    key = []
    for field in spec.natural:
        value = row[field]
        if field in spec.refs and value is not None:
            obj = matches[spec.refs[field]].get(value)
            if obj is None:
                return None
            value = obj.pk
        key.append(value)
    return tuple(key)


def _local_natural_key(spec, obj):
    return tuple(
        getattr(obj, f"{field}_id") if field in spec.refs else encode(getattr(obj, field))
        for field in spec.natural
    )


def _is_default(section, current):
    spec = SECTIONS[section]
    defaults = spec.model()
    return (
        all(current[field.name] == encode(getattr(defaults, field.name)) for field in spec.scalar_fields)
        and all(current[field] is None for field in (*spec.assets, *spec.refs))
    )


def _same_record(section, row, current, now):
    if section == "reminder_schedules" and row["cadence"] == "once" and row["active"] and not current["active"]:
        instant = local_wall_to_utc(
            datetime.fromisoformat(f"{row['anchor_date']}T{row['anchor_time']}"), row["timezone"], strict=False,
        )
        if instant <= now:
            row = {**row, "active": False}
    return equivalent(section, row, current)


def _conflict_label(row):
    return str(row.get("name") or row.get("title") or row.get("target_name") or row.get("start_time") or row["id"])[:255]


class RestorePlan:
    def __init__(self, user, manifest, *, lock):
        self.user = user
        self.ids = Identities(user, _ensure_namespace(user))
        self.matches = defaultdict(dict)
        self.entries = {}
        self.conflicts = []
        self.counts = {}
        self.now = timezone.now()
        self.manifest = manifest
        self._plan(lock)

    def _plan(self, lock):
        for section, spec in SECTIONS.items():
            counts = {"add": 0, "identical": 0, "conflict": 0}
            self.counts[section] = counts
            self.entries[section] = []
            rows = self.manifest["records"][section]
            if not rows:
                continue
            existing = list(_query(section, self.user, lock=lock))
            by_local = {str(obj.pk): obj for obj in existing}
            by_id = {self.ids.initial(section, obj.pk, obj): obj for obj in existing}
            by_id.update({key: by_local[pk] for key, pk in self.ids.by_portable[section].items() if pk in by_local})
            by_natural = {_local_natural_key(spec, obj): obj for obj in existing} if spec.natural else {}
            # Running timers are not backed up or compared, but they hold
            # their UUID: adding a session with it would break uniqueness.
            running = set(
                str(value) for value in Sessions.objects.filter(
                    user=self.user, end_time__isnull=True,
                ).values_list("uuid", flat=True)
            ) if section == "sessions" else set()
            used = set()
            for row in rows:
                portable = row["id"]
                match_by_id = by_id.get(portable)
                match_by_key = (
                    existing[0] if spec.singleton and existing
                    else by_natural.get(_natural_key(section, row, self.matches))
                )
                obj = match_by_id or match_by_key
                if obj is None:
                    status = "add"
                    if section == "notification_preferences":
                        defaults = _record(section, NotificationPreference(user=self.user), self.ids, record_id=portable)
                        if equivalent(section, row, defaults):
                            status = "identical"
                elif obj.pk in used or match_by_id and match_by_key and match_by_id.pk != match_by_key.pk:
                    status = "conflict"
                else:
                    used.add(obj.pk)
                    self.matches[section][portable] = obj
                    self.ids.preferred[section][str(obj.pk)] = portable
                    current = _record(section, obj, self.ids, record_id=portable)
                    if _same_record(section, row, current, self.now):
                        status = "identical"
                    elif spec.singleton and _is_default(section, current):
                        status = "add"
                    else:
                        status = "conflict"
                if status == "add" and row.get("uuid") in running:
                    status = "conflict"
                    self._add_conflict(section, row, label=f"{_conflict_label(row)} (a running timer has this session's ID)")
                elif status == "conflict":
                    self._add_conflict(section, row)
                counts[status] += 1
                self.entries[section].append((row, obj, status))

        existing_bytes = LLMAttachment.objects.filter(user=self.user).aggregate(total=Sum("size", default=0))["total"]
        added_bytes = sum(row["size"] for row, _, status in self.entries["insight_attachments"] if status == "add")
        if added_bytes and existing_bytes + added_bytes > MAX_STORED_BYTES_PER_USER:
            for row, _, status in self.entries["insight_attachments"]:
                if status == "add":
                    self._add_conflict("insight_attachments", row, label="Attachment storage limit would be exceeded")
                    self.counts["insight_attachments"]["add"] -= 1
                    self.counts["insight_attachments"]["conflict"] += 1

        # The database allows one pending revision per commitment regardless of
        # its generation. Detect a competing pending revision before any writes.
        pending = {
            row["commitment"]: (row, obj, status)
            for row, obj, status in self.entries["commitment_revisions"] if row["status"] == "pending"
        }
        if pending:
            targets = {key: obj.pk for key, obj in self.matches["commitments"].items() if key in pending}
            current_pending = dict(SECTIONS["commitment_revisions"].model.objects.filter(
                commitment_id__in=targets.values(), status="pending",
            ).values_list("commitment_id", "pk"))
            for key, pk in targets.items():
                row, obj, status = pending[key]
                if status == "add" and pk in current_pending and (obj is None or obj.pk != current_pending[pk]):
                    self._add_conflict("commitment_revisions", row, label="The commitment already has a pending revision")
                    self.counts["commitment_revisions"]["add"] -= 1
                    self.counts["commitment_revisions"]["conflict"] += 1

    def additions(self):
        return sum(counts["add"] for counts in self.counts.values())

    def fingerprint(self):
        """Every row's outcome and the local row it maps to. A restore applies
        a preview only while this is unchanged, so it can't write anything
        the preview didn't show."""
        entries = [
            [section, row["id"], status, None if obj is None else str(obj.pk)]
            for section in SECTIONS for row, obj, status in self.entries[section]
        ]
        raw = json.dumps({"entries": entries, "report": self.report()}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _add_conflict(self, section, row, label=None):
        if len(self.conflicts) < MAX_REPORTED_CONFLICTS:
            self.conflicts.append({"section": section, "id": row["id"], "label": label or _conflict_label(row)})

    def report(self):
        source = self.manifest["source"]
        return {
            "version": VERSION,
            "source_account": source["username"],
            "destination_account": self.user.username,
            "same_account": source["account_id"] == str(self.ids.namespace),
            "can_restore": not self.conflicts,
            "includes_insights": self.manifest["includes_insights"],
            "includes_attachments": self.manifest["includes_attachments"],
            "counts": self.counts,
            "conflicts": self.conflicts,
        }

    def _restore_values(self, section, row):
        spec = SECTIONS[section]
        values = {field.name: decode(field, row[field.name]) for field in spec.scalar_fields}
        for key, target in spec.refs.items():
            values[f"{key}_id"] = self.matches[target][row[key]].pk if row[key] is not None else None
        if spec.owner == "user":
            values["user"] = self.user

        def historical(target, portable):
            return self.ids.decode_historical(target, portable, self.matches)

        if section == "commitment_revisions":
            values["target_id"] = historical(TARGETS[row["aggregation_type"]], row["target_id"])
            values["filters_snapshot"] = _revision_snapshot(row["filters_snapshot"], historical)
        elif section == "insight_chats":
            values["filters"] = _decode_chat_filters(row["filters"], historical)
        elif section == "insight_messages":
            values["metadata"] = row["metadata"]
        elif section == "reminder_schedules" and row["active"]:
            reminder = spec.model(**values)
            if row["cadence"] == "once":
                instant = local_wall_to_utc(
                    datetime.combine(reminder.anchor_date, reminder.anchor_time), reminder.timezone, strict=False,
                )
                if instant > self.now:
                    values["next_fire_at"] = instant
                else:
                    values["active"] = False
            else:
                values["next_fire_at"] = _next_reminder_slot(reminder, self.now)
        return values

    def _write_section(self, section, reader, rollback_files):
        spec = SECTIONS[section]
        entries = self.entries[section]
        created = []
        adding = []
        for row, obj, status in entries:
            if obj is not None and row["id"] != self.ids.initial(section, obj.pk, obj):
                # For an identical independently-created record, retain its
                # original export UUID alongside the archive's alias. A row
                # already under its native ID needs no mapping.
                if str(obj.pk) not in self.ids.by_local[section]:
                    self.ids.bind(section, self.ids.initial(section, obj.pk, obj), obj.pk)
                self.ids.bind(section, row["id"], obj.pk)
            if status == "identical":
                continue
            values = self._restore_values(section, row)
            record = obj or spec.model(**values)
            for key in spec.assets:
                values[key] = reader.store(getattr(record, key), row[key], record, rollback_files)
            if obj is not None:
                for name, value in values.items():
                    setattr(obj, name, value)
                obj.save(update_fields=[name for name in values if name != "user"])
            else:
                for name in spec.assets:
                    setattr(record, name, values[name])
                created.append((record, values))
            adding.append((row, record))
        spec.model.objects.bulk_create([record for record, _ in created], batch_size=500)
        auto_fields = [field for field in spec.scalar_fields if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False)]
        if auto_fields:
            for record, values in created:
                for field in auto_fields:
                    setattr(record, field.name, values[field.name])
            spec.model.objects.bulk_update([record for record, _ in created], [field.name for field in auto_fields], batch_size=500)
        for row, record in adding:
            self.matches[section][row["id"]] = record
            if row["id"] != self.ids.initial(section, record.pk, record):
                self.ids.bind(section, row["id"], record.pk)
        self._write_links(section, adding)

    def _write_links(self, section, adding):
        spec = SECTIONS[section]
        for field_name, target in spec.many.items():
            field = spec.model._meta.get_field(field_name)
            through = field.remote_field.through
            parent_id = f"{field.m2m_field_name()}_id"
            child_id = f"{field.m2m_reverse_field_name()}_id"
            through.objects.bulk_create([
                through(**{parent_id: record.pk, child_id: self.matches[target][child].pk})
                for row, record in adding for child in row[field_name]
            ], batch_size=500)
        if section == "sessions":
            SessionSubproject.objects.bulk_create([
                SessionSubproject(
                    session_id=record.pk, subproject_id=self.matches["subprojects"][link["subproject"]].pk,
                    allocation_bp=link["basis_points"],
                )
                for row, record in adding for link in row["allocations"]
            ], batch_size=500)

    def apply(self, reader, rollback_files):
        added_sessions = self.counts["sessions"]["add"]
        other_sessions = Sessions.objects.filter(user=self.user, end_time__isnull=False).count() > self.counts["sessions"]["identical"]
        existing_commitments = [obj.pk for obj in self.matches["commitments"].values()]
        for section in SECTIONS:
            self._write_section(section, reader, rollback_files)
        self.ids.persist()

        commitments = Commitment.objects.filter(user=self.user)
        if other_sessions and self.counts["commitments"]["add"]:
            commitments.exclude(pk__in=existing_commitments).update(needs_recompute=True)
        if added_sessions:
            new_commitments = [
                self.matches["commitments"][row["id"]].pk
                for row, _, status in self.entries["commitments"] if status == "add"
            ]
            commitments.exclude(pk__in=new_commitments).update(needs_recompute=True)

        if self.counts["notification_preferences"]["add"] or self.counts["profile"]["add"]:
            preference = NotificationPreference.objects.select_related("user__profile").filter(user=self.user).first()
            if preference is not None:
                reschedule_notification_preferences(preference, now=self.now)
        if any(self.counts[key]["add"] for key in ("reminder_schedules", "notification_preferences", "profile")):
            from core.services.reminder_dispatcher import wake_dispatcher_on_commit

            wake_dispatcher_on_commit()
        if any(self.counts[key]["add"] for key in ("projects", "subprojects", "sessions")):
            from core.services.embedding_sync import request_sync_on_commit

            request_sync_on_commit(self.user.pk)


def _ensure_namespace(user):
    profiles = Profile.objects.filter(user=user)
    namespace = profiles.values_list("backup_namespace", flat=True).get()
    if namespace is None:
        # Profiles created by the previous app during a rolling deploy omit
        # the new column. Set it once without replacing another request's ID.
        profiles.filter(backup_namespace__isnull=True).update(backup_namespace=uuid4())
        namespace = profiles.values_list("backup_namespace", flat=True).get()
    return namespace


def _preview_token(user, digest, fingerprint):
    payload = {"user": user.pk, "account": str(_ensure_namespace(user)), "archive": digest, "plan": fingerprint}
    return signing.dumps(payload, salt=PREVIEW_SALT)


def _previewed_plan(user, token, digest):
    """The plan fingerprint a token was issued for: this account, these exact
    archive bytes, within the hour."""
    try:
        payload = signing.loads(token, salt=PREVIEW_SALT, max_age=PREVIEW_MAX_AGE)
    except signing.SignatureExpired as exc:
        raise RestoreConflict("This preview has expired, so nothing was restored. Preview the backup again.") from exc
    except signing.BadSignature as exc:
        raise RestoreConflict("This preview isn't valid, so nothing was restored. Preview the backup again.") from exc
    if (
        not isinstance(payload, dict) or payload.get("user") != user.pk
        or payload.get("account") != str(_ensure_namespace(user)) or payload.get("archive") != digest
        or not isinstance(payload.get("plan"), str)
    ):
        raise RestoreConflict(
            "This preview was made for a different file or account, so nothing was restored. Preview the backup again."
        )
    return payload["plan"]


def preview_backup(user, manifest, digest):
    """What restoring would do, with a token that lets restore apply exactly that."""
    plan = RestorePlan(user, manifest, lock=False)
    return {**plan.report(), "preview_token": _preview_token(user, digest, plan.fingerprint())}


def restore_backup(user, manifest, reader, *, digest, token):
    """Apply a previewed restore in one transaction, or write nothing.

    Raises RestoreConflict when the token doesn't match this account and file,
    when the account has changed since the preview, or when the backup has
    conflicts. Restoring again what is already restored succeeds and adds
    nothing, so a retried request is harmless.
    """
    expected = _previewed_plan(user, token, digest)
    rollback_files = []
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)
            plan = RestorePlan(user, manifest, lock=True)
            report = plan.report()
            if plan.fingerprint() != expected:
                if report["can_restore"] and not plan.additions():
                    return {**report, "restored": 0}
                raise RestoreConflict(STALE_PREVIEW, report)
            if not report["can_restore"]:
                raise RestoreConflict("This backup can't be restored while its conflicts remain. Nothing was changed.", report)
            plan.apply(reader, rollback_files)
            return {**report, "restored": plan.additions()}
    except (IntegrityError, OperationalError) as exc:
        clean_rollback_files(rollback_files)
        if isinstance(exc, OperationalError):
            state = getattr(exc.__cause__, "sqlstate", None)
            sqlite_lock = connection.vendor == "sqlite" and "locked" in str(exc).lower()
            if state not in {"40001", "40P01", "55P03"} and not sqlite_lock:
                raise
        # Another write may have reached one of the records being restored.
        logger.warning("Account restore for user %s rolled back (%s)", user.pk, type(exc).__name__)
        raise RestoreConflict(STALE_PREVIEW) from exc
    except BaseException:
        clean_rollback_files(rollback_files)
        raise
