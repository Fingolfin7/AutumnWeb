from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import DurationField, ExpressionWrapper, F, Sum
from django.utils import timezone

from core.models import (
    Commitment,
    CommitmentAdjustment,
    CommitmentPeriod,
    CommitmentRevision,
    Context,
    Projects,
    Sessions,
    SubProjects,
    Tag,
)
from core.utils import get_period_bounds


def build_commitment_scope_meta(user) -> dict:
    projects = (
        Projects.objects.filter(user=user)
        .select_related("context")
        .prefetch_related("tags")
        .order_by("name")
    )
    subprojects = (
        SubProjects.objects.filter(user=user)
        .select_related("parent_project__context")
        .prefetch_related("parent_project__tags")
        .order_by("name")
    )

    project_meta = {}
    tag_context_ids = {}
    for project in projects:
        tag_ids = [tag.id for tag in project.tags.all()]
        project_meta[str(project.id)] = {
            "context_id": project.context_id,
            "tag_ids": tag_ids,
        }
        for tag_id in tag_ids:
            tag_context_ids.setdefault(str(tag_id), set()).add(project.context_id)

    subproject_meta = {}
    for subproject in subprojects:
        parent = subproject.parent_project
        subproject_meta[str(subproject.id)] = {
            "project_id": parent.id,
            "context_id": parent.context_id,
            "tag_ids": [tag.id for tag in parent.tags.all()],
        }

    tag_meta = {}
    for tag in Tag.objects.filter(user=user).order_by("name"):
        tag_meta[str(tag.id)] = {
            "context_ids": sorted(
                [
                    context_id
                    for context_id in tag_context_ids.get(str(tag.id), set())
                    if context_id is not None
                ]
            )
        }

    return {
        "projects": project_meta,
        "subprojects": subproject_meta,
        "tags": tag_meta,
    }


def _project_has_any_subproject_in_qs(project: Projects, subprojects_qs) -> bool:
    return subprojects_qs.filter(parent_project=project).exists()


def _list_names(qs):
    return list(qs.values_list("name", flat=True))


def build_commitment_rule_lines(commitment: Commitment) -> list[str]:
    lines = [
        f"Scope: {commitment.get_aggregation_type_display()} = {commitment.target_name}"
    ]

    rule_parts = []
    for label, include_qs, exclude_qs in [
        ("Tags", commitment.include_tags.all(), commitment.exclude_tags.all()),
        (
            "Projects",
            commitment.include_projects.all(),
            commitment.exclude_projects.all(),
        ),
        (
            "Subprojects",
            commitment.include_subprojects.all(),
            commitment.exclude_subprojects.all(),
        ),
        (
            "Contexts",
            commitment.include_contexts.all(),
            commitment.exclude_contexts.all(),
        ),
    ]:
        include_names = _list_names(include_qs)
        exclude_names = _list_names(exclude_qs)
        if include_names:
            rule_parts.append(f"Include {label}: {', '.join(include_names)}")
        if exclude_names:
            rule_parts.append(f"Exclude {label}: {', '.join(exclude_names)}")

    if not rule_parts:
        lines.append("Rules: all sessions in scope count.")
    else:
        lines.extend(rule_parts)

    return lines


def build_commitment_panel_items(commitments):
    items = []
    for commitment in commitments:
        progress = None
        if commitment.active:
            reconcile_commitment(commitment)
            progress = get_commitment_progress(commitment)
        items.append(
            {
                "commitment": commitment,
                "progress": progress,
                "rule_lines": build_commitment_rule_lines(commitment),
            }
        )
    return items


