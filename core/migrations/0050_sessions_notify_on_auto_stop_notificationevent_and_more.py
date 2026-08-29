import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0049_alter_commitmentperiod_revision"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="sessions",
            name="notify_on_auto_stop",
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.CreateModel(
            name="NotificationEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("dedupe_key", models.CharField(max_length=255, unique=True)),
                (
                    "event_type",
                    models.CharField(
                        choices=[("reminder", "Timer reminder"), ("auto_stop", "Auto-stop")],
                        max_length=20,
                    ),
                ),
                ("payload", models.JSONField(default=dict)),
                ("scheduled_at", models.DateTimeField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("processing", "Processing"),
                            ("delivered", "Delivered"),
                            ("unavailable", "Unavailable"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(db_default=0, default=0)),
                ("next_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("lease_until", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, db_default="", default="")),
                ("last_error_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                (
                    "session",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="notification_events",
                        to="core.sessions",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["scheduled_at", "id"]},
        ),
        migrations.CreateModel(
            name="PushSubscription",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("endpoint", models.URLField(max_length=2048, unique=True)),
                ("p256dh", models.CharField(max_length=255)),
                ("auth", models.CharField(max_length=255)),
                ("expiration_time", models.DateTimeField(blank=True, null=True)),
                ("active", models.BooleanField(db_default=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("disabled_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, db_default="", default="")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="push_subscriptions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-updated_at", "-id"]},
        ),
        migrations.CreateModel(
            name="NotificationDelivery",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("processing", "Processing"),
                            ("delivered", "Delivered"),
                            ("expired", "Expired"),
                            ("unavailable", "Unavailable"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(db_default=0, default=0)),
                ("next_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("lease_until", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, db_default="", default="")),
                ("last_error_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deliveries",
                        to="core.notificationevent",
                    ),
                ),
                (
                    "subscription",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deliveries",
                        to="core.pushsubscription",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="TimerReminder",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "mode",
                    models.CharField(
                        choices=[
                            ("after", "Once after"),
                            ("at", "At"),
                            ("interval", "Every"),
                        ],
                        max_length=16,
                    ),
                ),
                ("next_fire_at", models.DateTimeField(blank=True, null=True)),
                ("interval_seconds", models.PositiveIntegerField(blank=True, null=True)),
                ("message", models.TextField(blank=True, db_default="", default="")),
                ("active", models.BooleanField(db_default=True, default=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("last_fired_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reminders",
                        to="core.sessions",
                    ),
                ),
            ],
            options={"ordering": ["next_fire_at", "id"]},
        ),
        migrations.AddField(
            model_name="notificationevent",
            name="reminder",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="notification_events",
                to="core.timerreminder",
            ),
        ),
        migrations.AddIndex(
            model_name="pushsubscription",
            index=models.Index(
                fields=["user", "active", "id"], name="pushsub_user_active_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="notificationdelivery",
            index=models.Index(
                fields=["status", "next_attempt_at", "id"],
                name="notifydelivery_due_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="notificationdelivery",
            constraint=models.UniqueConstraint(
                fields=("event", "subscription"),
                name="unique_notification_event_subscription",
            ),
        ),
        migrations.AddConstraint(
            model_name="notificationdelivery",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "pending",
                        "processing",
                        "delivered",
                        "expired",
                        "unavailable",
                        "failed",
                    )
                ),
                name="notifydelivery_status_valid",
            ),
        ),
        migrations.AddIndex(
            model_name="timerreminder",
            index=models.Index(
                fields=["active", "next_fire_at", "id"], name="timerrem_due_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="timerreminder",
            index=models.Index(
                fields=["session", "active", "id"], name="timerrem_session_active_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="timerreminder",
            constraint=models.CheckConstraint(
                condition=models.Q(mode__in=("after", "at", "interval")),
                name="timerrem_mode_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="timerreminder",
            constraint=models.CheckConstraint(
                condition=(
                    (
                        models.Q(mode="interval")
                        & models.Q(interval_seconds__isnull=False)
                        & models.Q(interval_seconds__gt=0)
                    )
                    | (
                        ~models.Q(mode="interval")
                        & models.Q(interval_seconds__isnull=True)
                    )
                ),
                name="timerrem_interval_seconds_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="timerreminder",
            constraint=models.CheckConstraint(
                condition=~models.Q(active=True, next_fire_at__isnull=True),
                name="timerrem_active_next_fire_valid",
            ),
        ),
        migrations.AddIndex(
            model_name="notificationevent",
            index=models.Index(
                fields=["status", "next_attempt_at", "id"], name="notifyevent_due_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="notificationevent",
            index=models.Index(
                fields=["user", "scheduled_at", "id"], name="notifyevent_user_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="notificationevent",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "pending",
                        "processing",
                        "delivered",
                        "unavailable",
                        "failed",
                        "cancelled",
                    )
                ),
                name="notifyevent_status_valid",
            ),
        ),
    ]
