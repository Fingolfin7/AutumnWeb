from datetime import date, datetime, time, timezone as dt_timezone

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Commitment,
    Context,
    NotificationEvent,
    Projects,
    ScheduledReminder,
    SubProjects,
    Tag,
)


class ProactiveNotificationModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "notifications", email="notifications@example.test", password="password"
        )
        self.other = User.objects.create_user(
            "other-notifications",
            email="other-notifications@example.test",
            password="password",
        )
        self.project = Projects.objects.create(user=self.user, name="Focused work")
        self.other_project = Projects.objects.create(user=self.other, name="Other work")
        self.subproject = SubProjects.objects.create(
            user=self.user,
            name="Preparation",
            parent_project=self.project,
        )
        self.fire_at = datetime(2026, 8, 30, 16, 30, tzinfo=dt_timezone.utc)

    def reminder(self, **overrides):
        values = {
            "user": self.user,
            "project": self.project,
            "cadence": "once",
            "timezone": "Europe/Prague",
            "anchor_date": date(2026, 8, 30),
            "anchor_time": time(18, 30),
            "next_fire_at": self.fire_at,
        }
        values.update(overrides)
        return ScheduledReminder.objects.create(**values)


    def test_scheduled_reminder_target_is_exactly_one_of_project_context_or_tag(self):
        context = Context.objects.create(user=self.user, name="Exercise")
        tag = Tag.objects.create(user=self.user, name="Deep work")

        for extra in ({"context": context}, {"tag": tag}):
            two_targets = ScheduledReminder(
                user=self.user,
                project=self.project,
                cadence="once",
                timezone="Europe/Prague",
                anchor_date=date(2026, 8, 30),
                anchor_time=time(18, 30),
                next_fire_at=self.fire_at,
                **extra,
            )
            with self.assertRaises(ValidationError):
                two_targets.full_clean()
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    two_targets.save()

        no_target = ScheduledReminder(
            user=self.user,
            cadence="once",
            timezone="Europe/Prague",
            anchor_date=date(2026, 8, 30),
            anchor_time=time(18, 30),
            next_fire_at=self.fire_at,
        )
        with self.assertRaises(ValidationError):
            no_target.full_clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                no_target.save()

        by_context = self.reminder(project=None, context=context)
        by_context.full_clean()
        self.assertEqual(by_context.target_name, "Exercise")
        self.assertIn("Exercise", str(by_context))
        self.assertEqual(list(context.scheduled_reminders.all()), [by_context])

        by_tag = self.reminder(project=None, tag=tag)
        by_tag.full_clean()
        self.assertEqual(by_tag.target_name, "Deep work")
        self.assertEqual(list(tag.scheduled_reminders.all()), [by_tag])

        foreign_context = ScheduledReminder(
            user=self.user,
            context=Context.objects.create(user=self.other, name="Theirs"),
            cadence="once",
            timezone="Europe/Prague",
            anchor_date=date(2026, 8, 30),
            anchor_time=time(18, 30),
            next_fire_at=self.fire_at,
        )
        with self.assertRaises(ValidationError):
            foreign_context.full_clean()

        foreign_tag = ScheduledReminder(
            user=self.user,
            tag=Tag.objects.create(user=self.other, name="Theirs"),
            cadence="once",
            timezone="Europe/Prague",
            anchor_date=date(2026, 8, 30),
            anchor_time=time(18, 30),
            next_fire_at=self.fire_at,
        )
        with self.assertRaises(ValidationError):
            foreign_tag.full_clean()

    def test_context_target_delete_cascades_reminder_and_cancels_pending_events(self):
        context = Context.objects.create(user=self.user, name="Exercise")
        reminder = self.reminder(project=None, context=context)
        event = NotificationEvent.objects.create(
            dedupe_key="scheduled-before-context-delete",
            event_type="scheduled_reminder",
            user=self.user,
            scheduled_reminder=reminder,
            payload={"title": "Scheduled"},
            scheduled_at=self.fire_at,
        )

        context.delete()

        self.assertFalse(ScheduledReminder.objects.filter(pk=reminder.pk).exists())
        event.refresh_from_db()
        self.assertEqual(event.status, "cancelled")
        self.assertIsNone(event.scheduled_reminder_id)

    def test_scheduled_reminder_clean_enforces_ownership_and_project_eligibility(self):
        wrong_owner = ScheduledReminder(
            user=self.user,
            project=self.other_project,
            cadence="once",
            timezone="Europe/Prague",
            anchor_date=date(2026, 8, 30),
            anchor_time=time(18, 30),
            next_fire_at=self.fire_at,
        )
        with self.assertRaises(ValidationError):
            wrong_owner.full_clean()

        paused = Projects.objects.create(user=self.user, name="Paused", status="paused")
        paused_reminder = ScheduledReminder(
            user=self.user,
            project=paused,
            cadence="daily",
            timezone="Europe/Prague",
            anchor_date=date(2026, 8, 30),
            anchor_time=time(18, 30),
            next_fire_at=self.fire_at,
        )
        paused_reminder.full_clean()

        archived = Projects.objects.create(user=self.user, name="Archived", status="archived")
        archived_reminder = ScheduledReminder(
            user=self.user,
            project=archived,
            cadence="daily",
            timezone="Europe/Prague",
            anchor_date=date(2026, 8, 30),
            anchor_time=time(18, 30),
            next_fire_at=self.fire_at,
        )
        with self.assertRaises(ValidationError):
            archived_reminder.full_clean()


    def test_commitment_queryset_delete_cancels_only_pending_source_events(self):
        context = Context.objects.create(user=self.user, name="Delete check")
        commitment = Commitment.objects.create(
            user=self.user,
            aggregation_type="context",
            context=context,
            commitment_type="sessions",
            target=1,
        )
        pending = NotificationEvent.objects.create(
            dedupe_key="commitment-before-delete",
            event_type="commitment_check",
            user=self.user,
            commitment=commitment,
            payload={"title": "Commitment"},
            scheduled_at=self.fire_at,
        )
        delivered = NotificationEvent.objects.create(
            dedupe_key="delivered-commitment-before-delete",
            event_type="commitment_check",
            user=self.user,
            commitment=commitment,
            payload={"title": "Already delivered"},
            scheduled_at=self.fire_at,
            status="delivered",
            delivered_at=self.fire_at,
        )

        Commitment.objects.filter(pk=commitment.pk).delete()

        pending.refresh_from_db()
        delivered.refresh_from_db()
        self.assertEqual(pending.status, "cancelled")
        self.assertEqual(delivered.status, "delivered")
        self.assertIsNone(pending.commitment_id)
        self.assertIsNone(delivered.commitment_id)


    def test_event_sources_are_nullable_and_must_be_owned_by_event_user(self):
        reminder = self.reminder()
        event = NotificationEvent.objects.create(
            dedupe_key="scheduled-event",
            event_type="scheduled_reminder",
            user=self.user,
            scheduled_reminder=reminder,
            payload={"title": "Scheduled"},
            scheduled_at=timezone.now(),
        )
        event.full_clean()

        NotificationEvent.objects.create(
            dedupe_key="weekly-event",
            event_type="weekly_review",
            user=self.user,
            payload={"title": "Weekly"},
            scheduled_at=timezone.now(),
        )

        foreign_event = NotificationEvent(
            dedupe_key="foreign-source-event",
            event_type="scheduled_reminder",
            user=self.other,
            scheduled_reminder=reminder,
            payload={"title": "Foreign"},
            scheduled_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            foreign_event.full_clean()
