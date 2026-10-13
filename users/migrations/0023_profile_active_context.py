from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0059_session_passage_embeddings"),
        ("users", "0022_expand_luna_reasoning_effort"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="active_context",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="+",
                to="core.context",
            ),
        ),
    ]
