import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0048_remove_sessions_allocation_mode"),
    ]

    operations = [
        migrations.AlterField(
            model_name="commitmentperiod",
            name="revision",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="period_rows",
                to="core.commitmentrevision",
            ),
        ),
    ]
