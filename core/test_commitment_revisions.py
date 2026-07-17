from datetime import date, datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from freezegun import freeze_time

from core.commitments import recompute_commitment
from core.models import (
    CommitmentAdjustment,
    CommitmentRevision,
    Projects,
)
from core.services import (
    CommitmentEditService,
    CommitmentRestartRequired,
    SessionMutationService,
)


UTC = dt_timezone.utc


class CommitmentRevisionServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="revision-user")

    def project(self, name):
        return Projects.objects.create(user=self.user, name=name)

    def create_commitment(self, project, **overrides):
        definition = {
            "aggregation_type": "project",
            "project": project,
            "commitment_type": "time",
            "period": "daily",
            "start_date": date(2026, 1, 1),
            "target": 60,
            "banking_enabled": True,
            "max_balance": 600,
            "min_balance": -600,
        }
        definition.update(overrides)
        return CommitmentEditService.create(self.user, definition)

    def session(self, project, start, end):
        return SessionMutationService.create_session(
            user=self.user,
            project=project,
            start_time=start,
            end_time=end,
            is_active=False,
        )

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_edits_coalesce_and_replay_resolves_revision_per_period(self):
        project = self.project("Coalesce")
        commitment = self.create_commitment(project)
        self.session(
            project,
            datetime(2026, 1, 1, 13, tzinfo=UTC),
            datetime(2026, 1, 1, 15, tzinfo=UTC),
        )

        CommitmentEditService.edit(
            commitment.pk, user=self.user, changes={"target": 100}
        )
        CommitmentEditService.edit(
            commitment.pk, user=self.user, changes={"target": 30}
        )

        pending = commitment.revisions.get(status=CommitmentRevision.STATUS_PENDING)
        self.assertEqual(pending.target_value, 30)
        self.assertEqual(
            pending.effective_from_instant,
            datetime(2026, 1, 1, 23, tzinfo=UTC),
        )
        commitment.refresh_from_db()
        self.assertEqual((commitment.target, commitment.version), (60, 3))

        with freeze_time("2026-01-03 12:00:00+00:00"):
            recompute_commitment(commitment)

        rows = list(commitment.period_rows.order_by("period_start"))
        self.assertEqual(
            [row.revision.target_value for row in rows],
            [60, 30],
        )
        self.assertEqual([row.balance_out for row in rows], [60, 30])
        commitment.refresh_from_db()
        self.assertEqual(commitment.target, 30)
        self.assertFalse(commitment.revisions.filter(status="pending").exists())

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_restart_keep_and_reset_preserve_history_and_discard_partial(self):
        keep_project = self.project("Keep")
        keep = self.create_commitment(keep_project)
        self.session(
            keep_project,
            datetime(2026, 1, 1, 13, tzinfo=UTC),
            datetime(2026, 1, 1, 15, tzinfo=UTC),
        )
        with freeze_time("2026-01-02 12:00:00+00:00"):
            recompute_commitment(keep)
            CommitmentEditService.edit(
                keep.pk, user=self.user, changes={"target": 30}
            )
        with freeze_time("2026-01-02 13:00:00+00:00"):
            CommitmentEditService.restart(
                keep.pk, user=self.user, keep_balance=True, changes=None
            )

        keep.refresh_from_db()
        carry = keep.adjustments.get(kind=CommitmentAdjustment.KIND_RESTART_CARRY)
        self.assertEqual(carry.amount, 60)
        self.assertFalse(keep.revisions.filter(status="pending").exists())
        self.assertEqual(keep.period_rows.filter(generation=1).count(), 1)
        self.assertFalse(keep.period_rows.filter(generation=2).exists())
        with freeze_time("2026-01-03 12:00:00+00:00"):
            recompute_commitment(keep)
        new_keep_row = keep.period_rows.get(generation=2)
        self.assertEqual((new_keep_row.carryover_in, new_keep_row.balance_out), (60, 0))

        reset_project = self.project("Reset")
        with freeze_time("2026-01-01 12:00:00+00:00"):
            reset = self.create_commitment(reset_project)
            self.session(
                reset_project,
                datetime(2026, 1, 1, 13, tzinfo=UTC),
                datetime(2026, 1, 1, 15, tzinfo=UTC),
            )
        with freeze_time("2026-01-02 12:00:00+00:00"):
            recompute_commitment(reset)
        with freeze_time("2026-01-02 13:00:00+00:00"):
            CommitmentEditService.restart(
                reset.pk, user=self.user, keep_balance=False, changes=None
            )
        self.assertFalse(
            reset.adjustments.filter(
                kind=CommitmentAdjustment.KIND_RESTART_CARRY
            ).exists()
        )
        self.assertEqual(reset.period_rows.filter(generation=1).count(), 1)
        with freeze_time("2026-01-03 12:00:00+00:00"):
            recompute_commitment(reset)
        new_reset_row = reset.period_rows.get(generation=2)
        self.assertEqual((new_reset_row.carryover_in, new_reset_row.balance_out), (0, -60))

    @freeze_time("2026-01-05 12:00:00+00:00")
    def test_cadence_restart_uses_new_local_date_and_keeps_old_rows(self):
        project = self.project("Cadence")
        commitment = self.create_commitment(project, period="weekly")
        with freeze_time("2026-01-12 12:00:00+00:00"):
            recompute_commitment(commitment)
            old_rows = list(
                commitment.period_rows.filter(generation=1).values_list(
                    "period_start", "period_end", "balance_out"
                )
            )
            CommitmentEditService.restart(
                commitment.pk,
                user=self.user,
                keep_balance=False,
                changes={"period": "daily"},
            )
        with freeze_time("2026-01-13 12:00:00+00:00"):
            recompute_commitment(commitment)

        commitment.refresh_from_db()
        new_row = commitment.period_rows.get(generation=2)
        self.assertEqual(commitment.period, "daily")
        self.assertEqual(
            new_row.period_start.astimezone(ZoneInfo("Europe/Prague")).date(),
            date(2026, 1, 12),
        )
        self.assertEqual(
            list(
                commitment.period_rows.filter(generation=1).values_list(
                    "period_start", "period_end", "balance_out"
                )
            ),
            old_rows,
        )

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_timezone_restart_controls_boundary_derivation(self):
        project = self.project("Timezone")
        commitment = self.create_commitment(project)
        with freeze_time("2026-01-01 23:30:00+00:00"):
            CommitmentEditService.restart(
                commitment.pk,
                user=self.user,
                keep_balance=False,
                changes={"timezone": "America/New_York"},
            )
        with freeze_time("2026-01-02 06:00:00+00:00"):
            recompute_commitment(commitment)

        row = commitment.period_rows.get(generation=2)
        self.assertEqual(row.revision.timezone, "America/New_York")
        self.assertEqual(row.period_start, datetime(2026, 1, 1, 5, tzinfo=UTC))
        self.assertEqual(row.period_end, datetime(2026, 1, 2, 5, tzinfo=UTC))

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_deactivate_freezes_and_reactivation_requires_restart(self):
        project = self.project("Freeze")
        commitment = self.create_commitment(project)
        with freeze_time("2026-01-02 12:00:00+00:00"):
            recompute_commitment(commitment)
            commitment.refresh_from_db()
            frozen_balance = commitment.balance
            frozen_count = commitment.period_rows.count()
            CommitmentEditService.edit(
                commitment.pk, user=self.user, changes={"active": False}
            )

        with freeze_time("2026-01-05 12:00:00+00:00"):
            recompute_commitment(commitment)
            with self.assertRaises(CommitmentRestartRequired):
                CommitmentEditService.edit(
                    commitment.pk, user=self.user, changes={"active": True}
                )
            CommitmentEditService.restart(
                commitment.pk,
                user=self.user,
                keep_balance=True,
                changes={"active": True},
            )

        commitment.refresh_from_db()
        self.assertEqual(commitment.period_rows.filter(generation=1).count(), frozen_count)
        self.assertEqual(commitment.balance, frozen_balance)
        self.assertTrue(commitment.active)
        self.assertEqual(commitment.generation, 2)
        self.assertEqual(commitment.version, 3)
        self.assertEqual(
            commitment.ledger_start_at, datetime(2026, 1, 5, 12, tzinfo=UTC)
        )
        self.assertTrue(commitment.needs_recompute)

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_version_dirty_unique_pending_and_atomic_mixed_rejection(self):
        project = self.project("Atomic")
        commitment = self.create_commitment(project)
        CommitmentEditService.edit(
            commitment.pk, user=self.user, changes={"max_balance": 700}
        )
        commitment.refresh_from_db()
        self.assertEqual(commitment.version, 2)
        self.assertTrue(commitment.needs_recompute)

        active = commitment.revisions.get(status="active")
        with self.assertRaises(IntegrityError), transaction.atomic():
            CommitmentRevision.objects.create(
                commitment=commitment,
                generation=commitment.generation,
                effective_from_instant=timezone_now(),
                status="pending",
                aggregation_type=active.aggregation_type,
                target_id=active.target_id,
                target_name=active.target_name,
                filters_snapshot=active.filters_snapshot,
                commitment_type=active.commitment_type,
                cadence=active.cadence,
                target_value=active.target_value,
                banking_enabled=active.banking_enabled,
                max_balance=active.max_balance,
                min_balance=active.min_balance,
                start_date=active.start_date,
                timezone=active.timezone,
            )

        before_pending = commitment.revisions.get(status="pending")
        with self.assertRaises(CommitmentRestartRequired):
            CommitmentEditService.edit(
                commitment.pk,
                user=self.user,
                changes={"period": "weekly", "target": 10, "active": False},
            )
        commitment.refresh_from_db()
        before_pending.refresh_from_db()
        self.assertEqual(commitment.version, 2)
        self.assertTrue(commitment.active)
        self.assertEqual(before_pending.target_value, 60)


def timezone_now():
    # Kept as a function so freezegun supplies the service-call instant.
    from django.utils import timezone

    return timezone.now()
