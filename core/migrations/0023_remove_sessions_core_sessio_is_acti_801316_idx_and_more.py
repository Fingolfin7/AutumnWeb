# Generated by Django 4.2.15 on 2024-11-21 03:36

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_sessions_core_sessio_is_acti_801316_idx_and_more'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='sessions',
            name='core_sessio_is_acti_801316_idx',
        ),
        migrations.RemoveIndex(
            model_name='sessions',
            name='core_sessio_user_id_509018_idx',
        ),
    ]