def commitment_applies_to_project(commitment: Commitment, project: Projects) -> bool:
    """
    Determine whether a commitment is relevant to a project based on aggregation
    scope and composable include/exclude rules.
    """
    if commitment.aggregation_type == "context":
        if commitment.context_id != project.context_id:
            return False
    elif commitment.aggregation_type == "tag":
        if not project.tags.filter(pk=commitment.tag_id).exists():
            return False
    elif commitment.aggregation_type == "project":
        if commitment.project_id != project.id:
            return False
    elif commitment.aggregation_type == "subproject":
        if not commitment.subproject_id:
            return False
        return commitment.subproject.parent_project_id == project.id
    else:
        return False

    include_tags = commitment.include_tags.all()
    exclude_tags = commitment.exclude_tags.all()
    include_projects = commitment.include_projects.all()
    exclude_projects = commitment.exclude_projects.all()
    include_subprojects = commitment.include_subprojects.all()

    if (
        include_tags.exists()
        and not project.tags.filter(pk__in=include_tags.values("pk")).exists()
    ):
        return False
    if (
        exclude_tags.exists()
        and project.tags.filter(pk__in=exclude_tags.values("pk")).exists()
    ):
        return False
    if include_projects.exists() and not include_projects.filter(pk=project.id).exists():
        return False
    if exclude_projects.exists() and exclude_projects.filter(pk=project.id).exists():
        return False
    if include_subprojects.exists() and not _project_has_any_subproject_in_qs(
        project, include_subprojects
    ):
        return False

    return True


def commitment_applies_to_subproject(
    commitment: Commitment, subproject: SubProjects
) -> bool:
    project = subproject.parent_project

    if commitment.aggregation_type == "context":
        if commitment.context_id != project.context_id:
            return False
    elif commitment.aggregation_type == "tag":
        if not project.tags.filter(pk=commitment.tag_id).exists():
            return False
    elif commitment.aggregation_type == "project":
        if commitment.project_id != project.id:
            return False
    elif commitment.aggregation_type == "subproject":
        if commitment.subproject_id != subproject.id:
            return False
    else:
        return False

    include_tags = commitment.include_tags.all()
    exclude_tags = commitment.exclude_tags.all()
    include_projects = commitment.include_projects.all()
    exclude_projects = commitment.exclude_projects.all()
    include_subprojects = commitment.include_subprojects.all()
    exclude_subprojects = commitment.exclude_subprojects.all()

    if (
        include_tags.exists()
        and not project.tags.filter(pk__in=include_tags.values("pk")).exists()
    ):
        return False
    if (
        exclude_tags.exists()
        and project.tags.filter(pk__in=exclude_tags.values("pk")).exists()
    ):
        return False
    if include_projects.exists() and not include_projects.filter(pk=project.id).exists():
        return False
    if exclude_projects.exists() and exclude_projects.filter(pk=project.id).exists():
        return False
    if (
        include_subprojects.exists()
        and not include_subprojects.filter(pk=subproject.id).exists()
    ):
        return False
    if (
        exclude_subprojects.exists()
        and exclude_subprojects.filter(pk=subproject.id).exists()
    ):
        return False

    return True


def commitment_applies_to_context(commitment: Commitment, context_obj: Context) -> bool:
    projects = Projects.objects.filter(user=commitment.user, context=context_obj)
    return any(commitment_applies_to_project(commitment, project) for project in projects)


def commitment_applies_to_tag(commitment: Commitment, tag_obj: Tag) -> bool:
    projects = Projects.objects.filter(user=commitment.user, tags=tag_obj).distinct()
    return any(commitment_applies_to_project(commitment, project) for project in projects)


def get_commitment_sessions_queryset(commitment, period_start, period_end):
    sessions = Sessions.objects.filter(
        user=commitment.user,
        end_time__isnull=False,
        end_time__gte=period_start,
        end_time__lt=period_end,
    )

    if commitment.aggregation_type == "project" and commitment.project_id:
        sessions = sessions.filter(project=commitment.project)
    elif commitment.aggregation_type == "subproject" and commitment.subproject_id:
        sessions = sessions.filter(subprojects=commitment.subproject)
    elif commitment.aggregation_type == "context" and commitment.context_id:
        sessions = sessions.filter(project__context=commitment.context)
    elif commitment.aggregation_type == "tag" and commitment.tag_id:
        sessions = sessions.filter(project__tags=commitment.tag)
    else:
        return sessions.none()

    return _apply_commitment_composable_filters(commitment, sessions)


