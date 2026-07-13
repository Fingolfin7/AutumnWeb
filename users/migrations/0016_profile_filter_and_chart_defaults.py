from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0015_profile_ai_features_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="default_chart_project_count",
            field=models.PositiveSmallIntegerField(
                default=7,
                help_text="Number of projects shown individually before the remainder are grouped as Other.",
                validators=[MinValueValidator(1), MaxValueValidator(100)],
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="default_filter_unit",
            field=models.CharField(
                choices=[
                    ("days", "Days"),
                    ("weeks", "Weeks"),
                    ("months", "Months"),
                    ("years", "Years"),
                ],
                default="months",
                max_length=6,
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="default_filter_value",
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text="How far the default date filter looks back from today.",
                validators=[MinValueValidator(1), MaxValueValidator(1000)],
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="insights_default_filter_unit",
            field=models.CharField(
                choices=[
                    ("days", "Days"),
                    ("weeks", "Weeks"),
                    ("months", "Months"),
                    ("years", "Years"),
                ],
                default="months",
                max_length=6,
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="insights_default_filter_value",
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text="How far the default Insights date filter looks back from today.",
                validators=[MinValueValidator(1), MaxValueValidator(1000)],
            ),
        ),
    ]
