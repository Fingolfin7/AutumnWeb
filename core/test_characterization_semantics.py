"""Synthetic characterization of current attribution and period semantics."""

import copy
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from core.commitments import reconcile_commitment
from core.importer import run_import
from core.models import Commitment, Projects, Sessions, SubProjects


class CurrentAttributionSemanticsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="chz-attribution")
        self.client.force_login(self.user)
        self.project = Projects.objects.create(user=self.user, name="Project")
        self.sub_a = SubProjects.objects.create(user=self.user, parent_project=self.project, name="A")
        self.sub_b = SubProjects.objects.create(user=self.user, parent_project=self.project, name="B")
        start = timezone.make_aware(datetime(2025, 1, 1, 9, 0))
        self.linked = Sessions.objects.create(
            user=self.user, project=self.project, start_time=start,
            end_time=start + timedelta(minutes=60), is_active=False,
        )
        self.linked.subprojects.add(self.sub_a, self.sub_b)
        self.unlinked = Sessions.objects.create(
            user=self.user, project=self.project, start_time=start + timedelta(hours=2),
            end_time=start + timedelta(hours=2, minutes=30), is_active=False,
        )

    def test_full_credit_and_no_subproject_bucket(self):
        # characterizes current behavior
        subprojects = self.client.get("/api/tally_by_subprojects/").json()
        self.assertEqual(
            {row["name"]: row["total_time"] for row in subprojects},
            {"A": 60.0, "B": 60.0, "no subproject": 30.0},
        )
        projects = self.client.get("/api/tally_by_sessions/").json()
        self.assertEqual(projects, [{"name": "Project", "total_time": 90.0}])

    def test_hierarchy_children_are_non_additive(self):
        # characterizes current behavior
        hierarchy = self.client.get("/api/hierarchy/").json()
        project = hierarchy["children"][0]["children"][0]
        self.assertEqual(project["total_time"], 90.0)
        self.assertEqual(
            {child["name"]: child["total_time"] for child in project["children"]},
            {"A": 60.0, "B": 60.0},
        )
        self.assertEqual(sum(child["total_time"] for child in project["children"]), 120.0)


class CurrentMergeSemanticsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="chz-merge")
        self.client.force_login(self.user)

    def test_subproject_merge_collapses_duplicate_links(self):
        # characterizes current behavior
        project = Projects.objects.create(user=self.user, name="Parent")
        sub_a = SubProjects.objects.create(user=self.user, parent_project=project, name="A")
        sub_b = SubProjects.objects.create(user=self.user, parent_project=project, name="B")
        start = timezone.make_aware(datetime(2025, 1, 1, 9, 0))
        session = Sessions.objects.create(
            user=self.user, project=project, start_time=start,
            end_time=start + timedelta(minutes=60), is_active=False,
        )
        session.subprojects.add(sub_a, sub_b)
        response = self.client.post(
            "/api/merge_subprojects/",
            data={"project_id": project.id, "subproject1": "A", "subproject2": "B", "new_subproject_name": "M"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        session.refresh_from_db()
        self.assertEqual(list(session.subprojects.values_list("name", flat=True)), ["M"])
        merged = SubProjects.objects.get(parent_project=project, name="M")
        project.refresh_from_db()
        self.assertEqual(merged.total_time, 60.0)
        self.assertEqual(project.total_time, 0.0)

    def test_project_merge_preserves_both_duplicate_named_subprojects(self):
        # characterizes current behavior
        project_a = Projects.objects.create(user=self.user, name="Project A")
        project_b = Projects.objects.create(user=self.user, name="Project B")
        SubProjects.objects.create(user=self.user, parent_project=project_a, name="Shared")
        SubProjects.objects.create(user=self.user, parent_project=project_b, name="Shared")
        response = self.client.post(
            "/api/merge_projects/",
            data={"project1": "Project A", "project2": "Project B", "new_project_name": "Merged"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        merged = Projects.objects.get(user=self.user, name="Merged")
        self.assertEqual(
            sorted(merged.subprojects.values_list("name", flat=True)),
            ["Shared", "Shared (Project B)"],
        )


class CurrentCommitmentPathDependenceTests(TestCase):
    @freeze_time("2025-01-01 12:00:00+00:00")
    def test_clamp_then_truncate_plus_1000_cap_600_minus_500(self):
        # characterizes current behavior
        user = User.objects.create_user(username="chz-commitment")
        project = Projects.objects.create(user=user, name="Commitment")
        commitment = Commitment.objects.create(
            user=user,
            project=project,
            aggregation_type="project",
            commitment_type="time",
            period="daily",
            start_date=timezone.localdate(),
            target=500,
            balance=0,
            max_balance=600,
            min_balance=-600,
            banking_enabled=True,
        )
        # The session ends in the first period and contributes its full 1500 minutes.
        Sessions.objects.create(
            user=user,
            project=project,
            start_time=timezone.make_aware(datetime(2024, 12, 31, 0, 0)),
            end_time=timezone.make_aware(datetime(2025, 1, 1, 1, 0)),
            is_active=False,
        )
        with freeze_time("2025-01-02 12:00:00+00:00"):
            self.assertTrue(reconcile_commitment(commitment))
            commitment.refresh_from_db()
            first_balance = commitment.balance
        with freeze_time("2025-01-03 12:00:00+00:00"):
            self.assertTrue(reconcile_commitment(commitment))
            commitment.refresh_from_db()
            second_balance = commitment.balance
        self.assertEqual((first_balance, second_balance), (600, 100))


class CurrentDateAndImportSemanticsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="chz-boundaries")
        self.client.force_login(self.user)
        self.project = Projects.objects.create(user=self.user, name="Boundary")

    @freeze_time("2025-01-15 12:00:00+00:00")
    def test_date_filter_uses_inclusive_calendar_day_boundaries(self):
        # characterizes current behavior
        times = (
            datetime(2025, 1, 9, 23, 59, 59),
            datetime(2025, 1, 10, 0, 0, 0),
            datetime(2025, 1, 10, 23, 59, 59),
            datetime(2025, 1, 11, 0, 0, 0),
        )
        sessions = []
        for end in times:
            end_aware = timezone.make_aware(end)
            sessions.append(
                Sessions.objects.create(
                    user=self.user, project=self.project,
                    start_time=end_aware - timedelta(minutes=1), end_time=end_aware,
                    is_active=False,
                )
            )
        response = self.client.get(
            "/api/sessions/search/",
            {"start_date": "2025-01-10", "end_date": "2025-01-10"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in response.json()["sessions"]],
            [sessions[2].id, sessions[1].id],
        )

    def test_legacy_import_deduplicates_within_two_minutes(self):
        # characterizes current behavior
        payload = {
            "Imported": {
                "Start Date": "01-02-2025",
                "Last Updated": "01-02-2025",
                "Total Time": 60.0,
                "Status": "active",
                "Description": "",
                "Sub Projects": {},
                "Session History": [{
                    "Date": "01-02-2025", "Start Time": "09:00:00",
                    "End Time": "10:00:00", "Sub-Projects": [], "Note": "same",
                }],
            }
        }
        first = run_import(self.user, payload)
        shifted = copy.deepcopy(payload)
        shifted["Imported"]["Session History"][0]["Start Time"] = "09:01:59"
        shifted["Imported"]["Session History"][0]["End Time"] = "10:01:59"
        second = run_import(self.user, shifted, merge=True, tolerance=2)
        self.assertEqual(first["sessions_imported"], 1)
        self.assertEqual(second["sessions_imported"], 0)
        self.assertEqual(Sessions.objects.filter(user=self.user, project__name="Imported").count(), 1)
