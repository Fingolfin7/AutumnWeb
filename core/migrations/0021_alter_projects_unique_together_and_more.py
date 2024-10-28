# Generated by Django 4.2.15 on 2024-10-26 01:07

from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0020_alter_projects_name'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='projects',
            unique_together={('user', 'name')},
        ),
        migrations.AlterUniqueTogether(
            name='subprojects',
            unique_together={('name', 'parent_project')},
        ),
    ]