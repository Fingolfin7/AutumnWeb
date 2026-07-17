"""Validation and atomic import for portable export format 2."""

from datetime import date, datetime, time, timezone as datetime_timezone
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.models import Commitment, Context, Projects, Sessions, SubProjects, Tag, status_choices
from core.services import SessionMutationService
from core.session_canonical import canonical_existing_session, canonical_session_content


class Format2ValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(errors))


class Format2ConflictError(ValueError):
    def __init__(self, conflicts):
        self.conflicts = sorted(set(conflicts))
        super().__init__("Conflicting session UUIDs: " + ", ".join(self.conflicts))


def _instant(value, path, errors):
    if not isinstance(value, str):
        errors.append(f"{path}: expected an ISO-8601 timestamp")
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        errors.append(f"{path}: expected an ISO-8601 timestamp")
        return None
    if timezone.is_naive(parsed):
        parsed = parsed.replace(tzinfo=datetime_timezone.utc)
    return parsed.astimezone(datetime_timezone.utc).replace(microsecond=0)


def _start_date(value, path, errors):
    parsed = _instant(value, path, []) if isinstance(value, str) else None
    if parsed is not None:
        return parsed
    try:
        parsed_date = date.fromisoformat(value)
    except (TypeError, ValueError):
        errors.append(f"{path}: expected an ISO-8601 date or timestamp")
        return None
    return datetime.combine(parsed_date, time.min, tzinfo=datetime_timezone.utc)


def _string(value, path, errors, *, nullable=False, max_length=None):
    if nullable and value is None:
        return None
    if not isinstance(value, str):
        errors.append(f"{path}: expected a string" + (" or null" if nullable else ""))
        return None
    if max_length is not None and len(value) > max_length:
        errors.append(f"{path}: must contain at most {max_length} characters")
    return value