def _apply_commitment_composable_filters(commitment, sessions):
    allowed_rule_dimensions = {
        "context": {"tag", "project", "subproject"},
        "tag": {"project", "subproject"},
        "project": {"subproject"},
        "subproject": set(),
    }.get(commitment.aggregation_type, set())

    include_project_ids = list(
        commitment.include_projects.values_list("pk", flat=True)
        if "project" in allowed_rule_dimensions
        else []
    )
    exclude_project_ids = list(
        commitment.exclude_projects.values_list("pk", flat=True)
        if "project" in allowed_rule_dimensions
        else []
    )
    include_subproject_ids = list(
        commitment.include_subprojects.values_list("pk", flat=True)
        if "subproject" in allowed_rule_dimensions
        else []
    )
    exclude_subproject_ids = list(
        commitment.exclude_subprojects.values_list("pk", flat=True)
        if "subproject" in allowed_rule_dimensions
        else []
    )
    include_context_ids = list(
        commitment.include_contexts.values_list("pk", flat=True)
        if "context" in allowed_rule_dimensions
        else []
    )
    exclude_context_ids = list(
        commitment.exclude_contexts.values_list("pk", flat=True)
        if "context" in allowed_rule_dimensions
        else []
    )
    include_tag_ids = list(
        commitment.include_tags.values_list("pk", flat=True)
        if "tag" in allowed_rule_dimensions
        else []
    )
    exclude_tag_ids = list(
        commitment.exclude_tags.values_list("pk", flat=True)
        if "tag" in allowed_rule_dimensions
        else []
    )

    if include_project_ids:
        sessions = sessions.filter(project_id__in=include_project_ids)
    if include_subproject_ids:
        sessions = sessions.filter(subprojects__pk__in=include_subproject_ids)
    if include_context_ids:
        sessions = sessions.filter(project__context_id__in=include_context_ids)
    if include_tag_ids:
        sessions = sessions.filter(project__tags__pk__in=include_tag_ids)

    if exclude_project_ids:
        sessions = sessions.exclude(project_id__in=exclude_project_ids)
    if exclude_subproject_ids:
        sessions = sessions.exclude(subprojects__pk__in=exclude_subproject_ids)
    if exclude_context_ids:
        sessions = sessions.exclude(project__context_id__in=exclude_context_ids)
    if exclude_tag_ids:
        sessions = sessions.exclude(project__tags__pk__in=exclude_tag_ids)

    return sessions.distinct()


def commitment_actual(commitment, period_start, period_end) -> float | int:
    sessions = get_commitment_sessions_queryset(
        commitment, period_start, period_end
    )

    if commitment.commitment_type != "time":
        return sessions.count()

    distinct_sessions = Sessions.objects.filter(pk__in=sessions.values("pk"))
    duration = distinct_sessions.aggregate(
        total=Sum(
            ExpressionWrapper(
                F("end_time") - F("start_time"),
                output_field=DurationField(),
            )
        )
    )["total"]
    return duration.total_seconds() / 60 if duration is not None else 0


_REVISION_FILTER_FIELDS = (
    "include_projects",
    "exclude_projects",
    "include_subprojects",
    "exclude_subprojects",
    "include_contexts",
    "exclude_contexts",
    "include_tags",
    "exclude_tags",
)


def snapshot_commitment_definition(commitment: Commitment) -> dict:
    """Return the immutable definition fields stored on a revision."""
    target = commitment.target_object
    filters = {}
    for field in _REVISION_FILTER_FIELDS:
        filters[field] = [
            {"id": obj.pk, "name": obj.name}
            for obj in getattr(commitment, field).all().order_by("pk")
        ]

    profile = getattr(commitment.user, "profile", None)
    timezone_name = getattr(profile, "timezone", None) or settings.TIME_ZONE
    return {
        "generation": commitment.generation,
        "aggregation_type": commitment.aggregation_type,
        "target_id": target.pk if target is not None else None,
        "target_name": target.name if target is not None else "",
        "filters_snapshot": filters,
        "commitment_type": commitment.commitment_type,
        "cadence": commitment.period,
        "target_value": commitment.target,
        "banking_enabled": commitment.banking_enabled,
        "max_balance": commitment.max_balance,
        "min_balance": commitment.min_balance,
        "start_date": commitment.start_date,
        "timezone": timezone_name,
    }


def _local_midnight(day, zone):
    return datetime.combine(day, datetime.min.time(), tzinfo=zone)


