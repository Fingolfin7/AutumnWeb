from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from freezegun import freeze_time
from rest_framework.test import APIClient

from core.models import Commitment, Context, Projects, Sessions, SubProjects, Tag
from core.services import SessionMutationService


UTC = datetime_timezone.utc


class V2ProjectSubprojectTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="v2-projects", email="v2-projects@example.com"
        )
        self.other_user = User.objects.create_user(
            username="v2-projects-other", email="v2-projects-other@example.com"
        )
        self.context = Context.objects.create(user=self.user, name="Work")
        self.other_context = Context.objects.create(user=self.user, name="Personal")
        self.tag_a = Tag.objects.create(user=self.user, name="Alpha")
        self.tag_b = Tag.objects.create(user=self.user, name="Beta")
        self.foreign_tag = Tag.objects.create(user=self.other_user, name="Foreign")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _project(self, name, **fields):
        fields.setdefault("context", self.context)
        return Projects.objects.create(user=self.user, name=name, **fields)

    def _commitment(self, *, kind, target):
        return Commitment.objects.create(
            user=self.user,
            aggregation_type=kind,
            target=60,
            **{kind: target},
        )

    @freeze_time("2026-07-16 12:00:00")
    def test_project_and_subproject_crud_detail_and_derived_fields(self):
        created = self.client.post(
            reverse("api_v2:projects"),
            {
                "name": "Created",
                "description": "Initial",
                "status": "paused",
                "context_id": self.context.id,
                "tag_ids": [self.tag_b.id, self.tag_a.id],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        project_id = created.json()["id"]
        self.assertEqual(created.json()["description"], "Initial")
        self.assertEqual(created.json()["status"], "paused")
        self.assertEqual(created.json()["context"]["id"], self.context.id)
        self.assertEqual(
            [tag["name"] for tag in created.json()["tags"]], ["Alpha", "Beta"]
        )

        sub_created = self.client.post(
            reverse("api_v2:project-subprojects", args=[project_id]),
            {"name": "Build", "description": "Sub description"},
            format="json",
        )
        self.assertEqual(sub_created.status_code, 201)
        subproject_id = sub_created.json()["id"]

        project = Projects.objects.get(pk=project_id)
        subproject = SubProjects.objects.get(pk=subproject_id)
        end = datetime(2026, 7, 15, 10, 30, tzinfo=UTC)
        SessionMutationService.create_session(
            user=self.user,
            project=project,
            subprojects=[subproject],
            start_time=end - timedelta(minutes=90.125),
            end_time=end,
            is_active=False,
        )
        Sessions.objects.create(
            user=self.user,
            project=project,
            start_time=end,
            end_time=None,
            is_active=True,
        )

        detail = self.client.get(
            reverse("api_v2:project-detail", args=[project_id])
        )
        self.assertEqual(detail.status_code, 200)
        body = detail.json()
        self.assertEqual(body["total_minutes"], 90.13)
        self.assertEqual(body["session_count"], 1)
        self.assertEqual(body["last_activity"], "2026-07-15")
        self.assertEqual(len(body["subprojects"]), 1)
        self.assertEqual(body["subprojects"][0]["total_minutes"], 90.13)
        self.assertEqual(body["subprojects"][0]["session_count"], 1)
        self.assertEqual(body["subprojects"][0]["last_activity"], "2026-07-15")

        nested = self.client.get(
            reverse("api_v2:project-subprojects", args=[project_id])
        )
        self.assertEqual(nested.status_code, 200)
        self.assertEqual(nested.json()["count"], 1)

        sub_patched = self.client.patch(
            reverse("api_v2:subproject-detail", args=[subproject_id]),
            {"name": "Built", "description": "Updated sub"},
            format="json",
        )
        self.assertEqual(sub_patched.status_code, 200)
        self.assertEqual(sub_patched.json()["name"], "Built")
        self.assertEqual(sub_patched.json()["description"], "Updated sub")

        patched = self.client.patch(
            reverse("api_v2:project-detail", args=[project_id]),
            {
                "name": "Renamed",
                "description": "Updated",
                "status": "complete",
                "context_id": None,
                "tag_ids": [],
                "start_date": "2025-01-02",
            },
            format="json",
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["name"], "Renamed")
        self.assertEqual(patched.json()["description"], "Updated")
        self.assertEqual(patched.json()["status"], "complete")
        self.assertIsNone(patched.json()["context"])
        self.assertEqual(patched.json()["tags"], [])
        self.assertEqual(patched.json()["start_date"], "2025-01-02")

        sub_detail = self.client.get(
            reverse("api_v2:subproject-detail", args=[subproject_id])
        )
        self.assertEqual(sub_detail.status_code, 200)
        self.assertEqual(sub_detail.json()["project_id"], project_id)

    def test_duplicate_create_and_renames_return_conflict(self):
        first = self._project("Same")
        second = self._project("Other")
        sub_a = SubProjects.objects.create(
            user=self.user, parent_project=first, name="Sub A"
        )
        SubProjects.objects.create(
            user=self.user, parent_project=first, name="Sub B"
        )

        duplicate = self.client.post(
            reverse("api_v2:projects"), {"name": "Same"}, format="json"
        )
        rename = self.client.patch(
            reverse("api_v2:project-detail", args=[second.id]),
            {"name": "Same"},
            format="json",
        )
        sub_rename = self.client.patch(
            reverse("api_v2:subproject-detail", args=[sub_a.id]),
            {"name": "Sub B"},
            format="json",
        )

        for response in (duplicate, rename, sub_rename):
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["error"]["code"], "conflict")

    def test_project_merge_preserves_descriptions_sessions_and_collisions(self):
        first = self._project("First", description="First text")
        second = self._project("Second", description="Second text")
        first_sub = SubProjects.objects.create(
            user=self.user, parent_project=first, name="Shared"
        )
        second_sub = SubProjects.objects.create(
            user=self.user, parent_project=second, name="Shared"
        )
        end = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
        first_session = SessionMutationService.create_session(
            user=self.user,
            project=first,
            subprojects=[first_sub],
            start_time=end - timedelta(minutes=20),
            end_time=end,
            is_active=False,
        )
        second_session = SessionMutationService.create_session(
            user=self.user,
            project=second,
            subprojects=[second_sub],
            start_time=end - timedelta(minutes=40),
            end_time=end,
            is_active=False,
        )

        response = self.client.post(
            reverse("api_v2:project-merge"),
            {"source_ids": [first.id, second.id], "new_name": "Combined"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        merged_id = response.json()["id"]
        self.assertEqual(
            response.json()["description"],
            "Merged from 'First' and 'Second'\n\n"
            "--- First Description ---\nFirst text\n\n"
            "--- Second Description ---\nSecond text",
        )
        self.assertEqual(response.json()["total_minutes"], 60.0)
        self.assertFalse(Projects.objects.filter(pk__in=[first.id, second.id]).exists())
        self.assertEqual(
            list(
                SubProjects.objects.filter(parent_project_id=merged_id)
                .order_by("name")
                .values_list("name", flat=True)
            ),
            ["Shared", "Shared (Second)"],
        )
        self.assertEqual(
            set(
                Sessions.objects.filter(pk__in=[first_session.id, second_session.id])
                .values_list("project_id", flat=True)
            ),
            {merged_id},
        )

    def test_subproject_merge_happy_path(self):
        project = self._project("Parent")
        first = SubProjects.objects.create(
            user=self.user, parent_project=project, name="One", description="1"
        )
        second = SubProjects.objects.create(
            user=self.user, parent_project=project, name="Two", description="2"
        )

        response = self.client.post(
            reverse("api_v2:subproject-merge"),
            {
                "project_id": project.id,
                "source_ids": [first.id, second.id],
                "new_name": "Merged",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["name"], "Merged")
        self.assertEqual(
            response.json()["description"],
            "Merged from 'One' and 'Two'\n\n"
            "--- One Description ---\n1\n\n--- Two Description ---\n2",
        )
        self.assertFalse(
            SubProjects.objects.filter(pk__in=[first.id, second.id]).exists()
        )

    def test_merge_and_delete_commitment_protection_are_conflicts_and_atomic(self):
        first = self._project("Protected")
        second = self._project("Other")
        commitment = self._commitment(kind="project", target=first)

        merge = self.client.post(
            reverse("api_v2:project-merge"),
            {"source_ids": [first.id, second.id], "new_name": "Blocked"},
            format="json",
        )
        self.assertEqual(merge.status_code, 409)
        self.assertEqual(merge.json()["error"]["code"], "conflict")
        self.assertTrue(Projects.objects.filter(pk=first.id).exists())
        self.assertTrue(Projects.objects.filter(pk=second.id).exists())
        self.assertFalse(Projects.objects.filter(name="Blocked").exists())
        self.assertTrue(Commitment.objects.filter(pk=commitment.id).exists())

        delete = self.client.delete(
            reverse("api_v2:project-detail", args=[first.id])
        )
        self.assertEqual(delete.status_code, 409)
        self.assertEqual(delete.json()["error"]["code"], "conflict")
        self.assertTrue(Projects.objects.filter(pk=first.id).exists())

    def test_subproject_delete_protection_success_and_absent(self):
        project = self._project("Parent")
        protected = SubProjects.objects.create(
            user=self.user, parent_project=project, name="Protected"
        )
        disposable = SubProjects.objects.create(
            user=self.user, parent_project=project, name="Disposable"
        )
        self._commitment(kind="subproject", target=protected)

        blocked = self.client.delete(
            reverse("api_v2:subproject-detail", args=[protected.id])
        )
        deleted = self.client.delete(
            reverse("api_v2:subproject-detail", args=[disposable.id])
        )
        absent = self.client.delete(
            reverse("api_v2:subproject-detail", args=[999999])
        )

        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(absent.status_code, 204)
        self.assertTrue(SubProjects.objects.filter(pk=protected.id).exists())
        self.assertFalse(SubProjects.objects.filter(pk=disposable.id).exists())

    def test_project_delete_success_and_absent(self):
        project = self._project("Disposable")
        deleted = self.client.delete(
            reverse("api_v2:project-detail", args=[project.id])
        )
        absent = self.client.delete(
            reverse("api_v2:project-detail", args=[999999])
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(absent.status_code, 204)
        self.assertFalse(Projects.objects.filter(pk=project.id).exists())

    def test_filters_pagination_and_ordering(self):
        active_alpha = self._project("Alpha match", status="active")
        paused_match = self._project(
            "Beta match", status="paused", context=self.other_context
        )
        excluded = self._project("Gamma match", status="active")
        unrelated = self._project("Zeta", status="active")
        active_alpha.tags.add(self.tag_a)
        paused_match.tags.add(self.tag_b)
        excluded.tags.add(self.tag_a)

        cases = (
            ({"status": "paused"}, {paused_match.id}),
            ({"search": "MATCH"}, {active_alpha.id, paused_match.id, excluded.id}),
            ({"context_ids": self.other_context.id}, {paused_match.id}),
            ({"tag_ids": self.tag_a.id}, {active_alpha.id, excluded.id}),
            (
                {"exclude_project_ids": excluded.id},
                {active_alpha.id, paused_match.id, unrelated.id},
            ),
        )
        for params, expected_ids in cases:
            with self.subTest(params=params):
                response = self.client.get(reverse("api_v2:projects"), params)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    {project["id"] for project in response.json()["projects"]},
                    expected_ids,
                )

        page = self.client.get(
            reverse("api_v2:projects"),
            {"limit": 2, "offset": 1, "ordering": "id"},
        )
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.json()["total"], 4)
        self.assertEqual(page.json()["count"], 2)
        self.assertEqual(
            [project["id"] for project in page.json()["projects"]],
            [paused_match.id, excluded.id],
        )

        by_name = self.client.get(reverse("api_v2:projects"))
        self.assertEqual(
            [project["name"] for project in by_name.json()["projects"]],
            ["Alpha match", "Beta match", "Gamma match", "Zeta"],
        )

    def test_foreign_resources_are_not_found_and_unknown_tag_is_validation_error(self):
        foreign_project = Projects.objects.create(
            user=self.other_user, name="Foreign Project"
        )
        foreign_subproject = SubProjects.objects.create(
            user=self.other_user,
            parent_project=foreign_project,
            name="Foreign Subproject",
        )

        project_detail = self.client.get(
            reverse("api_v2:project-detail", args=[foreign_project.id])
        )
        subproject_detail = self.client.get(
            reverse("api_v2:subproject-detail", args=[foreign_subproject.id])
        )
        nested = self.client.get(
            reverse("api_v2:project-subprojects", args=[foreign_project.id])
        )
        unknown_tag = self.client.post(
            reverse("api_v2:projects"),
            {"name": "Invalid tag", "tag_ids": [self.foreign_tag.id]},
            format="json",
        )

        for response in (project_detail, subproject_detail, nested):
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["error"]["code"], "not_found")
        self.assertEqual(unknown_tag.status_code, 400)
        self.assertEqual(
            unknown_tag.json()["error"]["code"], "validation_error"
        )

    def test_project_list_query_count_is_constant(self):
        for index in range(12):
            project = self._project(f"Project {index:02d}")
            project.tags.add(self.tag_a, self.tag_b)

        with self.assertNumQueries(3):
            response = self.client.get(reverse("api_v2:projects"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 12)

    def test_me_advertises_project_capabilities(self):
        response = self.client.get(reverse("api_v2:me"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("projects", response.json()["capabilities"])
        self.assertIn("subprojects", response.json()["capabilities"])
