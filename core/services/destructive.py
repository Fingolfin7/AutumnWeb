"""Atomic destructive mutations for projects and their related metadata."""

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404

from core.models import (
    Commitment,
    Context,
    Projects,
    Sessions,
    SessionSubproject,
    SubProjects,
    Tag,
)


class DestructiveOperationError(Exception):
    """A destructive mutation failed a user-correctable validation."""


class CommitmentTargetProtectedError(DestructiveOperationError):
    """A destructive mutation would remove a commitment's target."""


def _ensure_unprotected(*, kind, target):
    if Commitment.objects.filter(**{kind: target}).exists():
        raise CommitmentTargetProtectedError(
            f"A commitment targets {kind} '{target.name}'. "
            "Re-point or delete that commitment first."
        )


def _mark_commitments_dirty(user):
    # This slice intentionally chooses the conservative user-wide invalidation.
    Commitment.objects.filter(user=user).update(needs_recompute=True)


class DestructiveMutationService:
    """The single atomic write path for destructive project mutations."""

    @staticmethod
    @transaction.atomic
    def merge_projects(*, user, project1_name, project2_name, new_project_name):
        if project1_name == project2_name:
            raise DestructiveOperationError("Cannot merge a project with itself")

        project1 = get_object_or_404(Projects, name=project1_name, user=user)
        project2 = get_object_or_404(Projects, name=project2_name, user=user)
        _ensure_unprotected(kind="project", target=project1)
        _ensure_unprotected(kind="project", target=project2)

        if Projects.objects.filter(user=user, name=new_project_name).exists():
            raise DestructiveOperationError(
                f'Project with name "{new_project_name}" already exists'
            )

        merged_description = (
            f"Merged from '{project1.name}' and '{project2.name}'\n\n"
        )
        if project1.description:
            merged_description += (
                f"--- {project1.name} Description ---\n{project1.description}\n\n"
            )
        if project2.description:
            merged_description += (
                f"--- {project2.name} Description ---\n{project2.description}\n\n"
            )
        merged_description = merged_description.strip()

        merged_project = Projects.objects.create(
            user=user,
            name=new_project_name,
            start_date=min(project1.start_date, project2.start_date),
            last_updated=max(project1.last_updated, project2.last_updated),
            status="active",
            description=merged_description,
        )

        for session in project1.sessions.all():
            session.project = merged_project
            session.version = (session.version or 1) + 1
            session.save(update_fields=["project", "version"])
        for session in project2.sessions.all():
            session.project = merged_project
            session.version = (session.version or 1) + 1
            session.save(update_fields=["project", "version"])

        project1_subprojects = list(project1.subprojects.all())
        project2_subprojects = list(project2.subprojects.all())
        existing_subproject_names = set()

        for subproject in project1_subprojects:
            original_name = subproject.name
            new_name = original_name
            if new_name in existing_subproject_names:
                new_name = f"{original_name} ({project1.name})"
                counter = 1
                while new_name in existing_subproject_names:
                    new_name = f"{original_name} ({project1.name}) {counter}"
                    counter += 1
            subproject.name = new_name
            subproject.parent_project = merged_project
            subproject.save(update_fields=["name", "parent_project"])
            existing_subproject_names.add(new_name)

        for subproject in project2_subprojects:
            original_name = subproject.name
            new_name = original_name
            if new_name in existing_subproject_names:
                new_name = f"{original_name} ({project2.name})"
                counter = 1
                while new_name in existing_subproject_names:
                    new_name = f"{original_name} ({project2.name}) {counter}"
                    counter += 1
            subproject.name = new_name
            subproject.parent_project = merged_project
            subproject.save(update_fields=["name", "parent_project"])
            existing_subproject_names.add(new_name)

        project1.delete()
        project2.delete()
        _mark_commitments_dirty(user)
        return merged_project, project1_subprojects + project2_subprojects

    @staticmethod
    @transaction.atomic
    def merge_subprojects(*, user, project_id, name1, name2, new_name):
        if name1 == name2:
            raise DestructiveOperationError("Cannot merge a subproject with itself")

        parent_project = get_object_or_404(Projects, id=project_id, user=user)
        subproject1 = get_object_or_404(
            SubProjects,
            name=name1,
            parent_project=parent_project,
            user=user,
        )
        subproject2 = get_object_or_404(
            SubProjects,
            name=name2,
            parent_project=parent_project,
            user=user,
        )
        _ensure_unprotected(kind="subproject", target=subproject1)
        _ensure_unprotected(kind="subproject", target=subproject2)

        if SubProjects.objects.filter(
            user=user, name=new_name, parent_project=parent_project
        ).exists():
            raise DestructiveOperationError(
                f'Subproject with name "{new_name}" already exists in this project'
            )

        source_ids = {subproject1.pk, subproject2.pk}
        # Postgres rejects FOR UPDATE with DISTINCT, so collect the ids first
        # and lock by pk. Safe: everything runs in this one transaction.
        affected_ids = list(
            Sessions.objects.filter(
                Q(subproject_links__subproject=subproject1)
                | Q(subproject_links__subproject=subproject2)
            )
            .values_list("pk", flat=True)
            .distinct()
        )
        affected_sessions = list(
            Sessions.objects.select_for_update()
            .filter(pk__in=affected_ids)
            .prefetch_related("subproject_links__subproject")
            .order_by("id")
        )
        offending_session_ids = []
        for session in affected_sessions:
            links = list(session.subproject_links.all())
            allocation_total = sum(link.allocation_bp for link in links)
            merged_bp = sum(
                link.allocation_bp
                for link in links
                if link.subproject_id in source_ids
            )
            invalid_links = any(
                not 1 <= link.allocation_bp <= 10000
                or link.subproject.user_id != session.user_id
                or link.subproject.parent_project_id != session.project_id
                for link in links
            )
            if invalid_links or allocation_total > 10000 or merged_bp > 10000:
                offending_session_ids.append(session.pk)
        if offending_session_ids:
            ids = ", ".join(map(str, offending_session_ids))
            raise DestructiveOperationError(
                f"Cannot merge subprojects; invalid partitioned allocations in sessions: {ids}"
            )

        merged_description = f"Merged from '{name1}' and '{name2}'\n\n"
        if subproject1.description:
            merged_description += (
                f"--- {name1} Description ---\n{subproject1.description}\n\n"
            )
        if subproject2.description:
            merged_description += (
                f"--- {name2} Description ---\n{subproject2.description}\n\n"
            )
        merged_description = merged_description.strip()

        merged_subproject = SubProjects.objects.create(
            user=user,
            name=new_name,
            parent_project=parent_project,
            start_date=min(subproject1.start_date, subproject2.start_date),
            last_updated=max(
                subproject1.last_updated, subproject2.last_updated
            ),
            description=merged_description,
        )

        for session in affected_sessions:
            links = list(session.subproject_links.all())
            retained = [
                (link.subproject, link.allocation_bp)
                for link in links
                if link.subproject_id not in source_ids
            ]
            merged_bp = sum(
                link.allocation_bp
                for link in links
                if link.subproject_id in source_ids
            )
            allocations = [*retained, (merged_subproject, merged_bp)]
            SessionSubproject.objects.filter(session=session).delete()
            SessionSubproject.objects.bulk_create(
                [
                    SessionSubproject(
                        session=session,
                        subproject=subproject,
                        allocation_bp=allocation_bp,
                    )
                    for subproject, allocation_bp in allocations
                ]
            )
            session.version = (session.version or 1) + 1
            session.save(update_fields=["version"])

        subproject1.delete()
        subproject2.delete()
        _mark_commitments_dirty(user)
        return merged_subproject

    @staticmethod
    @transaction.atomic
    def rename_project(*, user, project_name, new_name):
        project = get_object_or_404(Projects, name=project_name, user=user)
        if (
            Projects.objects.filter(user=user, name=new_name)
            .exclude(pk=project.pk)
            .exists()
        ):
            raise DestructiveOperationError("Project name already exists")
        project.name = new_name
        project.save(update_fields=["name"])
        _mark_commitments_dirty(user)
        return project

    @staticmethod
    @transaction.atomic
    def rename_subproject(*, user, project_name, subproject_name, new_name):
        project = get_object_or_404(Projects, name=project_name, user=user)
        subproject = get_object_or_404(
            SubProjects,
            parent_project=project,
            user=user,
            name=subproject_name,
        )
        if (
            SubProjects.objects.filter(
                user=user, parent_project=project, name=new_name
            )
            .exclude(pk=subproject.pk)
            .exists()
        ):
            raise DestructiveOperationError("Subproject name already exists")
        subproject.name = new_name
        subproject.save(update_fields=["name"])
        _mark_commitments_dirty(user)
        return subproject

    @staticmethod
    @transaction.atomic
    def delete_project(*, user, project_name):
        project = get_object_or_404(Projects, name=project_name, user=user)
        _ensure_unprotected(kind="project", target=project)
        project.delete()
        _mark_commitments_dirty(user)

    @staticmethod
    @transaction.atomic
    def delete_subproject(*, user, project_name, subproject_name):
        subproject = get_object_or_404(
            SubProjects,
            name=subproject_name,
            parent_project__name=project_name,
            user=user,
        )
        _ensure_unprotected(kind="subproject", target=subproject)
        subproject.delete()
        _mark_commitments_dirty(user)

    @staticmethod
    @transaction.atomic
    def delete_context(*, user, context_name):
        context = get_object_or_404(Context, user=user, name=context_name)
        _ensure_unprotected(kind="context", target=context)
        context.delete()
        _mark_commitments_dirty(user)

    @staticmethod
    @transaction.atomic
    def delete_tag(*, user, tag_name):
        tag = get_object_or_404(Tag, user=user, name=tag_name)
        _ensure_unprotected(kind="tag", target=tag)
        tag.delete()
        _mark_commitments_dirty(user)
