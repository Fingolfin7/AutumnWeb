"""Shared project/session JSON import implementation."""

from datetime import datetime, timedelta

from django.utils import timezone

from .models import Commitment, Projects, Sessions, SubProjects, status_choices
from .services import DestructiveMutationService
from .totals import derived_project_last_updated, derived_project_totals
from .importer2 import import_format2
from .utils import (
    apply_context_and_tags_to_project,
    session_exists,
    sessions_get_earliest_latest,
)


def _iter_import_format1(
    user,
    data: dict,
    *,
    force=False,
    merge=False,
    tolerance=2,
    verbose=False,
    autumn_import=False,
    import_into_context=None,
):
    """Import exported project data for ``user``, yielding progress messages.

    Generator: yields the same human-readable messages the streaming import
    view reports to the browser, as they happen. Its return value (available
    via ``StopIteration.value`` or the ``run_import`` wrapper) is the import
    summary dict.
    """
    skipped = []
    projects_created = 0
    projects_updated = 0
    sessions_imported = 0

    total_projects = len(data.items())
    for idx, (project_name, project_data) in enumerate(data.items(), 1):
        yield (f"Processing project {idx}/{total_projects}: {project_name}")

        project = Projects.objects.filter(name=project_name, user=user).first()

        if project:
            if force:
                yield (
                    f"Force option enabled - deleting existing project '{project_name}'"
                )
                # Only delete projects belonging to the current user to avoid
                # removing other users' projects.
                DestructiveMutationService.delete_project(
                    user=user, project_name=project_name
                )
                project = None
            elif merge:
                projects_updated += 1
                if verbose:
                    yield (
                        f"Merging new sessions and subprojects into '{project_name}'..."
                    )
            else:
                skipped.append(project_name)
                yield (f"Skipping existing project: {project_name}")
                continue

        if not project:
            project = Projects.objects.create(
                user=user,
                name=project_name,
                start_date=timezone.make_aware(
                    datetime.strptime(project_data["Start Date"], "%m-%d-%Y")
                ),
                last_updated=timezone.make_aware(
                    datetime.strptime(project_data["Last Updated"], "%m-%d-%Y")
                ),
                description=project_data["Description"]
                if "Description" in project_data
                else "",
                context=import_into_context,
            )
            projects_created += 1

            if "Status" in project_data:
                # Handle old versions from before the status field was added.
                status_tuple = next(
                    (
                        status
                        for status in status_choices
                        if status[0] == project_data["Status"]
                    ),
                    None,
                )

                if status_tuple:
                    project.status = status_tuple[0]
                else:
                    raise ValueError(f"Invalid status: {project_data['Status']}")
            project.save(update_fields=["status"])

        # Apply context/tags (backwards compatible). If importing into a
        # context, don't let the file override it.
        if import_into_context is not None:
            sanitized_project_data = dict(project_data)
            sanitized_project_data.pop("Context", None)
        else:
            sanitized_project_data = project_data

        apply_context_and_tags_to_project(
            user=user,
            project=project,
            project_data=sanitized_project_data,
            merge=bool(
                merge
                and Projects.objects.filter(
                    name=project_name,
                    user=user,
                ).exists()
            ),
        )

        # Existing project + merge: optionally force it under the chosen context.
        if merge and project is not None and import_into_context is not None:
            project.context = import_into_context
            project.save(update_fields=["context"])

        # Process subprojects.
        total_subprojects = len(project_data["Sub Projects"])
        project_latest_activity = derived_project_last_updated(
            user, [project.pk]
        )[project.pk]

        if verbose and total_subprojects > 0:
            yield (f"Processing {total_subprojects} subprojects for {project_name}")

        for subproject_name, subproject_time in project_data["Sub Projects"].items():
            subproject_name_lower = subproject_name.lower()
            if autumn_import:
                subproject, created = SubProjects.objects.get_or_create(
                    user=user,
                    name=subproject_name_lower,
                    parent_project=project,
                    defaults={
                        "start_date": project.start_date,
                        "last_updated": project_latest_activity,
                        "total_time": 0.0,
                        "description": "",
                    },
                )
            else:
                subproject, created = SubProjects.objects.get_or_create(
                    user=user,
                    name=subproject_name_lower,
                    parent_project=project,
                    defaults={
                        "start_date": timezone.make_aware(
                            datetime.strptime(
                                project_data["Sub Projects"][subproject_name][
                                    "Start Date"
                                ],
                                "%m-%d-%Y",
                            )
                        ),
                        "last_updated": timezone.make_aware(
                            datetime.strptime(
                                project_data["Sub Projects"][subproject_name][
                                    "Last Updated"
                                ],
                                "%m-%d-%Y",
                            )
                        ),
                        "description": project_data["Sub Projects"][subproject_name][
                            "Description"
                        ]
                        if "Description" in project_data["Sub Projects"][subproject_name]
                        else "",
                    },
                )

            if created and verbose:
                yield (
                    f"Created new subproject '{subproject_name}' under project "
                    f"'{project_name}'"
                )

        # Process sessions.
        total_sessions = len(project_data["Session History"])
        yield (f"Processing {total_sessions} sessions for {project_name}")

        for session_idx, session_data in enumerate(project_data["Session History"], 1):
            start_time = timezone.make_aware(
                datetime.strptime(
                    f"{session_data['Date']} {session_data['Start Time']}",
                    "%m-%d-%Y %H:%M:%S",
                )
            )
            end_time = timezone.make_aware(
                datetime.strptime(
                    f"{session_data['Date']} {session_data['End Time']}",
                    "%m-%d-%Y %H:%M:%S",
                )
            )

            subproject_names = [
                name.lower() for name in session_data["Sub-Projects"]
            ]
            note = session_data["Note"]

            if end_time < start_time:
                start_time -= timedelta(days=1)

            if session_exists(
                user,
                project,
                start_time,
                end_time,
                subproject_names,
                time_tolerance=timedelta(minutes=tolerance),
            ):
                continue

            if verbose:
                yield (
                    f"Importing session on {session_data['Date']} from "
                    f"{session_data['Start Time']} to {session_data['End Time']}..."
                )

            session = Sessions.objects.create(
                user=user,
                project=project,
                start_time=start_time,
                end_time=end_time,
                is_active=False,
                note=note,
            )
            sessions_imported += 1

            for subproject_name in subproject_names:
                try:
                    subproject = SubProjects.objects.get(
                        user=user, name=subproject_name, parent_project=project
                    )
                    session.subprojects.add(subproject)
                except SubProjects.DoesNotExist:
                    yield (
                        f"Warning: Subproject not found: {subproject_name}. Subproject "
                        f"will not be added to session."
                    )
                    continue

            session.full_clean()
            session.save()
            Commitment.objects.filter(user=user).update(needs_recompute=True)

        yield ("\n\n")

        sessions = Sessions.objects.filter(project=project, user=user)
        earliest_start, latest_end = sessions_get_earliest_latest(sessions)

        if merge and earliest_start and latest_end:
            project.start_date = earliest_start
            project.save(update_fields=["start_date"])

            for subproject in project.subprojects.all():
                earliest_start, latest_end = sessions_get_earliest_latest(
                    subproject.sessions.all()
                )
                subproject.start_date = (
                    earliest_start if earliest_start else project.start_date
                )
                subproject.save(update_fields=["start_date"])

        # Imports may also change project/context metadata without writing a
        # session, so conservatively invalidate every commitment for the user.
        Commitment.objects.filter(user=user).update(needs_recompute=True)

        if not merge:
            tally = derived_project_totals(user, [project.pk])[project.pk]
            mismatch = abs(tally - project_data["Total Time"])
            if mismatch > tolerance:
                DestructiveMutationService.delete_project(
                    user=user, project_name=project.name
                )
                yield (
                    f"Error: Total time mismatch for project '{project_name}': "
                    f"expected {project_data['Total Time']}, got {tally}. "
                    f"Mismatch: {mismatch}"
                )
                return {
                    "projects_processed": idx,
                    "projects_created": projects_created,
                    "projects_updated": projects_updated,
                    "sessions_imported": sessions_imported,
                    "skipped": skipped,
                }

    if skipped:
        yield (f"Import completed with skipped projects: {', '.join(skipped)}")
    else:
        yield ("Import completed successfully!")

    return {
        "projects_processed": total_projects,
        "projects_created": projects_created,
        "projects_updated": projects_updated,
        "sessions_imported": sessions_imported,
        "skipped": skipped,
    }


