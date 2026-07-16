from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from freezegun import freeze_time
from rest_framework.test import APIClient

from core.models import Commitment, Projects
from core.services import SessionMutationService


UTC = datetime_timezone.utc


class V2CommitmentsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="v2-commitments", email="v2-commitments@example.com"
        )
        self.project = Projects.objects.create(user=self.user, name="Focus")
        self.other_project = Projects.objects.create(user=self.user, name="Exercise")
        self.foreign_user = User.objects.create_user(
            username="commitment-foreign", email="commitment-foreign@example.com"
        )
        self.foreign_project = Projects.objects.create(
            user=self.foreign_user, name="Foreign"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def create_payload(self, project=None, **overrides):
        payload = {
            "aggregation_type": "project",
            "project_id": (project or self.project).pk,
            "commitment_type": "time",
            "period": "daily",
            "start_date": "2026-01-01",
            "timezone": "Europe/Prague",
            "target_value": 60,
            "banking_enabled": True,
            "max_balance": 600,
            "min_balance": -600,
        }
        payload.update(overrides)
        return payload

    def create_commitment(self, project=None, **overrides):
        response = self.client.post(
            reverse("api_v2:commitments"),
            self.create_payload(project, **overrides),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_crud_list_duplicate_target_and_foreign_detail(self):
        created = self.create_commitment()
        payload = created.json()
        commitment_id = payload["id"]
        self.assertEqual(payload["version"], 1)
        self.assertEqual(
            payload["target"],
            {"kind": "project", "id": self.project.pk, "name": "Focus"},
        )
        self.assertEqual(payload["target_value"], 60.0)
        self.assertEqual(payload["filters"]["include_project_ids"], [])
        self.assertIsNone(payload["pending_revision"])

        listed = self.client.get(reverse("api_v2:commitments"))
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["count"], 1)
        self.assertEqual(listed.json()["commitments"][0]["id"], commitment_id)

        detail = self.client.get(
            reverse("api_v2:commitment-detail", args=[commitment_id])
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["id"], commitment_id)

        duplicate = self.client.post(
            reverse("api_v2:commitments"), self.create_payload(), format="json"
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], "conflict")
        self.assertEqual(
            duplicate.json()["error"]["message"],
            "This project already has a commitment.",
        )

        foreign = self.client.get(
            reverse(
                "api_v2:commitment-detail",
                args=[
                    Commitment.objects.create(
                        user=self.foreign_user,
                        project=self.foreign_project,
                        aggregation_type="project",
                        commitment_type="time",
                        period="daily",
                        start_date="2026-01-01",
                        target=10,
                    ).pk
                ],
            )
        )
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.json()["error"]["code"], "not_found")

        deleted = self.client.delete(
            reverse("api_v2:commitment-detail", args=[commitment_id]),
            HTTP_IF_MATCH="1",
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(
            self.client.delete(
                reverse("api_v2:commitment-detail", args=[commitment_id]),
                HTTP_IF_MATCH="not-an-integer",
            ).status_code,
            204,
        )

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_patch_pending_stale_version_and_restart_required(self):
        commitment = self.create_commitment().json()
        url = reverse("api_v2:commitment-detail", args=[commitment["id"]])
        response = self.client.patch(
            url,
            {"target_value": 90, "max_balance": 700},
            format="json",
            HTTP_IF_MATCH="1",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["version"], 2)
        self.assertEqual(response.json()["target_value"], 60.0)
        self.assertEqual(response.json()["max_balance"], 600.0)
        self.assertEqual(
            response.json()["pending_revision"]["changes"],
            {"target_value": 90.0, "max_balance": 700.0},
        )

        stale = self.client.patch(
            url,
            {"target_value": 30},
            format="json",
            HTTP_IF_MATCH="1",
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["code"], "version_conflict")
        self.assertEqual(stale.json()["error"]["details"]["current"]["version"], 2)

        restart_only = self.client.patch(
            url,
            {"period": "weekly"},
            format="json",
            HTTP_IF_MATCH="2",
        )
        self.assertEqual(restart_only.status_code, 400)
        self.assertEqual(restart_only.json()["error"]["code"], "restart_required")
        self.assertIn("period", restart_only.json()["error"]["message"])

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_restart_keep_reset_generation_balance_and_if_match(self):
        commitment = self.create_commitment().json()
        SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=datetime(2026, 1, 1, 13, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 15, tzinfo=UTC),
            is_active=False,
        )
        url = reverse("api_v2:commitment-restart", args=[commitment["id"]])
        with freeze_time("2026-01-02 13:00:00+00:00"):
            kept = self.client.post(
                url,
                {"keep_balance": True},
                format="json",
                HTTP_IF_MATCH="1",
            )
        self.assertEqual(kept.status_code, 200, kept.content)
        self.assertEqual(kept.json()["generation"], 2)
        self.assertEqual(kept.json()["balance"], 60.0)
        self.assertEqual(kept.json()["version"], 2)

        stale = self.client.post(
            url,
            {"keep_balance": False},
            format="json",
            HTTP_IF_MATCH="1",
        )
        self.assertEqual(stale.status_code, 409)

        with freeze_time("2026-01-02 14:00:00+00:00"):
            reset = self.client.post(
                url,
                {"keep_balance": False, "changes": {"target_value": 30}},
                format="json",
                HTTP_IF_MATCH="2",
            )
        self.assertEqual(reset.status_code, 200, reset.content)
        self.assertEqual(reset.json()["generation"], 3)
        self.assertEqual(reset.json()["balance"], 0.0)
        self.assertEqual(reset.json()["target_value"], 30.0)

    @freeze_time("2026-01-01 08:00:00+00:00")
    def test_manual_adjustment_is_unclamped_then_clamped_at_close(self):
        commitment = self.create_commitment(target_value=100).json()
        response = self.client.post(
            reverse("api_v2:commitment-adjustments", args=[commitment["id"]]),
            {"amount": 1000, "reason": "correction"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["amount"], 1000)
        self.assertEqual(response.json()["reason"], "correction")
        self.assertEqual(response.json()["balance"], 1000.0)
        self.assertEqual(
            Commitment.objects.get(pk=commitment["id"]).version, 2
        )

        with freeze_time("2026-01-02 12:00:00+00:00"):
            detail = self.client.get(
                reverse("api_v2:commitment-detail", args=[commitment["id"]])
            )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["balance"], 600.0)

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_period_generation_filter_and_pagination(self):
        commitment = self.create_commitment().json()
        detail_url = reverse(
            "api_v2:commitment-detail", args=[commitment["id"]]
        )
        with freeze_time("2026-01-04 12:00:00+00:00"):
            self.client.get(detail_url)
        with freeze_time("2026-01-04 13:00:00+00:00"):
            restarted = self.client.post(
                reverse("api_v2:commitment-restart", args=[commitment["id"]]),
                {"keep_balance": False},
                format="json",
                HTTP_IF_MATCH="1",
            )
        self.assertEqual(restarted.status_code, 200, restarted.content)
        with freeze_time("2026-01-06 12:00:00+00:00"):
            response = self.client.get(
                reverse("api_v2:commitment-periods", args=[commitment["id"]]),
                {"limit": 1, "offset": 0},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["total"], 2)
        self.assertEqual(response.json()["periods"][0]["generation"], 2)

        old = self.client.get(
            reverse("api_v2:commitment-periods", args=[commitment["id"]]),
            {"generation": 1, "limit": 2, "offset": 1},
        )
        self.assertEqual(old.status_code, 200)
        self.assertEqual(old.json()["total"], 3)
        self.assertEqual(old.json()["count"], 2)
        self.assertTrue(
            all(row["generation"] == 1 for row in old.json()["periods"])
        )
        self.assertGreater(
            old.json()["periods"][0]["period_start"],
            old.json()["periods"][1]["period_start"],
        )

    @freeze_time("2026-04-01 12:00:00+00:00")
    def test_session_patch_pre_anchor_warning_conditions(self):
        commitment = self.create_commitment(start_date="2026-04-01").json()
        before_anchor = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=datetime(2026, 3, 30, 8, tzinfo=UTC),
            end_time=datetime(2026, 3, 30, 9, tzinfo=UTC),
            is_active=False,
        )
        response = self.client.patch(
            reverse("api_v2:session-detail", args=[before_anchor.pk]),
            {"note": "old correction"},
            format="json",
            HTTP_IF_MATCH="1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["commitment_history_unaffected"])

        deleted_before_anchor = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=datetime(2026, 3, 31, 8, tzinfo=UTC),
            end_time=datetime(2026, 3, 31, 9, tzinfo=UTC),
            is_active=False,
        )
        response = self.client.delete(
            reverse("api_v2:session-detail", args=[deleted_before_anchor.pk]),
            HTTP_IF_MATCH="1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["commitment_history_unaffected"])

        after_anchor = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=datetime(2026, 4, 1, 13, tzinfo=UTC),
            end_time=datetime(2026, 4, 1, 14, tzinfo=UTC),
            is_active=False,
        )
        with freeze_time("2026-04-02 12:00:00+00:00"):
            response = self.client.patch(
                reverse("api_v2:session-detail", args=[after_anchor.pk]),
                {"note": "new correction"},
                format="json",
                HTTP_IF_MATCH="1",
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("commitment_history_unaffected", response.json())

        self.client.delete(
            reverse("api_v2:commitment-detail", args=[commitment["id"]])
        )
        no_commitment = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=datetime(2026, 3, 29, 8, tzinfo=UTC),
            end_time=datetime(2026, 3, 29, 9, tzinfo=UTC),
            is_active=False,
        )
        response = self.client.patch(
            reverse("api_v2:session-detail", args=[no_commitment.pk]),
            {"note": "without commitment"},
            format="json",
            HTTP_IF_MATCH="1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("commitment_history_unaffected", response.json())

    def test_me_capabilities_include_commitments(self):
        response = self.client.get(reverse("api_v2:me"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("commitments", response.json()["capabilities"])
