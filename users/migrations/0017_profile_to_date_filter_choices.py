from django.db import migrations, models


FILTER_UNIT_CHOICES = [
    ("days", "Days"),
    ("weeks", "Weeks"),
    ("months", "Months"),
    ("years", "Years"),
    ("month_to_date", "Month to date"),
    ("quarter_to_date", "Quarter to date"),
    ("year_to_date", "Year to date"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0016_profile_filter_and_chart_defaults"),
    ]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="default_filter_unit",
            field=models.CharField(
                choices=FILTER_UNIT_CHOICES,
                default="months",
                max_length=15,
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="insights_default_filter_unit",
            field=models.CharField(
                choices=FILTER_UNIT_CHOICES,
                default="months",
                max_length=15,
            ),
        ),
    ]
