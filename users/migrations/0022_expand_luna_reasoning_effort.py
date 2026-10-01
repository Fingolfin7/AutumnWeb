from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0021_profile_luna_recommendation_effort")]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="luna_recommendation_effort",
            field=models.CharField(
                choices=[("low", "Low"), ("medium", "Medium"), ("high", "High"),
                         ("xhigh", "xHigh"), ("max", "Max")],
                db_default="xhigh", default="xhigh", max_length=6,
            ),
        ),
    ]
