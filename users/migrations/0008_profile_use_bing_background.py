# Generated by Django 5.2 on 2025-07-17 21:49

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0007_profile_background_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='use_bing_background',
            field=models.BooleanField(default=False),
        ),
    ]
