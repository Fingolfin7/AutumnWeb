from django.db import migrations, models


class Migration(migrations.Migration):
    # These tables contain only thousands of rows. Plain AddIndex is deliberate;
    # PostgreSQL CONCURRENTLY is deferred until the later benchmark slice.
    atomic = False

    dependencies = [
        ("core", "0042_adopt_session_subproject_allocations"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="sessions",
            index=models.Index(
                fields=["user", "start_time", "id"],
                name="sess_active_user_start_idx",
                condition=models.Q(end_time__isnull=True),
            ),
        ),
        migrations.AddIndex(
            model_name="sessions",
            index=models.Index(
                fields=["user", "auto_stop_at", "id"],
                name="sess_autostop_partial_idx",
                condition=models.Q(
                    end_time__isnull=True,
                    auto_stop_at__isnull=False,
                ),
            ),
        ),
        migrations.AddIndex(
            model_name="sessions",
            index=models.Index(
                fields=["user", "end_time", "id"],
                name="sess_completed_user_end_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="sessions",
            index=models.Index(
                fields=["user", "project", "end_time", "id"],
                name="sess_completed_proj_end_idx",
            ),
        ),
    ]
