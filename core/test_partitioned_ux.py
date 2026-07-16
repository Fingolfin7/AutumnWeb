from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from freezegun import freeze_time
from rest_framework.test import APIClient

from core.attribution import subproject_tally
from core.models import Projects, Sessions, SessionSubproject, SubProjects
from core.services import (
    DestructiveMutationService,
    DestructiveOperationError,
    SessionMutationService,
    even_split_bps,
)


UTC = datetime_timezone.utc


class EvenSplitTests(TestCase):
    def test_three_ids_put_remainder_on_lowest_id(self):
        self.assertEqual(even_split_bps([9, 2, 5]), {2: 3334, 5: 3333, 9: 3333})

    def test_one_id_gets_full_allocation(self):
        self.assertEqual(even_split_bps([7]), {7: 10000})


@freeze_time("2026-07-16 12:00:00")
class PartitionedSessionApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="partitioned-api")
        self.project = Projects.objects.create(user=self.user, name="Project")
        self.sub_a = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="A"
        )
        self.sub_b = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="B"
        )
        self.sub_c = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="C"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def payload(self, **updates):
        payload = {
            "project_id": self.project.pk,
            "start": "2026-07-16T09:00:00Z",
            "end": "2026-07-16T10:00:00Z",
        }
        payload.update(updates)
        return payload

    def test_track_explicit_allocations_round_trip(self):
        response = self.client.post(
            reverse("api_v2:sessions"),
            self.payload(
                allocation_mode="partitioned",
                subproject_allocations=[
                    {"subproject_id": self.sub_a.pk, "allocation_bp": 2500},
                    {"subproject_id": self.sub_b.pk, "allocation_bp": 6000},
                ],
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["allocation_mode"], "partitioned")
        self.assertEqual(
            [
                (item["subproject_id"], item["allocation_bp"])
                for item in response.json()["subproject_allocations"]
            ],
            [(self.sub_a.pk, 2500), (self.sub_b.pk, 6000)],
        )

    def test_track_without_explicit_bps_even_splits(self):
        response = self.client.post(
            reverse("api_v2:sessions"),
            self.payload(
                allocation_mode="partitioned",
                subproject_ids=[self.sub_c.pk, self.sub_a.pk, self.sub_b.pk],
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            {
                item["subproject_id"]: item["allocation_bp"]
                for item in response.json()["subproject_allocations"]
            },
            {self.sub_a.pk: 3334, self.sub_b.pk: 3333, self.sub_c.pk: 3333},
        )

    def test_total_over_10000_is_validation_error(self):
        response = self.client.post(
            reverse("api_v2:sessions"),
            self.payload(
                allocation_mode="partitioned",
                subproject_allocations=[
                    {"subproject_id": self.sub_a.pk, "allocation_bp": 6000},
                    {"subproject_id": self.sub_b.pk, "allocation_bp": 5000},
                ],
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "validation_error")
        self.assertFalse(Sessions.objects.filter(user=self.user).exists())

    def test_mode_switch_back_to_legacy_forces_full_credit(self):
        created = self.client.post(
            reverse("api_v2:sessions"),
            self.payload(
                allocation_mode="partitioned",
                subproject_allocations=[
                    {"subproject_id": self.sub_a.pk, "allocation_bp": 3000},
                    {"subproject_id": self.sub_b.pk, "allocation_bp": 7000},
                ],
            ),
            format="json",
        ).json()

        response = self.client.patch(
            reverse("api_v2:session-detail", args=[created["id"]]),
            {"allocation_mode": "legacy_full"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["allocation_mode"], "legacy_full")
        self.assertEqual(
            [item["allocation_bp"] for item in response.json()["subproject_allocations"]],
            [10000, 10000],
        )

    @override_settings(AUTUMN_PARTITIONED_ATTRIBUTION=False)
    def test_disabled_flag_returns_validation_error(self):
        response = self.client.post(
            reverse("api_v2:sessions"),
            self.payload(
                allocation_mode="partitioned",
                subproject_ids=[self.sub_a.pk],
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "validation_error")
        self.assertIn(
            "partitioned attribution is disabled",
            str(response.json()["error"]["details"]),
        )

    def test_v1_relation_patch_is_rejected_but_note_patch_is_allowed(self):
        session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=[self.sub_a],
            allocation_mode="partitioned",
            start_time=datetime(2026, 7, 16, 9, tzinfo=UTC),
            end_time=datetime(2026, 7, 16, 10, tzinfo=UTC),
            is_active=False,
        )
        SessionMutationService.set_allocations(
            session.pk,
            user=self.user,
            allocations=[(self.sub_a, 5000)],
            allocation_mode="partitioned",
        )
        self.client.force_authenticate(user=None)
        self.client.force_login(self.user)

        rejected = self.client.patch(
            reverse("api_edit_session", args=[session.pk]),
            {"subprojects": [self.sub_b.name]},
            content_type="application/json",
        )
        allowed = self.client.patch(
            reverse("api_edit_session", args=[session.pk]),
            {"note": "still editable"},
            content_type="application/json",
        )

        self.assertEqual(rejected.status_code, 409)
        self.assertIn("upgrade autumn-cli", rejected.json()["error"])
        self.assertEqual(allowed.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.note, "still editable")


class PartitionedMergeAndReadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="partitioned-merge")
        self.project = Projects.objects.create(user=self.user, name="Project")
        self.sub_a = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="A"
        )
        self.sub_b = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="B"
        )

    def session(self, *, seconds=100):
        start = datetime(2026, 7, 16, 9, tzinfo=UTC)
        return Sessions.objects.create(
            user=self.user,
            project=self.project,
            allocation_mode="partitioned",
            start_time=start,
            end_time=start + timedelta(seconds=seconds),
            is_active=False,
        )

    def test_merge_precondition_lists_session_and_changes_nothing(self):
        session = self.session()
        SessionSubproject.objects.create(
            session=session, subproject=self.sub_a, allocation_bp=6000
        )
        SessionSubproject.objects.create(
            session=session, subproject=self.sub_b, allocation_bp=5000
        )
        before = list(
            SessionSubproject.objects.filter(session=session)
            .order_by("subproject_id")
            .values_list("subproject_id", "allocation_bp")
        )

        with self.assertRaises(DestructiveOperationError) as raised:
            DestructiveMutationService.merge_subprojects(
                user=self.user,
                project_id=self.project.pk,
                name1="A",
                name2="B",
                new_name="Merged",
            )

        self.assertIn(str(session.pk), str(raised.exception))
        self.assertTrue(SubProjects.objects.filter(pk=self.sub_a.pk).exists())
        self.assertTrue(SubProjects.objects.filter(pk=self.sub_b.pk).exists())
        self.assertFalse(SubProjects.objects.filter(name="Merged").exists())
        self.assertEqual(
            list(
                SessionSubproject.objects.filter(session=session)
                .order_by("subproject_id")
                .values_list("subproject_id", "allocation_bp")
            ),
            before,
        )

    def test_merge_success_sums_bps_and_reads_include_residual(self):
        session = self.session(seconds=100)
        SessionSubproject.objects.create(
            session=session, subproject=self.sub_a, allocation_bp=3000
        )
        SessionSubproject.objects.create(
            session=session, subproject=self.sub_b, allocation_bp=2000
        )

        merged = DestructiveMutationService.merge_subprojects(
            user=self.user,
            project_id=self.project.pk,
            name1="A",
            name2="B",
            new_name="Merged",
        )

        link = SessionSubproject.objects.get(session=session)
        self.assertEqual(link.subproject_id, merged.pk)
        self.assertEqual(link.allocation_bp, 5000)
        rows = {
            row["name"]: row["total"]
            for row in subproject_tally(Sessions.objects.filter(pk=session.pk))
        }
        self.assertEqual(rows["Merged"], timedelta(seconds=50))
        self.assertEqual(rows["no subproject"], timedelta(seconds=50))

