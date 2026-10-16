"""Project and subproject merges through /api/v2/ (the React merge pages post here).

Ported from the old merge page tests in core.tests: what ends up merged
(sessions, subprojects, descriptions, totals) and the ways a merge is refused.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Projects, Sessions, SubProjects
from core.totals import derived_project_totals, derived_subproject_totals


class MergeApiTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="merger", password="pw")
        self.client = APIClient()
        self.client.force_authenticate(self.user)


class MergeProjectsApiTests(MergeApiTestCase):
    def setUp(self):
        super().setUp()
        self.project1 = Projects.objects.create(
            user=self.user, name="Project A", description="Description for Project A"
        )
        self.project2 = Projects.objects.create(
            user=self.user, name="Project B", description="Description for Project B"
        )
        self.design_a = SubProjects.objects.create(
            user=self.user, name="Design", parent_project=self.project1
        )
        SubProjects.objects.create(user=self.user, name="Development", parent_project=self.project1)
        self.design_b = SubProjects.objects.create(
            user=self.user, name="Design", parent_project=self.project2
        )
        SubProjects.objects.create(user=self.user, name="Testing", parent_project=self.project2)
        self.session1 = self._session(self.project1, self.design_a, hours_ago=2)
        self.session2 = self._session(self.project2, self.design_b, hours_ago=3)

    def _session(self, project, sub, hours_ago):
        session = Sessions.objects.create(
            user=self.user,
            project=project,
            start_time=timezone.now() - timedelta(hours=hours_ago),
            end_time=timezone.now() - timedelta(hours=hours_ago - 1),
            is_active=False,
        )
        session.subprojects.add(sub)
        return session

    def _merge(self, **overrides):
        body = {
            "source_ids": [self.project1.pk, self.project2.pk],
            "new_name": "Merged Project",
            **overrides,
        }
        return self.client.post("/api/v2/projects/merge/", body, format="json")

    def test_merge_moves_sessions_and_subprojects_and_sums_the_time(self):
        response = self._merge()
        self.assertEqual(response.status_code, 201, response.content)

        self.assertFalse(Projects.objects.filter(name__in=["Project A", "Project B"]).exists())
        merged = Projects.objects.get(name="Merged Project")
        self.assertEqual(merged.user, self.user)
        self.assertIn("Merged from 'Project A' and 'Project B'", merged.description)
        self.assertIn("--- Project A Description ---", merged.description)
        self.assertIn("--- Project B Description ---", merged.description)
        self.assertEqual(set(merged.sessions.all()), {self.session1, self.session2})
        names = {sub.name for sub in merged.subprojects.all()}
        self.assertEqual(names, {"Design", "Design (Project B)", "Development", "Testing"})
        # Two one-hour sessions.
        self.assertAlmostEqual(derived_project_totals(self.user, [merged.pk])[merged.pk], 120.0, places=2)
        self.assertAlmostEqual(response.json()["total_minutes"], 120.0, places=2)

    def test_a_name_that_is_already_taken_is_refused_and_nothing_changes(self):
        Projects.objects.create(user=self.user, name="Merged Project")
        response = self._merge()
        self.assertEqual(response.status_code, 409)
        self.assertIn("already", response.json()["error"]["message"].lower())
        self.assertTrue(Projects.objects.filter(name="Project A").exists())
        self.assertTrue(Projects.objects.filter(name="Project B").exists())
        self.session1.refresh_from_db()
        self.assertEqual(self.session1.project, self.project1)


    def test_another_users_project_is_not_found(self):
        other = User.objects.create_user(username="other", email="o@example.com", password="pw")
        foreign = Projects.objects.create(user=other, name="Foreign")
        response = self._merge(source_ids=[self.project1.pk, foreign.pk])
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Projects.objects.filter(pk=foreign.pk).exists())
        self.assertTrue(Projects.objects.filter(pk=self.project1.pk).exists())


class MergeSubprojectsApiTests(MergeApiTestCase):
    def setUp(self):
        super().setUp()
        self.parent = Projects.objects.create(user=self.user, name="Parent Project")
        self.design = SubProjects.objects.create(
            user=self.user,
            name="Design",
            parent_project=self.parent,
            description="Design subproject description",
        )
        self.ui = SubProjects.objects.create(
            user=self.user,
            name="UI",
            parent_project=self.parent,
            description="UI subproject description",
        )
        self.session1 = self._session(self.design, hours_ago=2)
        self.session2 = self._session(self.ui, hours_ago=3)

    def _session(self, sub, hours_ago):
        session = Sessions.objects.create(
            user=self.user,
            project=self.parent,
            start_time=timezone.now() - timedelta(hours=hours_ago),
            end_time=timezone.now() - timedelta(hours=hours_ago - 1),
            is_active=False,
        )
        session.subprojects.add(sub)
        return session

    def _merge(self, **overrides):
        body = {
            "project_id": self.parent.pk,
            "source_ids": [self.design.pk, self.ui.pk],
            "new_name": "Design & UI",
            **overrides,
        }
        return self.client.post("/api/v2/subprojects/merge/", body, format="json")

    def test_merge_moves_sessions_and_sums_the_time(self):
        response = self._merge()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertFalse(SubProjects.objects.filter(name__in=["Design", "UI"]).exists())
        merged = SubProjects.objects.get(name="Design & UI")
        self.assertEqual(merged.user, self.user)
        self.assertEqual(merged.parent_project, self.parent)
        self.assertIn("Merged from 'Design' and 'UI'", merged.description)
        self.assertIn("--- Design Description ---", merged.description)
        self.assertIn("--- UI Description ---", merged.description)
        self.assertEqual(set(merged.sessions.all()), {self.session1, self.session2})
        self.assertAlmostEqual(
            derived_subproject_totals(self.user, [merged.pk])[merged.pk], 120.0, places=2
        )

    def test_a_name_that_is_already_taken_in_the_project_is_refused(self):
        SubProjects.objects.create(user=self.user, name="Design & UI", parent_project=self.parent)
        response = self._merge()
        self.assertEqual(response.status_code, 409)
        self.assertTrue(SubProjects.objects.filter(name="Design").exists())
        self.assertTrue(SubProjects.objects.filter(name="UI").exists())
