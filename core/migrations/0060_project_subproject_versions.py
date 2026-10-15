from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0059_session_passage_embeddings"),
    ]

    operations = [
        migrations.AddField(
            model_name="projects",
            name="version",
            field=models.IntegerField(db_default=1, default=1),
        ),
        migrations.AddField(
            model_name="subprojects",
            name="version",
            field=models.IntegerField(db_default=1, default=1),
        ),
    ]
