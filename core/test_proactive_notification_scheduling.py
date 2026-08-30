from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from freezegun import freeze_time

from core.models import NotificationEvent, NotificationPreference, Projects
from core.services import CommitmentEditService, SessionMutationService
from core.services.proactive_notifications import (
    _weekly_review_event,
    claim_due_commitment_checks,
    claim_due_proactive_notifications,
    claim_due_scheduled_reminders,
    claim_due_weekly_reviews,
    create_scheduled_reminder,
    ensure_notification_preferences,
    local_wall_to_utc,
    snooze_scheduled_reminder,
    weekly_review_summary,
)


UTC = dt_timezone.utc


class ScheduledNotificationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("planned-user", password="password")
        self.user.profile.timezone = "Europe/Prague"
        self.user.profile.save(update_fields=["timezone"])
        self.project = Projects.objects.create(user=self.user, name="Gym")

    def create(self, **overrides):
        values = {
            "user": self.user,
            "project": self.project,
            "local_date": date(2026, 1, 5),
            "local_time": time(18, 30),
            "cadence": "once",
            "now": datetime(2026, 1, 1, 12, tzinfo=UTC),
        }
        values.update(overrides)
        return create_scheduled_reminder(**values)

    def test_strict_user_time_rejects_gap_while_recurrence_resolves_it(self):
        wall = datetime(2026, 3, 29, 2, 30)
        with self.assertRaises(ValidationError):
            local_wall_to_utc(wall, "Europe/Prague", strict=True)
        resolved = local_wall_to_utc(wall, "Europe/Prague", strict=False)
        self.assertEqual(resolved, datetime(2026, 3, 29, 1, 0, tzinfo=UTC))

    def test_one_shot_claim_creates_actionable_deduplicated_event(self):
        reminder = self.create()
        occurrence = datetime(2026, 1, 5, 17, 30, tzinfo=UTC)

        first = claim_due_scheduled_reminders(now=occurrence)
        second = claim_due_scheduled_reminders(now=occurrence)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        event = first[0]
        self.assertEqual(event.event_type, "scheduled_reminder")
        self.assertEqual(event.scheduled_reminder_id, reminder.pk)
        self.assertEqual(event.payload["body"], "You planned Gym for 18:30.")
        self.assertEqual(
            [action["title"] for action in event.payload["actions"]],
            ["Start timer", "Snooze"],
        )
        reminder.refresh_from_db()
        self.assertFalse(reminder.active)
        self.assertIsNone(reminder.next_fire_at)

    def test_paused_category_advances_without_delivering_stale_one_shot(self):
        reminder = self.create()
        preference = ensure_notification_preferences(self.user)
        preference.scheduled_reminders_enabled = False
        preference.save(update_fields=["scheduled_reminders_enabled"])

        events = claim_due_scheduled_reminders(
            now=datetime(2026, 1, 5, 17, 30, tzinfo=UTC)
        )

        self.assertEqual(events, [])
        reminder.refresh_from_db()
        self.assertFalse(reminder.active)
        self.assertFalse(
            NotificationEvent.objects.filter(scheduled_reminder=reminder).exists()
        )

    def test_snoozed_daily_occurrence_returns_to_anchor_cadence(self):
        reminder = self.create(cadence="daily")
        now = datetime(2026, 1, 5, 17, 25, tzinfo=UTC)
        snooze_scheduled_reminder(
            user=self.user,
            reminder_id=reminder.pk,
            version=reminder.version,
            choice="15m",
            now=now,
        )
        reminder.refresh_from_db()
        self.assertEqual(reminder.next_fire_at, now + timedelta(minutes=15))

        events = claim_due_scheduled_reminders(now=now + timedelta(minutes=15))

        self.assertEqual(len(events), 1)
        reminder.refresh_from_db()
        self.assertEqual(
            reminder.next_fire_at,
            datetime(2026, 1, 6, 17, 30, tzinfo=UTC),
        )
        self.assertIsNone(reminder.snoozed_until)


class CommitmentAndReviewClaimTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("review-user", password="password")
        self.user.profile.timezone = "UTC"
        self.user.profile.save(update_fields=["timezone"])
        self.project = Projects.objects.create(user=self.user, name="Exercise")

    def create_daily_commitment(self, project):
        commitment = CommitmentEditService.create(
            self.user,
            {
                "aggregation_type": "project",
                "project": project,
                "commitment_type": "sessions",
                "period": "daily",
                "start_date": date(2026, 1, 1),
                "target": 1,
                "banking_enabled": False,
                "max_balance": 0,
                "min_balance": 0,
            },
        )
        commitment.notifications_enabled = True
        commitment.save(update_fields=["notifications_enabled"])
        return commitment

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_due_commitment_check_uses_canonical_remaining_and_deadline(self):
        commitment = CommitmentEditService.create(
            self.user,
            {
                "aggregation_type": "project",
                "project": self.project,
                "commitment_type": "sessions",
                "period": "daily",
                "start_date": date(2026, 1, 1),
                "target": 2,
                "banking_enabled": False,
                "max_balance": 0,
                "min_balance": 0,
            },
        )
        commitment.notifications_enabled = True
        commitment.save(update_fields=["notifications_enabled"])
        SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=datetime(2026, 1, 1, 15, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 16, tzinfo=UTC),
            is_active=False,
        )
        preference = NotificationPreference.objects.create(
            user=self.user,
            commitment_checks_enabled=True,
            next_commitment_check_at=datetime(2026, 1, 1, 18, tzinfo=UTC),
        )

        with freeze_time("2026-01-01 18:00:00+00:00"):
            events = claim_due_commitment_checks(
                now=datetime(2026, 1, 1, 18, tzinfo=UTC)
            )

        self.assertEqual(len(events), 1)
        self.assertIn("1 session remaining", events[0].payload["body"])
        self.assertIn("period ends Thursday", events[0].payload["body"])
        preference.refresh_from_db()
        self.assertEqual(
            preference.next_commitment_check_at,
            datetime(2026, 1, 2, 18, tzinfo=UTC),
        )

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_commitment_event_limit_keeps_partially_emitted_occurrence_due(self):
        second_project = Projects.objects.create(user=self.user, name="Study")
        self.create_daily_commitment(self.project)
        self.create_daily_commitment(second_project)
        occurrence = datetime(2026, 1, 1, 18, tzinfo=UTC)
        preference = NotificationPreference.objects.create(
            user=self.user,
            commitment_checks_enabled=True,
            next_commitment_check_at=occurrence,
        )

        first = claim_due_commitment_checks(now=occurrence, limit=1)

        self.assertEqual(len(first), 1)
        self.assertEqual(
            NotificationEvent.objects.filter(event_type="commitment_check").count(),
            1,
        )
        preference.refresh_from_db()
        self.assertEqual(preference.next_commitment_check_at, occurrence)

        second = claim_due_commitment_checks(now=occurrence, limit=1)

        self.assertEqual(len(second), 1)
        self.assertEqual(
            NotificationEvent.objects.filter(event_type="commitment_check").count(),
            2,
        )
        preference.refresh_from_db()
        self.assertEqual(
            preference.next_commitment_check_at,
            datetime(2026, 1, 2, 18, tzinfo=UTC),
        )

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_combined_claimer_gives_each_due_category_a_turn(self):
        self.create_daily_commitment(self.project)
        occurrence = datetime(2026, 1, 1, 18, tzinfo=UTC)
        reminder = create_scheduled_reminder(
            user=self.user,
            project=self.project,
            local_date=date(2026, 1, 1),
            local_time=time(18),
            cadence="once",
            now=datetime(2026, 1, 1, 12, tzinfo=UTC),
        )
        preference = NotificationPreference.objects.get(user=self.user)
        preference.commitment_checks_enabled = True
        preference.next_commitment_check_at = occurrence
        preference.weekly_review_enabled = True
        preference.weekly_review_weekday = 3
        preference.weekly_review_time = time(18)
        preference.next_weekly_review_at = occurrence
        preference.save()

        events = claim_due_proactive_notifications(now=occurrence, limit=3)

        self.assertEqual(len(events), 3)
        self.assertEqual(
            [event.event_type for event in events],
            ["scheduled_reminder", "commitment_check", "weekly_review"],
        )
        self.assertEqual(
            NotificationEvent.objects.filter(
                scheduled_reminder_id=reminder.pk
            ).count(),
            1,
        )

    @freeze_time("2026-01-12 09:00:00+00:00")
    def test_weekly_review_claim_uses_completed_local_days_and_project_count(self):
        SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=datetime(2026, 1, 8, 10, tzinfo=UTC),
            end_time=datetime(2026, 1, 8, 11, 15, tzinfo=UTC),
            is_active=False,
        )
        preference = NotificationPreference.objects.create(
            user=self.user,
            weekly_review_enabled=True,
            next_weekly_review_at=datetime(2026, 1, 12, 9, tzinfo=UTC),
        )

        summary = weekly_review_summary(
            preference, datetime(2026, 1, 12, 9, tzinfo=UTC)
        )
        events = claim_due_weekly_reviews(
            now=datetime(2026, 1, 12, 9, tzinfo=UTC)
        )

        self.assertEqual(summary["total_minutes"], 75)
        self.assertEqual(summary["project_count"], 1)
        self.assertEqual(len(events), 1)
        self.assertIn("1h 15m across 1 project", events[0].payload["body"])
        self.assertIn("0 of 0 commitments met", events[0].payload["body"])

    def test_weekly_review_dedupe_key_uses_local_week_start(self):
        preference = NotificationPreference.objects.create(
            user=self.user,
            weekly_review_enabled=True,
        )
        summary = {
            "total_minutes": 0,
            "project_count": 0,
            "met_count": 0,
            "eligible_count": 0,
            "window_start": datetime(2026, 1, 5, tzinfo=UTC),
            "window_end": datetime(2026, 1, 12, tzinfo=UTC),
            "timezone": "UTC",
        }
        first, first_created = _weekly_review_event(
            preference,
            datetime(2026, 1, 12, 9, tzinfo=UTC),
            summary,
        )

        # A timezone/DST representation can have different UTC bounds while
        # still referring to the same local Monday-start review week.
        summary["window_start"] = datetime(2026, 1, 4, 23, tzinfo=UTC)
        summary["window_end"] = datetime(2026, 1, 11, 23, tzinfo=UTC)
        summary["timezone"] = "Europe/Prague"
        second, second_created = _weekly_review_event(
            preference,
            datetime(2026, 1, 12, 9, tzinfo=UTC),
            summary,
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(
            first.dedupe_key,
            f"weekly-review:{self.user.pk}:2026-01-05",
        )
        self.assertEqual(
            NotificationEvent.objects.filter(event_type="weekly_review").count(),
            1,
        )