def _ensure_ledger_initialized(commitment: Commitment, now):
    """Bootstrap commitments created after the data migration.

    The migration itself anchors existing rows at its cutover instant. Until the
    revision-edit service lands, newly-created legacy/v1 rows are anchored at
    their start-date midnight so their first reconciliation retains v1 math.
    """
    revision = (
        commitment.revisions.filter(
            generation=commitment.generation,
            status=CommitmentRevision.STATUS_ACTIVE,
        )
        .order_by("-effective_from_instant", "-pk")
        .first()
    )
    if commitment.ledger_start_at is not None and revision is not None:
        return revision

    definition = snapshot_commitment_definition(commitment)
    zone = ZoneInfo(definition["timezone"])
    anchor = commitment.ledger_start_at or _local_midnight(
        definition["start_date"], zone
    )
    commitment.ledger_start_at = anchor
    commitment.needs_recompute = True
    commitment.save(update_fields=["ledger_start_at", "needs_recompute"])

    if revision is None:
        revision = CommitmentRevision.objects.create(
            commitment=commitment,
            effective_from_instant=anchor,
            status=CommitmentRevision.STATUS_ACTIVE,
            **definition,
        )
    if not commitment.adjustments.filter(
        kind=CommitmentAdjustment.KIND_OPENING
    ).exists():
        next_seq = (
            commitment.adjustments.order_by("-seq")
            .values_list("seq", flat=True)
            .first()
            or 0
        ) + 1
        CommitmentAdjustment.objects.create(
            commitment=commitment,
            seq=next_seq,
            kind=CommitmentAdjustment.KIND_OPENING,
            amount=commitment.balance,
            effective_at=anchor,
            reason="Initial commitment opening balance",
        )
    return revision


def _snapshot_ids(revision, field):
    values = revision.filters_snapshot.get(field, [])
    return [value["id"] if isinstance(value, dict) else value for value in values]


def _revision_sessions_queryset(revision, period_start, period_end):
    commitment = revision.commitment
    sessions = Sessions.objects.filter(
        user_id=commitment.user_id,
        end_time__isnull=False,
        end_time__gte=period_start,
        end_time__lt=period_end,
    )
    target_id = revision.target_id
    if revision.aggregation_type == "project" and target_id:
        sessions = sessions.filter(project_id=target_id)
    elif revision.aggregation_type == "subproject" and target_id:
        sessions = sessions.filter(subprojects__pk=target_id)
    elif revision.aggregation_type == "context" and target_id:
        sessions = sessions.filter(project__context_id=target_id)
    elif revision.aggregation_type == "tag" and target_id:
        sessions = sessions.filter(project__tags__pk=target_id)
    else:
        return sessions.none()

    allowed = {
        "context": {"tag", "project", "subproject"},
        "tag": {"project", "subproject"},
        "project": {"subproject"},
        "subproject": set(),
    }.get(revision.aggregation_type, set())
    dimensions = {
        "projects": "project_id",
        "subprojects": "subprojects__pk",
        "contexts": "project__context_id",
        "tags": "project__tags__pk",
    }
    for plural, lookup in dimensions.items():
        singular = plural[:-1]
        if singular not in allowed:
            continue
        include_ids = _snapshot_ids(revision, f"include_{plural}")
        exclude_ids = _snapshot_ids(revision, f"exclude_{plural}")
        if include_ids:
            sessions = sessions.filter(**{f"{lookup}__in": include_ids})
        if exclude_ids:
            sessions = sessions.exclude(**{f"{lookup}__in": exclude_ids})
    return sessions.distinct()


def _revision_accrual(revision, period_start, period_end):
    sessions = list(
        _revision_sessions_queryset(revision, period_start, period_end)
        .order_by("pk")
        .values_list("pk", "start_time", "end_time")
    )
    total_microseconds = sum(
        (
            (end_time - start_time).days * 86_400_000_000
            + (end_time - start_time).seconds * 1_000_000
            + (end_time - start_time).microseconds
        )
        for _, start_time, end_time in sessions
    )
    # One numerator unit is 1/10000 minute, i.e. 6000 microseconds.
    return total_microseconds // 6000, len(sessions)


