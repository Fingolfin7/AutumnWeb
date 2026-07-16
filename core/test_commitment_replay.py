from datetime import date, datetime, timedelta, timezone as dt_timezone
from importlib import import_module
from zoneinfo import ZoneInfo

from django.apps import apps
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from core.commitments import (
    mutation_affects_ledger,
    reconcile_commitment,
    recompute_commitment,
    snapshot_commitment_definition,
)
from core.models import (
    Commitment,
    CommitmentAdjustment,
    CommitmentPeriod,
    CommitmentRevision,
    Projects,
)
from core.services import SessionMutationService


UTC = dt_timezone.utc
PRAGUE = ZoneInfo("Europe/Prague")


class CommitmentReplayTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ledger-user")
        self.project = Projects.objects.create(user=self.user, name="Ledger")

    def commitment(self, **overrides):
        fields = {
            "user": self.user,
            "project": self.project,
            "aggregation_type": "project",
            "commitment_type": "time",
            "period": "daily",
            "start_date": timezone.localdate(),
            "target": 100,
            "balance": 0,
            "max_balance": 600,
            "min_balance": -600,
            "banking_enabled": True,
        }
        fields.update(overrides)
        return Commitment.objects.create(**fields)

    def session(self, start, end):
        return SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=start,
            end_time=end,
            is_active=False,
        )

    @freeze_time("2025-01-01 12:00:00+00:00")
    def test_clamp_then_truncate_path_and_v1_balance(self):
        commitment = self.commitment(target=500, start_date=date(2025, 1, 1))
        self.session(
            datetime(2024, 12, 31, tzinfo=UTC),
            datetime(2025, 1, 1, 1, tzinfo=UTC),
        )

        with freeze_time("2025-01-02 12:00:00+00:00"):
            self.assertTrue(reconcile_commitment(commitment))
        with freeze_time("2025-01-03 12:00:00+00:00"):
            self.assertTrue(reconcile_commitment(commitment))
            rows = list(
                commitment.period_rows.order_by("period_start").values_list(
                    "balance_out", flat=True
                )
            )
            client = APIClient()
            client.force_authenticate(self.user)
            response = client.get("/api/v2/commitments/")

        self.assertEqual(rows, [600, 100])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["commitments"][0]["balance"], 100)

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_adjustment_wins_period_close_tie(self):
        commitment = self.commitment(start_date=date(2026, 1, 1), max_balance=100)
        reconcile_commitment(commitment)
        period_end = datetime(2026, 1, 1, 23, tzinfo=UTC)
        CommitmentAdjustment.objects.create(
            commitment=commitment,
            seq=2,
            kind=CommitmentAdjustment.KIND_MANUAL,
            amount=200,
            effective_at=period_end,
            reason="tie",
        )
        Commitment.objects.filter(pk=commitment.pk).update(needs_recompute=True)

        with freeze_time("2026-01-02 12:00:00+00:00"):
            recompute_commitment(commitment)

        row = commitment.period_rows.get()
        self.assertEqual((row.carryover_in, row.balance_out), (200, 100))

    @freeze_time("2026-01-01 08:00:00+00:00")
    def test_manual_adjustment_is_unclamped_until_close(self):
        commitment = self.commitment(start_date=date(2026, 1, 1), max_balance=600)
        reconcile_commitment(commitment)
        CommitmentAdjustment.objects.create(
            commitment=commitment,
            seq=2,
            kind=CommitmentAdjustment.KIND_MANUAL,
            amount=1000,
            effective_at=datetime(2026, 1, 1, 12, tzinfo=UTC),
            reason="mid-period",
        )
        Commitment.objects.filter(pk=commitment.pk).update(needs_recompute=True)

        with freeze_time("2026-01-02 12:00:00+00:00"):
            recompute_commitment(commitment)

        row = commitment.period_rows.get()
        self.assertEqual(row.carryover_in, 1000)
        self.assertEqual(row.balance_out, 600)

    @freeze_time("2026-03-28 12:00:00+00:00")
    def test_dst_periods_use_local_boundaries_and_absolute_accrual(self):
        commitment = self.commitment(
            start_date=date(2026, 3, 28), target=120, max_balance=5000
        )
        reconcile_commitment(commitment)
        self.session(
            datetime(2026, 3, 29, 0, tzinfo=UTC),
            datetime(2026, 3, 29, 2, tzinfo=UTC),
        )

        with freeze_time("2026-04-01 12:00:00+00:00"):
            recompute_commitment(commitment)
            first = list(
                commitment.period_rows.order_by("period_start").values_list(
                    "period_start",
                    "period_end",
                    "accrued_numerator",
                    "session_count",
                    "carryover_in",
                    "balance_out",
                )
            )
            recompute_commitment(commitment)
            second = list(
                commitment.period_rows.order_by("period_start").values_list(
                    "period_start",
                    "period_end",
                    "accrued_numerator",
                    "session_count",
                    "carryover_in",
                    "balance_out",
                )
            )

        spring = next(row for row in first if row[0].astimezone(PRAGUE).date() == date(2026, 3, 29))
        self.assertEqual(spring[1] - spring[0], timedelta(hours=23))
        self.assertEqual((spring[2], spring[3]), (1_200_000, 1))
        self.assertEqual(first, second)

    @freeze_time("2026-04-01 12:00:00+00:00")
    def test_pre_anchor_mutation_is_accounting_noop(self):
        commitment = self.commitment(balance=77, start_date=date(2026, 1, 1))
        anchor = timezone.now()
        definition = snapshot_commitment_definition(commitment)
        commitment.ledger_start_at = anchor
        commitment.save(update_fields=["ledger_start_at"])
        CommitmentRevision.objects.create(
            commitment=commitment,
            effective_from_instant=anchor,
            status=CommitmentRevision.STATUS_ACTIVE,
            **definition,
        )
        CommitmentAdjustment.objects.create(
            commitment=commitment,
            seq=1,
            kind=CommitmentAdjustment.KIND_OPENING,
            amount=77,
            effective_at=anchor,
            reason="cutover",
        )
        old_instant = anchor - timedelta(days=2)
        self.assertFalse(mutation_affects_ledger(commitment, old_instant))
        session = self.session(old_instant - timedelta(hours=1), old_instant)
        self.assertTrue(Commitment.objects.get(pk=commitment.pk).needs_recompute)

        SessionMutationService.mutate_session(
            session.pk,
            user=self.user,
            note="pre-anchor edit",
        )
        recompute_commitment(commitment)
        commitment.refresh_from_db()

        self.assertEqual(commitment.balance, 77)
        self.assertFalse(commitment.needs_recompute)
        self.assertFalse(commitment.period_rows.exists())

    @freeze_time("2026-02-03 12:00:00+00:00")
    def test_recompute_is_deterministic_after_dirty_flag_is_reset(self):
        commitment = self.commitment(start_date=date(2026, 2, 1), target=50)
        self.session(
            datetime(2026, 2, 1, 8, tzinfo=UTC),
            datetime(2026, 2, 1, 9, tzinfo=UTC),
        )
        recompute_commitment(commitment)
        first = list(
            commitment.period_rows.order_by("period_start").values_list(
                "period_start", "accrued_numerator", "carryover_in", "balance_out"
            )
        )
        Commitment.objects.filter(pk=commitment.pk).update(needs_recompute=True)
        recompute_commitment(commitment)
        second = list(
            commitment.period_rows.order_by("period_start").values_list(
                "period_start", "accrued_numerator", "carryover_in", "balance_out"
            )
        )
        commitment.refresh_from_db()

        self.assertEqual(first, second)
        self.assertFalse(commitment.needs_recompute)

    @freeze_time("2026-05-04 12:00:00+00:00")
    def test_v1_list_and_detail_lazy_reads_are_idempotent(self):
        commitment = self.commitment(start_date=date(2026, 5, 1))
        client = APIClient()
        client.force_authenticate(self.user)

        list_first = client.get("/api/v2/commitments/").content
        detail_first = client.get(f"/api/v2/commitments/{commitment.pk}").content
        for _ in range(3):
            self.assertEqual(
                client.get("/api/v2/commitments/").content, list_first
            )
            self.assertEqual(
                client.get(f"/api/v2/commitments/{commitment.pk}").content,
                detail_first,
            )

    @freeze_time("2026-06-15 12:00:00+00:00")
    def test_migration_snapshot_preserves_populated_balance_without_history(self):
        commitment = self.commitment(
            balance=321,
            period="monthly",
            target=240,
            start_date=date(2025, 1, 1),
            banking_enabled=False,
        )
        migration = import_module("core.migrations.0045_commitment_replay_ledger")
        migration.snapshot_existing_commitments(apps, None)

        commitment.refresh_from_db()
        opening = commitment.adjustments.get()
        revision = commitment.revisions.get()
        self.assertEqual(opening.amount, 321)
        self.assertEqual(opening.effective_at, commitment.ledger_start_at)
        self.assertEqual(
            (revision.status, revision.cadence, revision.target_value, revision.target_name),
            ("active", "monthly", 240, self.project.name),
        )
        self.assertFalse(commitment.period_rows.exists())

        recompute_commitment(commitment)
        commitment.refresh_from_db()
        self.assertEqual(commitment.balance, 321)
        self.assertFalse(commitment.period_rows.exists())

    @freeze_time("2026-07-03 12:00:00+00:00")
    def test_session_commitment_uses_count_not_time_numerator(self):
        commitment = self.commitment(
            commitment_type="sessions",
            start_date=date(2026, 7, 1),
            target=1,
        )
        self.session(
            datetime(2026, 7, 1, 8, tzinfo=UTC),
            datetime(2026, 7, 1, 18, tzinfo=UTC),
        )
        recompute_commitment(commitment)
        first_row = commitment.period_rows.order_by("period_start").first()

        self.assertEqual(first_row.session_count, 1)
        self.assertEqual(first_row.accrued_numerator, 6_000_000)
        self.assertEqual(first_row.balance_out, 0)

    @freeze_time("2026-07-03 12:00:00+00:00")
    def test_non_banking_periods_record_accrual_without_moving_balance(self):
        commitment = self.commitment(
            balance=42,
            banking_enabled=False,
            start_date=date(2026, 7, 1),
            target=10,
        )
        self.session(
            datetime(2026, 7, 1, 8, tzinfo=UTC),
            datetime(2026, 7, 1, 9, tzinfo=UTC),
        )
        recompute_commitment(commitment)
        rows = list(commitment.period_rows.order_by("period_start"))
        commitment.refresh_from_db()

        self.assertTrue(rows)
        self.assertEqual(rows[0].accrued_numerator, 600_000)
        self.assertTrue(all(row.balance_out == 42 for row in rows))
        self.assertEqual(commitment.balance, 42)
