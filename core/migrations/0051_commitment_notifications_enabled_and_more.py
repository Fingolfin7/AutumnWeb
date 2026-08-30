import datetime
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0050_sessions_notify_on_auto_stop_notificationevent_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='commitment',
            name='notifications_enabled',
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.AddField(
            model_name='notificationevent',
            name='commitment',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='notification_events', to='core.commitment'),
        ),
        migrations.AlterField(
            model_name='notificationevent',
            name='event_type',
            field=models.CharField(choices=[('reminder', 'Timer reminder'), ('auto_stop', 'Auto-stop'), ('scheduled_reminder', 'Scheduled reminder'), ('commitment_check', 'Commitment check'), ('weekly_review', 'Weekly review')], max_length=20),
        ),
        migrations.CreateModel(
            name='NotificationPreference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('scheduled_reminders_enabled', models.BooleanField(db_default=True, default=True)),
                ('commitment_checks_enabled', models.BooleanField(db_default=False, default=False)),
                ('weekly_review_enabled', models.BooleanField(db_default=False, default=False)),
                ('commitment_check_time', models.TimeField(db_default=datetime.time(18, 0), default=datetime.time(18, 0))),
                ('weekly_review_weekday', models.PositiveSmallIntegerField(db_default=0, default=0)),
                ('weekly_review_time', models.TimeField(db_default=datetime.time(9, 0), default=datetime.time(9, 0))),
                ('next_commitment_check_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('next_weekly_review_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('version', models.PositiveIntegerField(db_default=1, default=1)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='notification_preferences', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['user_id'],
            },
        ),
        migrations.CreateModel(
            name='ScheduledReminder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message', models.TextField(blank=True, db_default='', default='')),
                ('cadence', models.CharField(choices=[('once', 'Once'), ('daily', 'Daily'), ('weekly', 'Weekly')], max_length=10)),
                ('timezone', models.CharField(max_length=64)),
                ('anchor_date', models.DateField()),
                ('anchor_time', models.TimeField()),
                ('next_fire_at', models.DateTimeField(blank=True, null=True)),
                ('active', models.BooleanField(db_default=True, default=True)),
                ('cancelled_at', models.DateTimeField(blank=True, null=True)),
                ('last_fired_at', models.DateTimeField(blank=True, null=True)),
                ('snoozed_until', models.DateTimeField(blank=True, null=True)),
                ('last_snoozed_at', models.DateTimeField(blank=True, null=True)),
                ('version', models.PositiveIntegerField(db_default=1, default=1)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='scheduled_reminders', to='core.projects')),
                ('subproject', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='scheduled_reminders', to='core.subprojects')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='scheduled_reminders', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['next_fire_at', 'id'],
            },
        ),
        migrations.AddField(
            model_name='notificationevent',
            name='scheduled_reminder',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='notification_events', to='core.scheduledreminder'),
        ),
        migrations.AddConstraint(
            model_name='notificationevent',
            constraint=models.CheckConstraint(condition=models.Q(('event_type__in', ('reminder', 'auto_stop', 'scheduled_reminder', 'commitment_check', 'weekly_review'))), name='notifyevent_type_valid'),
        ),
        migrations.AddConstraint(
            model_name='notificationpreference',
            constraint=models.CheckConstraint(condition=models.Q(('commitment_check_time__gte', datetime.time(18, 0)), ('commitment_check_time__lte', datetime.time(23, 59, 59))), name='notify_pref_commitment_time_valid'),
        ),
        migrations.AddConstraint(
            model_name='notificationpreference',
            constraint=models.CheckConstraint(condition=models.Q(('weekly_review_weekday__gte', 0), ('weekly_review_weekday__lte', 6)), name='notify_pref_weekday_valid'),
        ),
        migrations.AddConstraint(
            model_name='notificationpreference',
            constraint=models.CheckConstraint(condition=models.Q(('version__gte', 1)), name='notify_pref_version_positive'),
        ),
        migrations.AddIndex(
            model_name='scheduledreminder',
            index=models.Index(fields=['active', 'next_fire_at', 'id'], name='schedrem_due_idx'),
        ),
        migrations.AddIndex(
            model_name='scheduledreminder',
            index=models.Index(fields=['user', 'active', 'id'], name='schedrem_user_active_idx'),
        ),
        migrations.AddConstraint(
            model_name='scheduledreminder',
            constraint=models.CheckConstraint(condition=models.Q(('cadence__in', ('once', 'daily', 'weekly'))), name='schedrem_cadence_valid'),
        ),
        migrations.AddConstraint(
            model_name='scheduledreminder',
            constraint=models.CheckConstraint(condition=models.Q(('active', True), ('next_fire_at__isnull', True), _negated=True), name='schedrem_active_next_fire_valid'),
        ),
        migrations.AddConstraint(
            model_name='scheduledreminder',
            constraint=models.CheckConstraint(condition=models.Q(('version__gte', 1)), name='schedrem_version_positive'),
        ),
    ]
