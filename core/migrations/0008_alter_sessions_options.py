# Generated by Django 4.2 on 2024-06-14 00:04

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_alter_projects_options'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='sessions',
            options={'ordering': ['-end_time'], 'verbose_name_plural': 'Sessions'},
        ),
    ]