def _periods_for_replay(revision, ledger_start_at, now):
    zone = ZoneInfo(revision.timezone)
    start_dt = _local_midnight(revision.start_date, zone)
    cursor = max(ledger_start_at, start_dt)
    periods = []
    while cursor <= now:
        local_reference = cursor.astimezone(zone)
        with timezone.override(zone):
            period_start, period_end = get_period_bounds(
                revision.cadence, local_reference
            )
        if period_end <= cursor:
            cursor = period_end + timedelta(seconds=1)
            continue
        if period_end > now:
            break
        if period_end > ledger_start_at:
            periods.append(
                (period_start, max(period_start, ledger_start_at, start_dt), period_end)
            )
        cursor = period_end + timedelta(seconds=1)
    return periods


def _activate_due_revision(commitment, now):
    pending = (
        commitment.revisions.filter(
            generation=commitment.generation,
            status=CommitmentRevision.STATUS_PENDING,
            effective_from_instant__lte=now,
        )
        .order_by("effective_from_instant", "pk")
        .first()
    )
    if pending is None:
        return False

    pending.status = CommitmentRevision.STATUS_ACTIVE
    pending.save(update_fields=["status"])
    commitment.target = pending.target_value
    commitment.banking_enabled = pending.banking_enabled
    commitment.max_balance = pending.max_balance
    commitment.min_balance = pending.min_balance
    commitment.save(
        update_fields=["target", "banking_enabled", "max_balance", "min_balance"]
    )
    for field in _REVISION_FILTER_FIELDS:
        getattr(commitment, field).set(_snapshot_ids(pending, field))
    return True


def _revision_for_period(revisions, period_start):
    governing = None
    for revision in revisions:
        if revision.effective_from_instant <= period_start:
            governing = revision
        else:
            break
    # A newly-created/restarted ledger may begin partway through its first
    # canonical period, after that period's midnight boundary.
    return governing or revisions[0]


def mutation_affects_ledger(commitment: Commitment, instant) -> bool:
    """Whether a mutation instant belongs to the current accounting ledger."""
    if commitment.ledger_start_at is None:
        return True
    if timezone.is_naive(instant):
        instant = timezone.make_aware(instant)
    return instant >= commitment.ledger_start_at


