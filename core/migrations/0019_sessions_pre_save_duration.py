# Generated by Django 4.2.15 on 2024-09-28 15:22

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_alter_projects_user_alter_sessions_user_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='sessions',
            name='pre_save_duration',
            field=models.FloatField(default=0.0),
        ),
    ]
