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
from core.services.reporting import summarize_completed_sessions


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

    def test_completed_session_summary_is_half_open(self):
        start = datetime(2026, 1, 5, tzinfo=UTC)
        end = datetime(2026, 1, 12, tzinfo=UTC)
        self._session(self.project, start - timedelta(minutes=60))
        self._session(self.project, start + timedelta(hours=1))
        self._session(self.other_project, end - timedelta(minutes=60))
        self._session(self.other_project, end)

        summary = summarize_completed_sessions(self.user, start, end)

        self.assertEqual(summary["total_minutes"], 60)
        self.assertEqual(summary["project_count"], 2)
        self.assertEqual(summary["session_count"], 2)
        self.assertEqual(
            [(row["project_id"], row["total_minutes"]) for row in summary["per_project"]],
            [(self.project.pk, 30), (self.other_project.pk, 30)],
        )

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

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_weekly_score_includes_prior_generations_with_revision_banking(self):
        commitment = self._commitment(
            target=60,
            timezone="UTC",
            start_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
            banking_enabled=True,
            max_balance=600,
            min_balance=0,
        )
        self._session(
            self.project,
            datetime(2026, 1, 1, 12, tzinfo=UTC),
            minutes=120,
        )

        # Close two periods in generation one, then restart with banking
        # disabled.  The old rows must retain the old revision's banking rule.
        from core.commitments import recompute_commitment

        with freeze_time("2026-01-03 12:00:00+00:00"):
            recompute_commitment(commitment)
            commitment = CommitmentEditService.restart(
                commitment.pk,
                user=self.user,
                keep_balance=False,
                changes={"banking_enabled": False},
            )

        with freeze_time("2026-01-06 12:00:00+00:00"):
            score = weekly_commitment_score(
                self.user,
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 8, tzinfo=UTC),
            )

        details = score["details"][0]
        periods = sorted(details["periods"], key=lambda row: row["period_start"])
        self.assertEqual(details["period_count"], 5)
        self.assertEqual(details["met_period_count"], 2)
        self.assertEqual(
            [period["banking_enabled"] for period in periods],
            [True, True, False, False, False],
        )
        self.assertEqual(
            [period["met"] for period in periods],
            [True, True, False, False, False],
        )
