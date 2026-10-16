from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from core.commitments import (
    commitment_actionability,
    get_commitment_evaluation,
    weekly_commitment_score,
)
from core.models import Projects, Sessions
from core.services import CommitmentEditService


UTC = dt_timezone.utc


class ProactiveNotificationDomainTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="proactive-domain")
        self.project = Projects.objects.create(user=self.user, name="Primary")
        self.other_project = Projects.objects.create(
            user=self.user, name="Secondary"
        )

    def _commitment(self, **changes):
        definition = {
            "project": self.project,
            "target": 30,
            "commitment_type": "time",
            "period": "daily",
            "start_date": datetime(2026, 1, 5, tzinfo=UTC).date(),
        }
        definition.update(changes)
        return CommitmentEditService.create(self.user, definition)

    def _session(self, project, start, minutes=30):
        return Sessions.objects.create(
            user=self.user,
            project=project,
            start_time=start,
            end_time=start + timedelta(minutes=minutes),
        )

    @freeze_time("2026-01-05 12:00:00+00:00")
    def test_profile_timezone_wins_over_server_timezone_for_boundaries(self):
        self.user.profile.timezone = "America/New_York"
        self.user.profile.save(update_fields=["timezone"])
        commitment = self._commitment()
        self._session(
            self.project,
            datetime(2026, 1, 6, 1, 0, tzinfo=UTC),
        )

        with timezone.override(ZoneInfo("Europe/Prague")):
            evaluation = get_commitment_evaluation(
                commitment,
                datetime(2026, 1, 6, 3, 30, tzinfo=UTC),
            )

        self.assertEqual(evaluation["timezone"], "America/New_York")
        self.assertEqual(
            evaluation["period_start"],
            datetime(2026, 1, 5, 5, tzinfo=UTC),
        )
        self.assertEqual(evaluation["actual"], 30)

    @freeze_time("2026-01-05 12:00:00+00:00")
    def test_revision_timezone_and_snapshot_scope_are_frozen(self):
        self.user.profile.timezone = "America/New_York"
        self.user.profile.save(update_fields=["timezone"])
        commitment = self._commitment(timezone="Asia/Tokyo")
        # This session is in the profile's New York day but before the Tokyo
        # revision's Jan 6 period starts at 15:00 UTC.
        self._session(
            self.project,
            datetime(2026, 1, 5, 12, 30, tzinfo=UTC),
        )

        evaluation = get_commitment_evaluation(
            commitment,
            datetime(2026, 1, 6, 3, 30, tzinfo=UTC),
        )
        self.assertEqual(evaluation["timezone"], "Asia/Tokyo")
        self.assertEqual(
            evaluation["period_start"],
            datetime(2026, 1, 5, 15, tzinfo=UTC),
        )
        self.assertEqual(evaluation["actual"], 0)

    @freeze_time("2026-01-04 12:00:00+00:00")
    def test_actionability_uses_positive_bank_balance(self):
        commitment = self._commitment(
            target=60,
            start_date=datetime(2026, 1, 4, tzinfo=UTC).date(),
            timezone="UTC",
        )
        # A prior daily period earns 60 minutes of carry, covering the open
        # period even though it has no current sessions.
        self._session(
            self.project,
            datetime(2026, 1, 4, 12, 0, tzinfo=UTC),
            minutes=120,
        )
        reference = datetime(2026, 1, 5, 19, 0, tzinfo=UTC)
        with freeze_time("2026-01-05 20:00:00+00:00"):
            evaluation = get_commitment_evaluation(commitment, reference)
            actionability = commitment_actionability(evaluation, reference)

        self.assertEqual(evaluation["balance"], 60)
        self.assertEqual(evaluation["remaining"], 0)
        self.assertTrue(evaluation["covered"])
        self.assertFalse(actionability["actionable"])


    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_weekly_score_mixes_cadences_and_counts_closing_boundary(self):
        daily = self._commitment(
            target=30,
            timezone="UTC",
            start_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
        )
        weekly = self._commitment(
            target=30,
            period="weekly",
            timezone="UTC",
            start_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
            project=self.other_project,
        )
        monthly = self._commitment(
            target=30,
            period="monthly",
            timezone="UTC",
            start_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
            project=Projects.objects.create(user=self.user, name="Monthly"),
        )
        for day in range(1, 7):
            self._session(
                self.project,
                datetime(2026, 1, day, 12, tzinfo=UTC),
            )
        self._session(
            self.other_project,
            datetime(2026, 1, 1, 12, tzinfo=UTC),
        )

        with freeze_time("2026-01-08 12:00:00+00:00"):
            score = weekly_commitment_score(
                self.user,
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 8, tzinfo=UTC),
            )

        self.assertEqual(score["eligible_count"], 2)
        self.assertEqual(score["met_count"], 1)
        details = {item["commitment_id"]: item for item in score["details"]}
        self.assertEqual(details[daily.pk]["period_count"], 7)
        self.assertEqual(details[daily.pk]["met_period_count"], 6)
        self.assertFalse(details[daily.pk]["met"])
        self.assertEqual(details[weekly.pk]["met_period_count"], 1)
        self.assertTrue(details[weekly.pk]["met"])
        self.assertNotIn(monthly.pk, details)