def _validate_document(user, document, *, force):
    errors = []
    if not isinstance(document, dict) or document.get("format") != 2:
        raise Format2ValidationError(["format: expected 2"])
    raw_projects = document.get("projects")
    if not isinstance(raw_projects, list):
        raise Format2ValidationError(["projects: expected a list"])

    existing_projects = {
        project.name: project
        for project in Projects.objects.filter(user=user).select_related("context")
    }
    existing_subprojects = {}
    for subproject in SubProjects.objects.filter(user=user).select_related("parent_project"):
        key = (subproject.parent_project.name, subproject.name)
        if key in existing_subprojects:
            errors.append(
                f"subprojects: ambiguous existing scoped name {key[0]!r}/{key[1]!r}"
            )
        existing_subprojects[key] = subproject

    normalized_projects = []
    seen_projects = set()
    seen_uuids = set()
    all_session_rows = []
    valid_statuses = {choice[0] for choice in status_choices}

    for project_index, raw_project in enumerate(raw_projects):
        path = f"projects[{project_index}]"
        if not isinstance(raw_project, dict):
            errors.append(f"{path}: expected an object")
            continue
        name = _string(raw_project.get("name"), f"{path}.name", errors, max_length=255)
        if not name:
            errors.append(f"{path}.name: must not be blank")
        elif name in seen_projects:
            errors.append(f"{path}.name: duplicate project name {name!r}")
        seen_projects.add(name)

        status = _string(raw_project.get("status"), f"{path}.status", errors)
        if status is not None and status not in valid_statuses:
            errors.append(f"{path}.status: invalid status {status!r}")
        description = _string(
            raw_project.get("description"), f"{path}.description", errors
        )
        context = _string(
            raw_project.get("context"),
            f"{path}.context",
            errors,
            nullable=True,
            max_length=100,
        )
        start_date = _start_date(raw_project.get("start_date"), f"{path}.start_date", errors)

        raw_tags = raw_project.get("tags")
        tags = []
        if not isinstance(raw_tags, list):
            errors.append(f"{path}.tags: expected a list")
        else:
            for tag_index, raw_tag in enumerate(raw_tags):
                tag = _string(
                    raw_tag, f"{path}.tags[{tag_index}]", errors, max_length=100
                )
                if tag is not None and not tag:
                    errors.append(f"{path}.tags[{tag_index}]: must not be blank")
                elif tag is not None:
                    tags.append(tag)
        tags = sorted(set(tags))

        raw_subprojects = raw_project.get("subprojects")
        subprojects = []
        declared_names = set()
        if not isinstance(raw_subprojects, list):
            errors.append(f"{path}.subprojects: expected a list")
            raw_subprojects = []
        for subproject_index, raw_subproject in enumerate(raw_subprojects):
            sub_path = f"{path}.subprojects[{subproject_index}]"
            if not isinstance(raw_subproject, dict):
                errors.append(f"{sub_path}: expected an object")
                continue
            sub_name = _string(
                raw_subproject.get("name"), f"{sub_path}.name", errors, max_length=255
            )
            sub_description = _string(
                raw_subproject.get("description"), f"{sub_path}.description", errors
            )
            if not sub_name:
                errors.append(f"{sub_path}.name: must not be blank")
            elif sub_name in declared_names:
                errors.append(f"{sub_path}.name: duplicate scoped name {sub_name!r}")
            declared_names.add(sub_name)
            subprojects.append({"name": sub_name, "description": sub_description})

        raw_sessions = raw_project.get("sessions")
        sessions = []
        if not isinstance(raw_sessions, list):
            errors.append(f"{path}.sessions: expected a list")
            raw_sessions = []
        resolvable_names = {
            sub_name
            for project_name, sub_name in existing_subprojects
            if project_name == name
        } | declared_names

        for session_index, raw_session in enumerate(raw_sessions):
            session_path = f"{path}.sessions[{session_index}]"
            if not isinstance(raw_session, dict):
                errors.append(f"{session_path}: expected an object")
                continue
            raw_uuid = raw_session.get("uuid")
            session_uuid = None
            if raw_uuid is not None:
                try:
                    session_uuid = UUID(str(raw_uuid))
                except (TypeError, ValueError, AttributeError):
                    errors.append(f"{session_path}.uuid: expected a UUID or null")
                else:
                    if session_uuid in seen_uuids:
                        errors.append(
                            f"{session_path}.uuid: duplicate UUID {session_uuid} in batch"
                        )
                    seen_uuids.add(session_uuid)

            allocation_mode = raw_session.get("allocation_mode")
            if allocation_mode not in ("legacy_full", "partitioned"):
                errors.append(
                    f"{session_path}.allocation_mode: expected legacy_full or partitioned"
                )
            start = _instant(raw_session.get("start"), f"{session_path}.start", errors)
            end = _instant(raw_session.get("end"), f"{session_path}.end", errors)
            if start is not None and end is not None and end < start:
                errors.append(f"{session_path}.end: must be on or after start")
            note = _string(
                raw_session.get("note"), f"{session_path}.note", errors, nullable=True
            )

            raw_links = raw_session.get("links")
            links = []
            link_names = set()
            total_bp = 0
            if not isinstance(raw_links, list):
                errors.append(f"{session_path}.links: expected a list")
                raw_links = []
            for link_index, raw_link in enumerate(raw_links):
                link_path = f"{session_path}.links[{link_index}]"
                if not isinstance(raw_link, dict):
                    errors.append(f"{link_path}: expected an object")
                    continue
                subproject_name = _string(
                    raw_link.get("subproject"),
                    f"{link_path}.subproject",
                    errors,
                    max_length=255,
                )
                allocation_bp = raw_link.get("allocation_bp")
                if (
                    isinstance(allocation_bp, bool)
                    or not isinstance(allocation_bp, int)
                    or not 1 <= allocation_bp <= 10000
                ):
                    errors.append(f"{link_path}.allocation_bp: must be an integer from 1 to 10000")
                else:
                    total_bp += allocation_bp
                    if allocation_mode == "legacy_full" and allocation_bp != 10000:
                        errors.append(
                            f"{link_path}.allocation_bp: legacy_full links must equal 10000"
                        )
                if subproject_name in link_names:
                    errors.append(
                        f"{link_path}.subproject: duplicate link {subproject_name!r}"
                    )
                link_names.add(subproject_name)
                if subproject_name not in resolvable_names:
                    errors.append(
                        f"{link_path}.subproject: scoped name {subproject_name!r} "
                        f"does not exist in project {name!r}"
                    )
                links.append((subproject_name, allocation_bp))
            if allocation_mode == "partitioned" and total_bp > 10000:
                errors.append(
                    f"{session_path}.links: partitioned allocation sum must not exceed 10000"
                )

            session = {
                "uuid": session_uuid,
                "allocation_mode": allocation_mode,
                "start": start,
                "end": end,
                "note": note,
                "links": links,
            }
            sessions.append(session)
            all_session_rows.append((name, session))

        normalized_projects.append(
            {
                "name": name,
                "status": status,
                "description": description,
                "context": context,
                "tags": tags,
                "start_date": start_date,
                "subprojects": subprojects,
                "sessions": sessions,
            }
        )

    existing_sessions = {
        session.uuid: session
        for session in Sessions.objects.filter(user=user, uuid__in=seen_uuids)
        .select_related("project")
        .prefetch_related("subproject_links__subproject")
    }
    conflicts = []
    if not errors:
        for project_name, session in all_session_rows:
            if session["uuid"] is None:
                continue
            existing = existing_sessions.get(session["uuid"])
            if existing is None:
                continue
            incoming = canonical_session_content(
                project_name,
                session["start"],
                session["end"],
                session["note"],
                session["allocation_mode"],
                session["links"],
            )
            if canonical_existing_session(existing) != incoming:
                conflicts.append(str(session["uuid"]))

    if errors:
        raise Format2ValidationError(errors)
    if conflicts and not force:
        raise Format2ConflictError(conflicts)
    return normalized_projects, existing_sessions


