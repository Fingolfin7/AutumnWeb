# Generated by Django 4.2.15 on 2024-11-21 03:49

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0023_remove_sessions_core_sessio_is_acti_801316_idx_and_more'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='sessions',
            index=models.Index(fields=['is_active', 'end_time'], name='core_sessio_is_acti_801316_idx'),
        ),
        migrations.AddIndex(
            model_name='sessions',
            index=models.Index(fields=['user', 'project'], name='core_sessio_user_id_509018_idx'),
        ),
    ]