@transaction.atomic
def recompute_commitment(commitment: Commitment) -> bool:
    """Rebuild current-generation derived periods and replay their event stream."""
    locked = Commitment.objects.select_for_update().get(pk=commitment.pk)
    now = timezone.now()
    old_balance = locked.balance
    was_dirty = locked.needs_recompute

    if not locked.active:
        locked.needs_recompute = False
        locked.save(update_fields=["needs_recompute"])
        commitment.balance = locked.balance
        commitment.needs_recompute = False
        commitment.ledger_start_at = locked.ledger_start_at
        commitment.generation = locked.generation
        commitment.active = False
        return was_dirty

    revision = _ensure_ledger_initialized(locked, now)
    activated = _activate_due_revision(locked, now)
    revisions = list(
        locked.revisions.filter(
            generation=locked.generation,
            status=CommitmentRevision.STATUS_ACTIVE,
        ).order_by("effective_from_instant", "pk")
    )
    if not revisions:
        revisions = [revision]
    anchor = locked.ledger_start_at
    desired = _periods_for_replay(revisions[0], anchor, now)
    existing = {
        row.period_start: row
        for row in locked.period_rows.filter(generation=locked.generation)
    }
    period_rows = []
    derived_changed = activated
    for period_start, effective_start, period_end in desired:
        revision = _revision_for_period(revisions, period_start)
        accrued_numerator, session_count = _revision_accrual(
            revision, effective_start, period_end
        )
        row = existing.get(period_start)
        if row is None:
            row = CommitmentPeriod.objects.create(
                commitment=locked,
                generation=locked.generation,
                revision=revision,
                period_start=period_start,
                period_end=period_end,
                accrued_numerator=accrued_numerator,
                session_count=session_count,
                closed_at=now,
            )
            derived_changed = True
        else:
            updates = {
                "revision": revision,
                "period_end": period_end,
                "accrued_numerator": accrued_numerator,
                "session_count": session_count,
            }
            changed_fields = [
                field for field, value in updates.items() if getattr(row, field) != value
            ]
            if changed_fields:
                for field, value in updates.items():
                    setattr(row, field, value)
                row.save(update_fields=changed_fields)
                derived_changed = True
        period_rows.append(row)

    desired_starts = [row.period_start for row in period_rows]
    stale = locked.period_rows.filter(generation=locked.generation)
    if desired_starts:
        stale = stale.exclude(period_start__in=desired_starts)
    if stale.exists():
        stale.delete()
        derived_changed = True

    events = []
    for adjustment in locked.adjustments.filter(effective_at__gte=anchor):
        events.append((adjustment.effective_at, 0, adjustment.seq, adjustment))
    for row in period_rows:
        events.append((row.period_end, 1, row.period_start, row))
    events.sort(key=lambda event: (event[0], event[1], event[2]))

    running = 0
    last_initialized = 0
    latest_balance_out = None
    for _, event_type, _, event in events:
        if event_type == 0:
            if event.kind in {
                CommitmentAdjustment.KIND_OPENING,
                CommitmentAdjustment.KIND_RESTART_CARRY,
            }:
                running = event.amount
                last_initialized = event.amount
            else:
                running += event.amount
            continue

        carryover_in = running
        revision = event.revision
        actual = (
            event.accrued_numerator / 10000
            if revision.commitment_type == "time"
            else event.session_count
        )
        surplus = actual - revision.target_value
        if revision.banking_enabled:
            running = int(
                max(
                    revision.min_balance,
                    min(revision.max_balance, running + surplus),
                )
            )
        row_updates = []
        if event.carryover_in != carryover_in:
            event.carryover_in = carryover_in
            row_updates.append("carryover_in")
        if event.balance_out != running:
            event.balance_out = running
            row_updates.append("balance_out")
        if row_updates:
            event.save(update_fields=row_updates)
            derived_changed = True
        latest_balance_out = running

    locked.balance = (
        latest_balance_out if latest_balance_out is not None else last_initialized
    )
    locked.needs_recompute = False
    locked.save(update_fields=["balance", "needs_recompute"])

    commitment.balance = locked.balance
    commitment.needs_recompute = False
    commitment.ledger_start_at = locked.ledger_start_at
    commitment.generation = locked.generation
    commitment.target = locked.target
    commitment.banking_enabled = locked.banking_enabled
    commitment.max_balance = locked.max_balance
    commitment.min_balance = locked.min_balance
    if activated:
        commitment._prefetched_objects_cache = {}
    return derived_changed or was_dirty or old_balance != locked.balance


def get_commitment_progress(commitment) -> dict:
    """
    Calculate the progress for a commitment in the current period.
    """
    period_start, period_end = get_period_bounds(commitment.period)
    start_dt = get_commitment_start_datetime(commitment)
    effective_period_start = max(period_start, start_dt)

    if effective_period_start >= period_end:
        actual = 0
    else:
        actual = commitment_actual(
            commitment, effective_period_start, period_end
        )

    if commitment.commitment_type == "time":
        actual = round(actual, 2)

    target = commitment.target
    percentage = min(round((actual / target) * 100, 1), 100) if target > 0 else 0

    if percentage >= 100:
        status = "complete"
    elif percentage >= 75:
        status = "approaching"
    elif percentage >= 50:
        status = "on-track"
    elif percentage >= 25:
        status = "warning"
    else:
        status = "behind"

    current_surplus = actual - target

    return {
        "actual": actual,
        "target": target,
        "percentage": percentage,
        "balance": commitment.balance,
        "current_surplus": round(current_surplus, 2),
        "status": status,
        "period_start": period_start,
        "effective_period_start": effective_period_start,
        "period_end": period_end,
        "commitment_type": commitment.commitment_type,
        "period": commitment.period,
    }