def iter_import(
    user,
    data: dict,
    *,
    force=False,
    merge=False,
    tolerance=2,
    verbose=False,
    autumn_import=False,
    import_into_context=None,
):
    """Detect the portable envelope while preserving legacy format-1 behavior."""
    if isinstance(data, dict) and data.get("format") == 2:
        yield "Validating format-2 import batch"
        summary = import_format2(
            user,
            data,
            force=force,
            import_into_context=import_into_context,
        )
        yield "Import completed successfully!"
        return summary
    return (
        yield from _iter_import_format1(
            user,
            data,
            force=force,
            merge=merge,
            tolerance=tolerance,
            verbose=verbose,
            autumn_import=autumn_import,
            import_into_context=import_into_context,
        )
    )


def run_import(
    user,
    data: dict,
    *,
    force=False,
    merge=False,
    tolerance=2,
    verbose=False,
    autumn_import=False,
    import_into_context=None,
    progress=None,
) -> dict:
    """Non-streaming wrapper around ``iter_import``.

    Consumes the generator, forwarding each progress message to the optional
    ``progress`` callable, and returns the import summary dict.
    """
    gen = iter_import(
        user,
        data,
        force=force,
        merge=merge,
        tolerance=tolerance,
        verbose=verbose,
        autumn_import=autumn_import,
        import_into_context=import_into_context,
    )
    while True:
        try:
            message = next(gen)
        except StopIteration as stop:
            return stop.value
        if progress is not None:
            progress(message)
