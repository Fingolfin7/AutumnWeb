from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Commitment, Context, Projects, Tag


class V2ContextsTagsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="v2-contexts-tags", email="v2-contexts-tags@example.com"
        )
        self.other_user = User.objects.create_user(
            username="v2-contexts-tags-other",
            email="v2-contexts-tags-other@example.com",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _project(self, name, context):
        return Projects.objects.create(user=self.user, name=name, context=context)

    def test_context_crud_count_ordering_and_absent_delete(self):
        beta = Context.objects.create(user=self.user, name="Beta")
        alpha = Context.objects.create(user=self.user, name="Alpha")
        self._project("One", alpha)
        self._project("Two", alpha)
        self._project("Three", beta)

        listed = self.client.get(reverse("api_v2:contexts"))
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(
            listed.json(),
            {
                "count": 2,
                "contexts": [
                    {"id": alpha.id, "name": "Alpha", "description": None,
                     "project_count": 2},
                    {"id": beta.id, "name": "Beta", "description": None,
                     "project_count": 1},
                ],
            },
        )

        created = self.client.post(
            reverse("api_v2:contexts"), {"name": "  Study  "}, format="json"
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["name"], "Study")
        self.assertEqual(created.json()["project_count"], 0)

        patched = self.client.patch(
            reverse("api_v2:context-detail", args=[created.json()["id"]]),
            {"name": "Learning"},
            format="json",
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["name"], "Learning")

        deleted = self.client.delete(
            reverse("api_v2:context-detail", args=[created.json()["id"]])
        )
        absent = self.client.delete(
            reverse("api_v2:context-detail", args=[999999])
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(absent.status_code, 204)
        self.assertFalse(Context.objects.filter(pk=created.json()["id"]).exists())

    def test_tag_crud_count_ordering_and_absent_delete(self):
        context = Context.objects.create(user=self.user, name="Work")
        beta = Tag.objects.create(user=self.user, name="Beta")
        alpha = Tag.objects.create(user=self.user, name="Alpha")
        first = self._project("One", context)
        second = self._project("Two", context)
        first.tags.add(alpha, beta)
        second.tags.add(alpha)

        listed = self.client.get(reverse("api_v2:tags"))
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(
            listed.json(),
            {
                "count": 2,
                "tags": [
                    {"id": alpha.id, "name": "Alpha", "color": None,
                     "project_count": 2},
                    {"id": beta.id, "name": "Beta", "color": None,
                     "project_count": 1},
                ],
            },
        )

        created = self.client.post(
            reverse("api_v2:tags"), {"name": "  Focused  "}, format="json"
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["name"], "Focused")
        self.assertEqual(created.json()["project_count"], 0)

        patched = self.client.patch(
            reverse("api_v2:tag-detail", args=[created.json()["id"]]),
            {"name": "Deep Work"},
            format="json",
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["name"], "Deep Work")

        deleted = self.client.delete(
            reverse("api_v2:tag-detail", args=[created.json()["id"]])
        )
        absent = self.client.delete(reverse("api_v2:tag-detail", args=[999999]))
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(absent.status_code, 204)
        self.assertFalse(Tag.objects.filter(pk=created.json()["id"]).exists())

    def test_case_insensitive_duplicates_conflict_on_create_and_patch(self):
        Context.objects.create(user=self.user, name="Work")
        other_context = Context.objects.create(user=self.user, name="Personal")
        Tag.objects.create(user=self.user, name="Focus")
        other_tag = Tag.objects.create(user=self.user, name="Urgent")

        responses = (
            self.client.post(
                reverse("api_v2:contexts"), {"name": " work "}, format="json"
            ),
            self.client.patch(
                reverse("api_v2:context-detail", args=[other_context.id]),
                {"name": "WORK"}, format="json",
            ),
            self.client.post(
                reverse("api_v2:tags"), {"name": " focus "}, format="json"
            ),
            self.client.patch(
                reverse("api_v2:tag-detail", args=[other_tag.id]),
                {"name": "FOCUS"}, format="json",
            ),
        )
        for response in responses:
            with self.subTest(response=response):
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["error"]["code"], "conflict")

        other_context.refresh_from_db()
        other_tag.refresh_from_db()
        self.assertEqual(other_context.name, "Personal")
        self.assertEqual(other_tag.name, "Urgent")

    def test_name_validation_matches_v1_cleaning(self):
        cases = (
            (reverse("api_v2:contexts"), {"name": 123}),
            (reverse("api_v2:contexts"), {"name": "   "}),
            (reverse("api_v2:tags"), {"name": "x" * 101}),
        )
        for url, payload in cases:
            with self.subTest(payload=payload):
                response = self.client.post(url, payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json()["error"]["code"], "validation_error"
                )

    def test_commitment_targets_block_deletes_and_leave_data_untouched(self):
        context = Context.objects.create(user=self.user, name="Protected Context")
        tag = Tag.objects.create(user=self.user, name="Protected Tag")
        project = self._project("Protected Project", context)
        project.tags.add(tag)
        context_commitment = Commitment.objects.create(
            user=self.user, aggregation_type="context", context=context, target=60
        )
        tag_commitment = Commitment.objects.create(
            user=self.user, aggregation_type="tag", tag=tag, target=60
        )

        responses = (
            self.client.delete(reverse("api_v2:context-detail", args=[context.id])),
            self.client.delete(reverse("api_v2:tag-detail", args=[tag.id])),
        )
        for response in responses:
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["error"]["code"], "conflict")

        project.refresh_from_db()
        self.assertEqual(project.context_id, context.id)
        self.assertTrue(project.tags.filter(pk=tag.id).exists())
        self.assertTrue(Context.objects.filter(pk=context.id).exists())
        self.assertTrue(Tag.objects.filter(pk=tag.id).exists())
        self.assertTrue(Commitment.objects.filter(pk=context_commitment.id).exists())
        self.assertTrue(Commitment.objects.filter(pk=tag_commitment.id).exists())

    def test_foreign_context_and_tag_details_are_not_found(self):
        foreign_context = Context.objects.create(
            user=self.other_user, name="Foreign Context"
        )
        foreign_tag = Tag.objects.create(user=self.other_user, name="Foreign Tag")
        responses = (
            self.client.patch(
                reverse("api_v2:context-detail", args=[foreign_context.id]),
                {"name": "Nope"}, format="json",
            ),
            self.client.delete(
                reverse("api_v2:context-detail", args=[foreign_context.id])
            ),
            self.client.patch(
                reverse("api_v2:tag-detail", args=[foreign_tag.id]),
                {"name": "Nope"}, format="json",
            ),
            self.client.delete(reverse("api_v2:tag-detail", args=[foreign_tag.id])),
        )
        for response in responses:
            with self.subTest(response=response):
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_general_context_deletion_sets_project_context_to_null(self):
        general = Context.objects.create(user=self.user, name="General")
        project = self._project("General Project", general)
        response = self.client.delete(
            reverse("api_v2:context-detail", args=[general.id])
        )
        self.assertEqual(response.status_code, 204)
        project.refresh_from_db()
        self.assertIsNone(project.context_id)
        self.assertFalse(Context.objects.filter(pk=general.id).exists())

    def test_tag_deletion_detaches_projects(self):
        context = Context.objects.create(user=self.user, name="Work")
        tag = Tag.objects.create(user=self.user, name="Disposable")
        project = self._project("Tagged Project", context)
        project.tags.add(tag)
        response = self.client.delete(reverse("api_v2:tag-detail", args=[tag.id]))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(project.tags.filter(pk=tag.id).exists())
        self.assertTrue(Projects.objects.filter(pk=project.id).exists())

    def test_list_endpoints_each_use_one_query(self):
        contexts = [
            Context.objects.create(user=self.user, name=f"Context {index:02d}")
            for index in range(10)
        ]
        tags = [
            Tag.objects.create(user=self.user, name=f"Tag {index:02d}")
            for index in range(10)
        ]
        for index, context in enumerate(contexts):
            project = self._project(f"Project {index:02d}", context)
            project.tags.add(*tags[: index + 1])

        with self.assertNumQueries(1):
            contexts_response = self.client.get(reverse("api_v2:contexts"))
        with self.assertNumQueries(1):
            tags_response = self.client.get(reverse("api_v2:tags"))

        self.assertEqual(contexts_response.status_code, 200)
        self.assertEqual(tags_response.status_code, 200)
        self.assertEqual(contexts_response.json()["count"], 10)
        self.assertEqual(tags_response.json()["count"], 10)

    def test_me_advertises_context_and_tag_capabilities(self):
        response = self.client.get(reverse("api_v2:me"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("contexts", response.json()["capabilities"])
        self.assertIn("tags", response.json()["capabilities"])


class ContextDescriptionAndTagColorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="v2-meta-extras")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_context_description_round_trip(self):
        created = self.client.post(
            "/api/v2/contexts/",
            {"name": "Deep", "description": "Focus work"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["description"], "Focus work")

        cid = created.json()["id"]
        patched = self.client.patch(
            f"/api/v2/contexts/{cid}", {"description": "Updated"}, format="json"
        )
        if patched.status_code == 404:  # trailing-slash routing
            patched = self.client.patch(
                f"/api/v2/contexts/{cid}/", {"description": "Updated"}, format="json"
            )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["description"], "Updated")
        self.assertEqual(patched.json()["name"], "Deep")

    def test_tag_color_round_trip(self):
        created = self.client.post(
            "/api/v2/tags/", {"name": "focus", "color": "#aa3355"}, format="json"
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["color"], "#aa3355")

        tid = created.json()["id"]
        patched = self.client.patch(
            f"/api/v2/tags/{tid}", {"color": "blue"}, format="json"
        )
        if patched.status_code == 404:
            patched = self.client.patch(
                f"/api/v2/tags/{tid}/", {"color": "blue"}, format="json"
            )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["color"], "blue")

    def test_empty_write_rejected(self):
        response = self.client.post("/api/v2/contexts/", {}, format="json")
        self.assertEqual(response.status_code, 400)