def calculate_commitment_streak(commitment, num_periods=8) -> dict:
    """
    Calculate consecutive periods where commitment target was met, accounting
    for banked time/sessions that can cover deficits.
    """
    now = timezone.now()
    start_dt = get_commitment_start_datetime(commitment)
    _, span_end = get_period_bounds(commitment.period, now)
    span_sessions = get_commitment_sessions_queryset(
        commitment, start_dt, span_end
    )
    session_rows = list(
        Sessions.objects.filter(pk__in=span_sessions.values("pk"))
        .order_by("end_time", "pk")
        .values_list("pk", "start_time", "end_time")
    )
    session_index = 0
    # Migration cutover deliberately creates no synthetic history. Closed rows
    # are authoritative where present; older/missing periods continue to use
    # the legacy session simulation so v1 streak payloads remain unchanged.
    replay_rows = {
        row.period_start: row
        for row in commitment.period_rows.filter(
            generation=commitment.generation
        ).order_by("period_start")
    }

    all_periods = []
    check_date = start_dt

    while True:
        period_start, period_end = get_period_bounds(commitment.period, check_date)

        if period_end <= start_dt:
            check_date = period_end + timedelta(seconds=1)
            continue

        is_current = period_start <= now < period_end
        effective_start = max(period_start, start_dt)

        while (
            session_index < len(session_rows)
            and session_rows[session_index][2] < effective_start
        ):
            session_index += 1

        bucket = []
        while (
            session_index < len(session_rows)
            and session_rows[session_index][2] < period_end
        ):
            bucket.append(session_rows[session_index])
            session_index += 1

        if commitment.commitment_type == "time":
            actual = sum(
                (end_time - start_time).total_seconds() / 60
                for _, start_time, end_time in bucket
            )
        else:
            actual = len(bucket)

        replay_row = replay_rows.get(period_start)
        if replay_row is not None:
            actual = (
                replay_row.accrued_numerator / 10000
                if commitment.commitment_type == "time"
                else replay_row.session_count
            )

        all_periods.append(
            {
                "period_start": period_start,
                "effective_period_start": effective_start,
                "period_end": period_end,
                "actual": actual,
                "target": commitment.target,
                "is_current": is_current,
            }
        )

        if is_current or period_start > now:
            break

        check_date = period_end + timedelta(seconds=1)

    simulated_balance = 0
    for period in all_periods:
        surplus = period["actual"] - period["target"]

        if period["is_current"]:
            period["met"] = period["actual"] >= period["target"]
            period["saved_by_bank"] = False
        elif surplus >= 0:
            period["met"] = True
            period["saved_by_bank"] = False
            if commitment.banking_enabled:
                simulated_balance = min(
                    commitment.max_balance, simulated_balance + surplus
                )
        else:
            if commitment.banking_enabled and simulated_balance + surplus >= 0:
                period["met"] = True
                period["saved_by_bank"] = True
                simulated_balance += surplus
            else:
                period["met"] = False
                period["saved_by_bank"] = False
                if commitment.banking_enabled:
                    simulated_balance = max(
                        commitment.min_balance, simulated_balance + surplus
                    )

    current_streak = 0
    for period in reversed(all_periods):
        if period["is_current"]:
            continue
        if period["met"]:
            current_streak += 1
        else:
            break

    return {"current_streak": current_streak, "periods": all_periods[-num_periods:]}


def reconcile_commitment(commitment, force: bool = False) -> bool:
    """Compatibility wrapper for all v1/web lazy reconciliation call sites."""
    state = Commitment.objects.only(
        "needs_recompute", "ledger_start_at", "generation"
    ).get(pk=commitment.pk)
    commitment.needs_recompute = state.needs_recompute
    commitment.ledger_start_at = state.ledger_start_at
    commitment.generation = state.generation
    if force or state.needs_recompute or state.ledger_start_at is None:
        return recompute_commitment(commitment)

    revision = (
        state.revisions.filter(
            generation=state.generation,
            status=CommitmentRevision.STATUS_ACTIVE,
        )
        .order_by("-effective_from_instant", "-pk")
        .first()
    )
    if revision is None:
        return recompute_commitment(commitment)

    closed_periods = _periods_for_replay(
        revision, state.ledger_start_at, timezone.now()
    )
    if not closed_periods:
        return False
    latest_start = (
        state.period_rows.filter(generation=state.generation)
        .order_by("-period_start")
        .values_list("period_start", flat=True)
        .first()
    )
    if latest_start != closed_periods[-1][0]:
        return recompute_commitment(commitment)
    return False


def get_commitment_start_datetime(commitment) -> datetime:
    start_date = getattr(commitment, "start_date", None)
    if start_date is None:
        if commitment.created_at:
            start_date = timezone.localtime(commitment.created_at).date()
        else:
            start_date = timezone.localdate()
    return timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
