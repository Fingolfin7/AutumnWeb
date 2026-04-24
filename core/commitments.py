from datetime import datetime, timedelta

from django.utils import timezone

from core.models import Commitment, Context, Projects, Sessions, SubProjects, Tag
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
        is_active=False,
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

    include_projects = (
        commitment.include_projects.all()
        if "project" in allowed_rule_dimensions
        else commitment.include_projects.none()
    )
    exclude_projects = (
        commitment.exclude_projects.all()
        if "project" in allowed_rule_dimensions
        else commitment.exclude_projects.none()
    )
    include_subprojects = (
        commitment.include_subprojects.all()
        if "subproject" in allowed_rule_dimensions
        else commitment.include_subprojects.none()
    )
    exclude_subprojects = (
        commitment.exclude_subprojects.all()
        if "subproject" in allowed_rule_dimensions
        else commitment.exclude_subprojects.none()
    )
    include_contexts = (
        commitment.include_contexts.all()
        if "context" in allowed_rule_dimensions
        else commitment.include_contexts.none()
    )
    exclude_contexts = (
        commitment.exclude_contexts.all()
        if "context" in allowed_rule_dimensions
        else commitment.exclude_contexts.none()
    )
    include_tags = (
        commitment.include_tags.all()
        if "tag" in allowed_rule_dimensions
        else commitment.include_tags.none()
    )
    exclude_tags = (
        commitment.exclude_tags.all()
        if "tag" in allowed_rule_dimensions
        else commitment.exclude_tags.none()
    )

    if include_projects.exists():
        sessions = sessions.filter(project__in=include_projects)
    if include_subprojects.exists():
        sessions = sessions.filter(subprojects__in=include_subprojects)
    if include_contexts.exists():
        sessions = sessions.filter(project__context__in=include_contexts)
    if include_tags.exists():
        sessions = sessions.filter(project__tags__in=include_tags)

    if exclude_projects.exists():
        sessions = sessions.exclude(project__in=exclude_projects)
    if exclude_subprojects.exists():
        sessions = sessions.exclude(subprojects__in=exclude_subprojects)
    if exclude_contexts.exists():
        sessions = sessions.exclude(project__context__in=exclude_contexts)
    if exclude_tags.exists():
        sessions = sessions.exclude(project__tags__in=exclude_tags)

    return sessions.distinct()


def get_commitment_progress(commitment) -> dict:
    """
    Calculate the progress for a commitment in the current period.
    """
    period_start, period_end = get_period_bounds(commitment.period)
    start_dt = get_commitment_start_datetime(commitment)
    effective_period_start = max(period_start, start_dt)

    if effective_period_start >= period_end:
        sessions = Sessions.objects.none()
    else:
        sessions = get_commitment_sessions_queryset(
            commitment, effective_period_start, period_end
        )

    if commitment.commitment_type == "time":
        actual = round(sum(session.duration or 0 for session in sessions), 2)
    else:
        actual = sessions.count()

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

    all_periods = []
    check_date = start_dt

    while True:
        period_start, period_end = get_period_bounds(commitment.period, check_date)

        if period_end <= start_dt:
            check_date = period_end + timedelta(seconds=1)
            continue

        is_current = period_start <= now < period_end
        effective_start = max(period_start, start_dt)
        sessions = get_commitment_sessions_queryset(
            commitment, effective_start, period_end
        )

        if commitment.commitment_type == "time":
            actual = sum(session.duration or 0 for session in sessions)
        else:
            actual = sessions.count()

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
    """
    Update the commitment balance when completed periods have not yet been
    reconciled.
    """
    now = timezone.now()
    start_dt = get_commitment_start_datetime(commitment)
    period_start, period_end = get_period_bounds(commitment.period)

    if start_dt >= period_end:
        return False

    if commitment.last_reconciled and commitment.last_reconciled >= period_start and not force:
        return False

    periods_to_reconcile = []
    check_date = commitment.last_reconciled or start_dt

    while True:
        check_start, check_end = get_period_bounds(commitment.period, check_date)

        if check_end > now:
            break

        effective_start = max(check_start, start_dt)
        if effective_start >= check_end:
            check_date = check_end + timedelta(seconds=1)
            continue

        if not commitment.last_reconciled or check_end > commitment.last_reconciled:
            periods_to_reconcile.append((effective_start, check_end))

        check_date = check_end + timedelta(seconds=1)

    if not periods_to_reconcile:
        return False

    for period_start, period_end in periods_to_reconcile:
        sessions = get_commitment_sessions_queryset(commitment, period_start, period_end)

        if commitment.commitment_type == "time":
            actual = sum(session.duration or 0 for session in sessions)
        else:
            actual = sessions.count()

        surplus = actual - commitment.target

        if commitment.banking_enabled:
            new_balance = commitment.balance + surplus
            new_balance = max(
                commitment.min_balance, min(commitment.max_balance, new_balance)
            )
            commitment.balance = int(new_balance)

    commitment.last_reconciled = now
    commitment.save()

    return True


def get_commitment_start_datetime(commitment) -> datetime:
    start_date = getattr(commitment, "start_date", None)
    if start_date is None:
        if commitment.created_at:
            start_date = timezone.localtime(commitment.created_at).date()
        else:
            start_date = timezone.localdate()
    return timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