@transaction.atomic
def import_format2(user, document, *, force=False, import_into_context=None):
    """Validate the entire batch and then create/update it in one transaction."""
    projects, existing_sessions = _validate_document(user, document, force=force)
    projects_created = 0
    projects_updated = 0
    sessions_imported = 0
    sessions_skipped = 0

    for project_data in projects:
        project = Projects.objects.filter(user=user, name=project_data["name"]).first()
        if project is None:
            context = import_into_context
            if context is None and project_data["context"]:
                context, _ = Context.objects.get_or_create(
                    user=user, name=project_data["context"]
                )
            project = Projects.objects.create(
                user=user,
                name=project_data["name"],
                status=project_data["status"],
                description=project_data["description"],
                start_date=project_data["start_date"],
                last_updated=project_data["start_date"],
                context=context,
            )
            projects_created += 1
            project.tags.set(
                [Tag.objects.get_or_create(user=user, name=name)[0] for name in project_data["tags"]]
            )
        else:
            projects_updated += 1
            if import_into_context is not None:
                project.context = import_into_context
                project.save(update_fields=["context"])
            elif project.context_id is None and project_data["context"]:
                project.context, _ = Context.objects.get_or_create(
                    user=user, name=project_data["context"]
                )
                project.save(update_fields=["context"])
            project.tags.add(
                *[
                    Tag.objects.get_or_create(user=user, name=name)[0]
                    for name in project_data["tags"]
                ]
            )

        subprojects = {
            subproject.name: subproject
            for subproject in SubProjects.objects.filter(
                user=user, parent_project=project
            )
        }
        for subproject_data in project_data["subprojects"]:
            if subproject_data["name"] not in subprojects:
                subprojects[subproject_data["name"]] = SubProjects.objects.create(
                    user=user,
                    parent_project=project,
                    name=subproject_data["name"],
                    description=subproject_data["description"],
                    start_date=project.start_date,
                    last_updated=project.start_date,
                )

        for session_data in project_data["sessions"]:
            allocations = [
                (subprojects[name], allocation_bp)
                for name, allocation_bp in session_data["links"]
            ]
            existing = existing_sessions.get(session_data["uuid"])
            if existing is not None:
                incoming = canonical_session_content(
                    project.name,
                    session_data["start"],
                    session_data["end"],
                    session_data["note"],
                    session_data["allocation_mode"],
                    session_data["links"],
                )
                if canonical_existing_session(existing) == incoming:
                    sessions_skipped += 1
                    continue
                SessionMutationService.mutate_session(
                    existing.pk,
                    user=user,
                    project=project,
                    start_time=session_data["start"],
                    end_time=session_data["end"],
                    auto_stop_at=None,
                    note=session_data["note"],
                    is_active=False,
                    allocation_mode=session_data["allocation_mode"],
                    allocations=allocations,
                )
                sessions_imported += 1
                continue

            fields = {
                "user": user,
                "project": project,
                "start_time": session_data["start"],
                "end_time": session_data["end"],
                "is_active": False,
                "note": session_data["note"],
                "allocation_mode": session_data["allocation_mode"],
            }
            if session_data["uuid"] is not None:
                fields["uuid"] = session_data["uuid"]
            SessionMutationService.create_session(allocations=allocations, **fields)
            sessions_imported += 1

    Commitment.objects.filter(user=user).update(needs_recompute=True)
    return {
        "projects_created": projects_created,
        "projects_updated": projects_updated,
        "sessions_imported": sessions_imported,
        "sessions_skipped": sessions_skipped,
        "conflicts": [],
    }
