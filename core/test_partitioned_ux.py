from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth.models import User
from django.test import TestCase
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
                subproject_allocations=[
                    {"subproject_id": self.sub_a.pk, "allocation_bp": 2500},
                    {"subproject_id": self.sub_b.pk, "allocation_bp": 6000},
                ],
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertNotIn("allocation_mode", response.json())
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

    def test_patch_bare_subproject_ids_re_even_splits(self):
        created = self.client.post(
            reverse("api_v2:sessions"),
            self.payload(
                subproject_allocations=[
                    {"subproject_id": self.sub_a.pk, "allocation_bp": 3000},
                    {"subproject_id": self.sub_b.pk, "allocation_bp": 7000},
                ],
            ),
            format="json",
        ).json()

        response = self.client.patch(
            reverse("api_v2:session-detail", args=[created["id"]]),
            {"subproject_ids": [self.sub_c.pk, self.sub_a.pk, self.sub_b.pk]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {
                item["subproject_id"]: item["allocation_bp"]
                for item in response.json()["subproject_allocations"]
            },
            {self.sub_a.pk: 3334, self.sub_b.pk: 3333, self.sub_c.pk: 3333},
        )

    def test_create_service_three_subprojects_defaults_to_even_split(self):
        session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=[self.sub_c, self.sub_a, self.sub_b],
        )
        self.assertEqual(
            dict(
                session.subproject_links.values_list(
                    "subproject_id", "allocation_bp"
                )
            ),
            {self.sub_a.pk: 3334, self.sub_b.pk: 3333, self.sub_c.pk: 3333},
        )



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

