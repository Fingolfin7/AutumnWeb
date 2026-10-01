from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0020_profile_typesafe_api_key_enc")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="luna_recommendation_effort",
            field=models.CharField(
                choices=[("high", "High"), ("xhigh", "xHigh")],
                db_default="xhigh", default="xhigh", max_length=5,
            ),
        ),
    ]
