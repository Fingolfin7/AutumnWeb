from django.db import migrations, models
from django.utils import timezone


def backfill_crosses_dst_transition(apps, schema_editor):
    Sessions = apps.get_model("core", "Sessions")
    default_tz = timezone.get_default_timezone()

    for session in Sessions.objects.all().iterator():
        if not session.start_time or not session.end_time:
            crosses = False
        else:
            start_local = timezone.localtime(session.start_time, default_tz)
            end_local = timezone.localtime(session.end_time, default_tz)
            crosses = start_local.utcoffset() != end_local.utcoffset()

        if session.crosses_dst_transition != crosses:
            session.crosses_dst_transition = crosses
            session.save(update_fields=["crosses_dst_transition"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0032_commitment"),
    ]

    operations = [
        migrations.AddField(
            model_name="sessions",
            name="crosses_dst_transition",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            backfill_crosses_dst_transition,
            migrations.RunPython.noop,
        ),
    ]
