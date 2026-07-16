from django.db import migrations


def floor_session_instants_and_recompute_totals(apps, schema_editor):
    Projects = apps.get_model("core", "Projects")
    Sessions = apps.get_model("core", "Sessions")
    SubProjects = apps.get_model("core", "SubProjects")

    completed_contributions = []
    for session in Sessions.objects.all().iterator():
        changed_fields = []
        for field_name in ("start_time", "end_time", "auto_stop_at"):
            value = getattr(session, field_name)
            if value is not None and value.microsecond:
                setattr(session, field_name, value.replace(microsecond=0))
                changed_fields.append(field_name)
        if changed_fields:
            session.save(update_fields=changed_fields)

        if not session.is_active and session.end_time is not None:
            minutes = round(
                (session.end_time - session.start_time).total_seconds() / 60.0,
                4,
            )
            completed_contributions.append(
                (
                    session.project_id,
                    list(session.subprojects.values_list("pk", flat=True)),
                    minutes,
                )
            )

    project_totals = {project.pk: 0 for project in Projects.objects.all()}
    subproject_totals = {
        subproject.pk: 0 for subproject in SubProjects.objects.all()
    }
    for project_id, subproject_ids, minutes in completed_contributions:
        project_totals[project_id] += minutes
        for subproject_id in subproject_ids:
            subproject_totals[subproject_id] += minutes

    projects = list(Projects.objects.all())
    for project in projects:
        project.total_time = project_totals[project.pk]
    Projects.objects.bulk_update(projects, ["total_time"])

    subprojects = list(SubProjects.objects.all())
    for subproject in subprojects:
        subproject.total_time = subproject_totals[subproject.pk]
    SubProjects.objects.bulk_update(subprojects, ["total_time"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0039_sessions_core_sessio_user_id_51a485_idx"),
    ]

    operations = [
        migrations.RunPython(
            floor_session_instants_and_recompute_totals,
            # Flooring is deliberately lossy and cannot be reversed.
            reverse_code=migrations.RunPython.noop,
        ),
    ]
