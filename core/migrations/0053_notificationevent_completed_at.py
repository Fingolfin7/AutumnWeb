from django.db import migrations, models
from django.utils import timezone


TERMINAL_STATUSES = ("delivered", "unavailable", "failed", "cancelled")


def backfill_completed_at(apps, schema_editor):
    NotificationEvent = apps.get_model("core", "NotificationEvent")
    # Preserve existing history: migration time is the first trustworthy
    # completion timestamp for rows created before this field existed.
    NotificationEvent.objects.using(schema_editor.connection.alias).filter(
        status__in=TERMINAL_STATUSES, completed_at__isnull=True
    ).update(completed_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [("core", "0052_remove_scheduledreminder_subproject_and_more")]

    operations = [
        migrations.AddField(
            model_name="notificationevent",
            name="completed_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(backfill_completed_at, migrations.RunPython.noop),
    ]
