from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from core.models import Projects, SubProjects, Sessions, Commitment
from django.contrib.auth.models import User
from datetime import datetime, timedelta
from django.core.management import call_command
from django.conf import settings
import io
import json
import os
from core.models import Context
from rest_framework.authtoken.models import Token
from core.utils import (
    get_period_bounds,
    get_commitment_progress,
    reconcile_commitment,
    calculate_daily_activity_streak,
    calculate_commitment_streak,
)


class UpdateSessionTests(TestCase):
    def setUp(self):
        # Create a user
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

        # Create a project
        self.project = Projects.objects.create(user=self.user, name="Test Project")

        # Create subprojects
        self.subproject1 = SubProjects.objects.create(
            user=self.user, name="Subproject 1", parent_project=self.project
        )
        self.subproject2 = SubProjects.objects.create(
            user=self.user, name="Subproject 2", parent_project=self.project
        )

        # Create an initial session
        self.session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            is_active=False,
        )
        self.session.subprojects.add(self.subproject1)

    def test_update_session_updates_total_time(self):
        # Verify initial total times
        self.project.refresh_from_db()
        self.subproject1.refresh_from_db()
        self.subproject2.refresh_from_db()
        self.assertAlmostEqual(
            self.project.total_time, 60.0, places=2
        )  # 1 hour, with 2 decimal precision
        self.assertAlmostEqual(self.subproject1.total_time, 60.0, places=2)
        self.assertAlmostEqual(self.subproject2.total_time, 0.0, places=2)

        # Prepare data for updating the session
        new_start_time = timezone.now() - timedelta(hours=3)
        new_end_time = timezone.now() - timedelta(hours=2)
        update_data = {
            "project_name": self.project.name,
            "start_time": new_start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": new_end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": "Updated session",
            "subprojects": [self.subproject2.name],  # Change subproject
        }

        # Call the update_session view
        response = self.client.post(
            reverse("update_session", args=[self.session.id]), data=update_data
        )

        self.assertEqual(response.status_code, 302)  # Redirect after successful update

        self.project.refresh_from_db()
        self.subproject1.refresh_from_db()
        self.subproject2.refresh_from_db()

        # Verify updated total times
        self.assertAlmostEqual(
            self.project.total_time, 60.0, places=2
        )  # Still 1 hour, but reassigned
        self.assertAlmostEqual(self.subproject1.total_time, 0.0, places=2)
        self.assertAlmostEqual(self.subproject2.total_time, 60.0, places=2)


class StopTimerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")
        self.project = Projects.objects.create(user=self.user, name="Test Project")
        self.subproject = SubProjects.objects.create(
            user=self.user, name="Subproject", parent_project=self.project
        )

        # Create an active session (with no end time and is_active=True)
        self.session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=timezone.now() - timedelta(hours=1),
            is_active=True,
        )
        self.session.subprojects.add(self.subproject)

    def test_stop_timer(self):
        response = self.client.post(reverse("stop_timer", args=[self.session.id]))
        self.assertEqual(response.status_code, 302)  # Expecting a redirect

        # Refresh session and project from DB
        self.session.refresh_from_db()
        self.project.refresh_from_db()
        self.subproject.refresh_from_db()

        # Verify session is stopped: is_active should be False and end_time not None
        self.assertFalse(self.session.is_active)
        self.assertIsNotNone(self.session.end_time)

        # Check that audit has updated total time; assume the duration is computed correctly.
        expected_duration = self.session.duration
        self.assertAlmostEqual(self.project.total_time, expected_duration, places=2)
        self.assertAlmostEqual(self.subproject.total_time, expected_duration, places=2)


class DeleteSessionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")
        self.project = Projects.objects.create(user=self.user, name="Test Project")

        self.subproject1 = SubProjects.objects.create(
            user=self.user, name="Subproject 1", parent_project=self.project
        )
        self.subproject2 = SubProjects.objects.create(
            user=self.user, name="Subproject 2", parent_project=self.project
        )

        self.session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            is_active=False,
        )

        self.session.subprojects.add(self.subproject1, self.subproject2)

    def test_delete_session(self):
        self.project.refresh_from_db()
        self.subproject1.refresh_from_db()
        self.subproject2.refresh_from_db()

        # Verify initial total times
        self.assertAlmostEqual(
            self.project.total_time, 60.0, places=2
        )  # 1 hour, with 2 decimal precision
        self.assertAlmostEqual(self.subproject1.total_time, 60.0, places=2)
        self.assertAlmostEqual(self.subproject2.total_time, 60.0, places=2)

        response = self.client.post(reverse("delete_session", args=[self.session.id]))
        self.assertEqual(response.status_code, 302)  # Expecting a redirect

        # Verify the session no longer exists
        session_exists = Sessions.objects.filter(id=self.session.id).exists()
        self.assertFalse(session_exists)

        self.project.refresh_from_db()
        self.subproject1.refresh_from_db()
        self.subproject2.refresh_from_db()

        # Verify the project's and subprojects' total time is updated after deletion
        self.assertAlmostEqual(self.project.total_time, 0.0, places=2)
        self.assertAlmostEqual(self.subproject1.total_time, 0.0, places=2)
        self.assertAlmostEqual(self.subproject2.total_time, 0.0, places=2)


class MergeProjectsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

        # Create two projects to merge
        self.project1 = Projects.objects.create(
            user=self.user,
            name="Project A",
            description="Description for Project A",
            total_time=120.0,  # 2 hours
        )
        self.project2 = Projects.objects.create(
            user=self.user,
            name="Project B",
            description="Description for Project B",
            total_time=180.0,  # 3 hours
        )

        # Create subprojects for each project
        self.subproject1a = SubProjects.objects.create(
            user=self.user, name="Design", parent_project=self.project1, total_time=60.0
        )
        self.subproject1b = SubProjects.objects.create(
            user=self.user,
            name="Development",
            parent_project=self.project1,
            total_time=60.0,
        )
        self.subproject2a = SubProjects.objects.create(
            user=self.user,
            name="Design",  # Same name as project1's subproject
            parent_project=self.project2,
            total_time=90.0,
        )
        self.subproject2b = SubProjects.objects.create(
            user=self.user,
            name="Testing",
            parent_project=self.project2,
            total_time=90.0,
        )

        # Create sessions for each project
        self.session1 = Sessions.objects.create(
            user=self.user,
            project=self.project1,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            is_active=False,
        )
        self.session1.subprojects.add(self.subproject1a)

        self.session2 = Sessions.objects.create(
            user=self.user,
            project=self.project2,
            start_time=timezone.now() - timedelta(hours=3),
            end_time=timezone.now() - timedelta(hours=2),
            is_active=False,
        )
        self.session2.subprojects.add(self.subproject2a)

    def test_merge_projects_success(self):
        """Test successful project merge"""
        response = self.client.post(
            reverse("merge_projects"),
            {
                "project1": "Project A",
                "project2": "Project B",
                "new_project_name": "Merged Project",
            },
        )

        self.assertEqual(response.status_code, 302)  # Redirect after success

        # Check that original projects are deleted
        self.assertFalse(Projects.objects.filter(name="Project A").exists())
        self.assertFalse(Projects.objects.filter(name="Project B").exists())

        # Check that merged project exists
        merged_project = Projects.objects.get(name="Merged Project")
        self.assertEqual(merged_project.user, self.user)
        self.assertIn(
            "Merged from 'Project A' and 'Project B'", merged_project.description
        )
        self.assertIn("--- Project A Description ---", merged_project.description)
        self.assertIn("--- Project B Description ---", merged_project.description)

        # Check that sessions were moved
        self.assertEqual(merged_project.sessions.count(), 2)
        self.assertIn(self.session1, merged_project.sessions.all())
        self.assertIn(self.session2, merged_project.sessions.all())

        # Check that subprojects were moved (with conflict resolution)
        subproject_names = [sp.name for sp in merged_project.subprojects.all()]
        self.assertIn("Design", subproject_names)  # From project1
        self.assertIn("Design (Project B)", subproject_names)  # Renamed from project2
        self.assertIn("Development", subproject_names)
        self.assertIn("Testing", subproject_names)

        # Check total time was recalculated (based on actual session durations)
        # Each session is 1 hour (60 minutes), so 2 sessions = 120 minutes
        self.assertAlmostEqual(merged_project.total_time, 120.0, places=2)

    def test_merge_projects_duplicate_name(self):
        """Test merge fails when new project name already exists"""
        # Create a project with the target name
        Projects.objects.create(user=self.user, name="Merged Project")

        response = self.client.post(
            reverse("merge_projects"),
            {
                "project1": "Project A",
                "project2": "Project B",
                "new_project_name": "Merged Project",
            },
        )

        self.assertEqual(response.status_code, 200)  # Form with errors
        self.assertContains(response, "You already have a project with this name")

        # Check that original projects still exist
        self.assertTrue(Projects.objects.filter(name="Project A").exists())
        self.assertTrue(Projects.objects.filter(name="Project B").exists())

    def test_merge_projects_same_project(self):
        """Test merge fails when trying to merge a project with itself"""
        response = self.client.post(
            reverse("merge_projects"),
            {
                "project1": "Project A",
                "project2": "Project A",
                "new_project_name": "Merged Project",
            },
        )

        self.assertEqual(response.status_code, 200)  # Form with errors
        self.assertContains(response, "Cannot merge a project with itself")

    def test_merge_projects_invalid_form(self):
        """Test merge fails with invalid form data"""
        response = self.client.post(
            reverse("merge_projects"),
            {
                "project1": "Project A",
                # Missing project2 and new_project_name
            },
        )

        self.assertEqual(response.status_code, 200)  # Form with errors
        self.assertContains(response, "Invalid form data")


class MergeSubProjectsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

        # Create a parent project
        self.parent_project = Projects.objects.create(
            user=self.user,
            name="Parent Project",
            total_time=240.0,  # 4 hours
        )

        # Create two subprojects to merge
        self.subproject1 = SubProjects.objects.create(
            user=self.user,
            name="Design",
            parent_project=self.parent_project,
            description="Design subproject description",
            total_time=120.0,  # 2 hours
        )
        self.subproject2 = SubProjects.objects.create(
            user=self.user,
            name="UI",
            parent_project=self.parent_project,
            description="UI subproject description",
            total_time=120.0,  # 2 hours
        )

        # Create sessions for each subproject
        self.session1 = Sessions.objects.create(
            user=self.user,
            project=self.parent_project,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            is_active=False,
        )
        self.session1.subprojects.add(self.subproject1)

        self.session2 = Sessions.objects.create(
            user=self.user,
            project=self.parent_project,
            start_time=timezone.now() - timedelta(hours=3),
            end_time=timezone.now() - timedelta(hours=2),
            is_active=False,
        )
        self.session2.subprojects.add(self.subproject2)

    def test_merge_subprojects_success(self):
        """Test successful subproject merge"""
        response = self.client.post(
            reverse("merge_subprojects", args=[self.parent_project.id]),
            {
                "subproject1": "Design",
                "subproject2": "UI",
                "new_subproject_name": "Design & UI",
            },
        )

        self.assertEqual(response.status_code, 302)  # Redirect after success

        # Check that original subprojects are deleted
        self.assertFalse(SubProjects.objects.filter(name="Design").exists())
        self.assertFalse(SubProjects.objects.filter(name="UI").exists())

        # Check that merged subproject exists
        merged_subproject = SubProjects.objects.get(name="Design & UI")
        self.assertEqual(merged_subproject.user, self.user)
        self.assertEqual(merged_subproject.parent_project, self.parent_project)
        self.assertIn("Merged from 'Design' and 'UI'", merged_subproject.description)
        self.assertIn("--- Design Description ---", merged_subproject.description)
        self.assertIn("--- UI Description ---", merged_subproject.description)

        # Check that sessions were moved
        self.assertEqual(merged_subproject.sessions.count(), 2)
        self.assertIn(self.session1, merged_subproject.sessions.all())
        self.assertIn(self.session2, merged_subproject.sessions.all())

        # Check total time was recalculated (based on actual session durations)
        # Each session is 1 hour (60 minutes), so 2 sessions = 120 minutes
        self.assertAlmostEqual(merged_subproject.total_time, 120.0, places=2)

    def test_merge_subprojects_duplicate_name(self):
        """Test merge fails when new subproject name already exists"""
        # Create a subproject with the target name
        SubProjects.objects.create(
            user=self.user, name="Design & UI", parent_project=self.parent_project
        )

        response = self.client.post(
            reverse("merge_subprojects", args=[self.parent_project.id]),
            {
                "subproject1": "Design",
                "subproject2": "UI",
                "new_subproject_name": "Design & UI",
            },
        )

        self.assertEqual(response.status_code, 200)  # Form with errors
        self.assertContains(
            response, "You already have a subproject with this name in this project"
        )

        # Check that original subprojects still exist
        self.assertTrue(SubProjects.objects.filter(name="Design").exists())
        self.assertTrue(SubProjects.objects.filter(name="UI").exists())

    def test_merge_subprojects_same_subproject(self):
        """Test merge fails when trying to merge a subproject with itself"""
        response = self.client.post(
            reverse("merge_subprojects", args=[self.parent_project.id]),
            {
                "subproject1": "Design",
                "subproject2": "Design",
                "new_subproject_name": "Merged Subproject",
            },
        )

        self.assertEqual(response.status_code, 200)  # Form with errors
        self.assertContains(response, "Cannot merge a subproject with itself")

    def test_merge_subprojects_invalid_form(self):
        """Test merge fails with invalid form data"""
        response = self.client.post(
            reverse("merge_subprojects", args=[self.parent_project.id]),
            {
                "subproject1": "Design",
                # Missing subproject2 and new_subproject_name
            },
        )

        self.assertEqual(response.status_code, 200)  # Form with errors
        self.assertContains(response, "Invalid form data")


class MergeProjectsAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

        # Create two projects to merge
        self.project1 = Projects.objects.create(
            user=self.user,
            name="Project A",
            description="Description for Project A",
            total_time=120.0,
        )
        self.project2 = Projects.objects.create(
            user=self.user,
            name="Project B",
            description="Description for Project B",
            total_time=180.0,
        )

    def test_merge_projects_api_success(self):
        """Test successful project merge via API"""
        response = self.client.post(
            "/api/merge_projects/",
            {
                "project1": "Project A",
                "project2": "Project B",
                "new_project_name": "Merged Project",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("Successfully merged", data["message"])
        self.assertEqual(data["project"]["name"], "Merged Project")

        # Check that original projects are deleted
        self.assertFalse(Projects.objects.filter(name="Project A").exists())
        self.assertFalse(Projects.objects.filter(name="Project B").exists())

    def test_merge_projects_api_missing_parameters(self):
        """Test API fails with missing parameters"""
        response = self.client.post(
            "/api/merge_projects/",
            {
                "project1": "Project A",
                # Missing project2 and new_project_name
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("required", data["error"])

    def test_merge_projects_api_duplicate_name(self):
        """Test API fails when new project name already exists"""
        Projects.objects.create(user=self.user, name="Merged Project")

        response = self.client.post(
            "/api/merge_projects/",
            {
                "project1": "Project A",
                "project2": "Project B",
                "new_project_name": "Merged Project",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("already exists", data["error"])


class MergeSubProjectsAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

        # Create a parent project
        self.parent_project = Projects.objects.create(
            user=self.user, name="Parent Project"
        )

        # Create two subprojects to merge
        self.subproject1 = SubProjects.objects.create(
            user=self.user,
            name="Design",
            parent_project=self.parent_project,
            total_time=120.0,
        )
        self.subproject2 = SubProjects.objects.create(
            user=self.user,
            name="UI",
            parent_project=self.parent_project,
            total_time=120.0,
        )

    def test_merge_subprojects_api_success(self):
        """Test successful subproject merge via API"""
        response = self.client.post(
            "/api/merge_subprojects/",
            {
                "subproject1": "Design",
                "subproject2": "UI",
                "new_subproject_name": "Design & UI",
                "project_id": self.parent_project.id,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("Successfully merged", data["message"])
        self.assertEqual(data["subproject"]["name"], "Design & UI")

        # Check that original subprojects are deleted
        self.assertFalse(SubProjects.objects.filter(name="Design").exists())
        self.assertFalse(SubProjects.objects.filter(name="UI").exists())

    def test_merge_subprojects_api_missing_parameters(self):
        """Test API fails with missing parameters"""
        response = self.client.post(
            "/api/merge_subprojects/",
            {
                "subproject1": "Design",
                # Missing other parameters
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("required", data["error"])

    def test_merge_subprojects_api_duplicate_name(self):
        """Test API fails when new subproject name already exists"""
        SubProjects.objects.create(
            user=self.user, name="Design & UI", parent_project=self.parent_project
        )

        response = self.client.post(
            "/api/merge_subprojects/",
            {
                "subproject1": "Design",
                "subproject2": "UI",
                "new_subproject_name": "Design & UI",
                "project_id": self.parent_project.id,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("already exists", data["error"])


class ImportIntoContextCLITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="importuser", password="password")

    def _write_temp_import_json(self, payload: dict) -> str:
        temp_dir = os.path.join(settings.MEDIA_ROOT, "temp_tests")
        os.makedirs(temp_dir, exist_ok=True)
        path = os.path.join(temp_dir, "import_cli_test.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        return path

    def test_cli_import_into_new_context_overrides_file_context(self):
        payload = {
            "Project One": {
                "Start Date": "01-01-2024",
                "Last Updated": "01-02-2024",
                "Total Time": 0.0,
                "Description": "",
                "Status": "active",
                "Context": "FileContext",
                "Tags": [],
                "Sub Projects": {},
                "Session History": [],
            },
            "Project Two": {
                "Start Date": "02-01-2024",
                "Last Updated": "02-02-2024",
                "Total Time": 0.0,
                "Description": "",
                "Status": "active",
                "Context": "FileContext",
                "Tags": [],
                "Sub Projects": {},
                "Session History": [],
            },
        }
        path = self._write_temp_import_json(payload)

        out = io.StringIO()
        call_command(
            "import",
            self.user.username,
            path,
            "--context",
            "ImportedCtx",
            "--create-context",
            stdout=out,
        )

        imported_ctx = Context.objects.get(user=self.user, name="ImportedCtx")
        self.assertEqual(
            Projects.objects.filter(user=self.user, context=imported_ctx).count(), 2
        )

        # Ensure file context didn't get created/used
        self.assertFalse(
            Context.objects.filter(user=self.user, name="FileContext").exists()
        )


class ImportIntoContextUITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="importui", password="password")
        self.client.login(username="importui", password="password")

    def _make_upload_file(self, payload: dict, name: str = "import_ui_test.json"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(
            name,
            json.dumps(payload).encode("utf-8"),
            content_type="application/json",
        )

    def _consume_event_stream(self, response) -> str:
        chunks = []
        for chunk in response.streaming_content:
            if isinstance(chunk, bytes):
                chunk = chunk.decode("utf-8", errors="ignore")
            chunks.append(chunk)
        return "".join(chunks)

    def test_ui_import_under_existing_context(self):
        # pre-create a destination context
        dest_ctx = Context.objects.create(user=self.user, name="DestCtx")

        payload = {
            "UI Project": {
                "Start Date": "03-01-2024",
                "Last Updated": "03-02-2024",
                "Total Time": 0.0,
                "Description": "",
                "Status": "active",
                "Context": "FileContext",
                "Tags": [],
                "Sub Projects": {},
                "Session History": [],
            }
        }

        resp = self.client.post(
            reverse("import"),
            data={
                "file": self._make_upload_file(payload),
                "merge": "on",
                "tolerance": "0.5",
                "import_context": str(dest_ctx.id),
            },
        )
        self.assertEqual(resp.status_code, 200)

        # start streaming import
        stream_resp = self.client.get(reverse("import_stream"))
        self.assertEqual(stream_resp.status_code, 200)
        stream_text = self._consume_event_stream(stream_resp)
        self.assertIn("Import completed successfully", stream_text)

        proj = Projects.objects.get(user=self.user, name="UI Project")
        self.assertEqual(proj.context_id, dest_ctx.id)
        self.assertFalse(
            Context.objects.filter(user=self.user, name="FileContext").exists()
        )

    def test_ui_import_new_context_wins_over_dropdown_and_shows_notification(self):
        dropdown_ctx = Context.objects.create(user=self.user, name="DropdownCtx")

        payload = {
            "UI Project 2": {
                "Start Date": "04-01-2024",
                "Last Updated": "04-02-2024",
                "Total Time": 0.0,
                "Description": "",
                "Status": "active",
                "Context": "FileContext",
                "Tags": [],
                "Sub Projects": {},
                "Session History": [],
            }
        }

        # Provide BOTH: dropdown + new context name -> new name wins
        resp = self.client.post(
            reverse("import"),
            data={
                "file": self._make_upload_file(payload),
                "merge": "on",
                "tolerance": "0.5",
                "import_context": str(dropdown_ctx.id),
                "import_context_new": "NewCtxWins",
            },
        )

        # The form warns via a field error (surfaced as JSON)
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertIn("errors", body)
        self.assertIn("import_context", body["errors"])

        # Now submit with only new context to proceed
        resp2 = self.client.post(
            reverse("import"),
            data={
                "file": self._make_upload_file(payload, name="import_ui_test2.json"),
                "merge": "on",
                "tolerance": "0.5",
                "import_context_new": "NewCtxWins",
            },
        )
        self.assertEqual(resp2.status_code, 200)

        stream_resp = self.client.get(reverse("import_stream"))
        self.assertEqual(stream_resp.status_code, 200)
        stream_text = self._consume_event_stream(stream_resp)
        self.assertIn("Import completed successfully", stream_text)

        new_ctx = Context.objects.get(user=self.user, name="NewCtxWins")
        proj = Projects.objects.get(user=self.user, name="UI Project 2")
        self.assertEqual(proj.context_id, new_ctx.id)


class ProjectsGroupedApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")
        # DRF token auth for API endpoints
        self.token = Token.objects.create(user=self.user)

    def test_projects_grouped_includes_archived_and_returns_200(self):
        Projects.objects.create(user=self.user, name="Active Project", status="active")
        Projects.objects.create(
            user=self.user, name="Archived Project", status="archived"
        )

        url = reverse("api_projects_grouped")
        response = self.client.get(url, HTTP_AUTHORIZATION=f"Token {self.token.key}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertIn("projects", payload)
        self.assertIn("archived", payload["projects"])
        self.assertIn("Archived Project", payload["projects"]["archived"])
        self.assertIn("summary", payload)
        self.assertEqual(payload["summary"]["archived"], 1)


class TrackApiRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="trackuser", password="password")
        self.client.login(username="trackuser", password="password")
        self.token = Token.objects.create(user=self.user)

        self.project = Projects.objects.create(user=self.user, name="Track Project")

    def test_track_session_does_not_double_count_project_total(self):
        sp1 = SubProjects.objects.create(
            user=self.user,
            name="SP1",
            parent_project=self.project,
        )
        sp2 = SubProjects.objects.create(
            user=self.user,
            name="SP2",
            parent_project=self.project,
        )

        start = timezone.now().replace(microsecond=0) - timedelta(minutes=9)
        end = start + timedelta(minutes=9)

        resp = self.client.post(
            reverse("api_track"),
            data={
                "project": self.project.name,
                # core.utils.parse_date_or_datetime does not accept full ISO with timezone
                # (e.g. 2026-01-28T10:00:00+00:00), so use a supported format.
                "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end": end.strftime("%Y-%m-%d %H:%M:%S"),
                "subprojects": [sp1.name, sp2.name],
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )

        self.assertEqual(resp.status_code, 201)
        self.project.refresh_from_db()
        self.assertAlmostEqual(self.project.total_time, 9.0, places=2)

        sp1.refresh_from_db()
        sp2.refresh_from_db()
        self.assertAlmostEqual(sp1.total_time, 9.0, places=2)
        self.assertAlmostEqual(sp2.total_time, 9.0, places=2)


# =============================================================================
# Commitment Feature Tests
# =============================================================================


class CommitmentModelTests(TestCase):
    """Test the Commitment model."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='commituser',
            email='commit@example.com',
            password='testpass123'
        )
        self.context = Context.objects.create(user=self.user, name='General')
        self.project = Projects.objects.create(
            user=self.user,
            name='Commitment Test Project',
            context=self.context
        )

    def test_create_time_commitment(self):
        """Test creating a time-based commitment."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=300
        )
        self.assertEqual(commitment.commitment_type, 'time')
        self.assertEqual(commitment.period, 'weekly')
        self.assertEqual(commitment.target, 300)
        self.assertEqual(commitment.balance, 0)
        self.assertTrue(commitment.active)
        self.assertTrue(commitment.banking_enabled)

    def test_create_session_commitment(self):
        """Test creating a session-based commitment."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='sessions',
            period='daily',
            target=2
        )
        self.assertEqual(commitment.commitment_type, 'sessions')
        self.assertEqual(commitment.target, 2)

    def test_commitment_str(self):
        """Test the string representation of a commitment."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=300
        )
        self.assertIn('Commitment Test Project', str(commitment))
        self.assertIn('300', str(commitment))
        self.assertIn('weekly', str(commitment))

    def test_one_to_one_constraint(self):
        """Test that a project can only have one commitment."""
        Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=300
        )
        with self.assertRaises(Exception):
            Commitment.objects.create(
                user=self.user,
                project=self.project,
                commitment_type='sessions',
                period='daily',
                target=5
            )


class PeriodBoundsTests(TestCase):
    """Test the get_period_bounds utility function."""

    def test_daily_bounds(self):
        """Test daily period bounds."""
        ref_date = timezone.make_aware(datetime(2025, 6, 15, 14, 30))
        start, end = get_period_bounds('daily', ref_date)

        self.assertEqual(start.date(), datetime(2025, 6, 15).date())
        self.assertEqual(end.date(), datetime(2025, 6, 16).date())

    def test_weekly_bounds_monday_start(self):
        """Test that weekly periods start on Monday."""
        ref_date = timezone.make_aware(datetime(2025, 6, 18, 14, 30))
        start, end = get_period_bounds('weekly', ref_date)

        self.assertEqual(start.date(), datetime(2025, 6, 16).date())
        self.assertEqual(end.date(), datetime(2025, 6, 23).date())

    def test_weekly_bounds_on_monday(self):
        """Test weekly bounds when reference is Monday."""
        ref_date = timezone.make_aware(datetime(2025, 6, 16, 14, 30))
        start, end = get_period_bounds('weekly', ref_date)

        self.assertEqual(start.date(), datetime(2025, 6, 16).date())
        self.assertEqual(end.date(), datetime(2025, 6, 23).date())

    def test_monthly_bounds(self):
        """Test monthly period bounds."""
        ref_date = timezone.make_aware(datetime(2025, 6, 15, 14, 30))
        start, end = get_period_bounds('monthly', ref_date)

        self.assertEqual(start.date(), datetime(2025, 6, 1).date())
        self.assertEqual(end.date(), datetime(2025, 7, 1).date())

    def test_quarterly_bounds_q2(self):
        """Test quarterly period bounds for Q2."""
        ref_date = timezone.make_aware(datetime(2025, 5, 15, 14, 30))
        start, end = get_period_bounds('quarterly', ref_date)

        self.assertEqual(start.date(), datetime(2025, 4, 1).date())
        self.assertEqual(end.date(), datetime(2025, 7, 1).date())

    def test_quarterly_bounds_q4(self):
        """Test quarterly period bounds for Q4."""
        ref_date = timezone.make_aware(datetime(2025, 11, 15, 14, 30))
        start, end = get_period_bounds('quarterly', ref_date)

        self.assertEqual(start.date(), datetime(2025, 10, 1).date())
        self.assertEqual(end.date(), datetime(2026, 1, 1).date())

    def test_yearly_bounds(self):
        """Test yearly period bounds."""
        ref_date = timezone.make_aware(datetime(2025, 6, 15, 14, 30))
        start, end = get_period_bounds('yearly', ref_date)

        self.assertEqual(start.date(), datetime(2025, 1, 1).date())
        self.assertEqual(end.date(), datetime(2026, 1, 1).date())

    def test_fortnightly_bounds(self):
        """Test fortnightly period bounds."""
        ref_date = timezone.make_aware(datetime(2025, 6, 18, 14, 30))
        start, end = get_period_bounds('fortnightly', ref_date)

        self.assertEqual((end - start).days, 14)


class CommitmentProgressTests(TestCase):
    """Test the get_commitment_progress utility function."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='progressuser',
            email='progress@example.com',
            password='testpass123'
        )
        self.context = Context.objects.create(user=self.user, name='General')
        self.project = Projects.objects.create(
            user=self.user,
            name='Progress Test Project',
            context=self.context
        )

    def test_progress_with_no_sessions(self):
        """Test progress calculation with no sessions."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=300
        )
        progress = get_commitment_progress(commitment)

        self.assertEqual(progress['actual'], 0)
        self.assertEqual(progress['target'], 300)
        self.assertEqual(progress['percentage'], 0)
        self.assertEqual(progress['status'], 'behind')

    def test_time_based_progress(self):
        """Test time-based progress calculation."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=100
        )

        now = timezone.now()
        period_start, _ = get_period_bounds('weekly', now)
        session_start = period_start + timedelta(hours=1)

        Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=session_start,
            end_time=session_start + timedelta(minutes=60),
            is_active=False
        )

        progress = get_commitment_progress(commitment)

        self.assertEqual(progress['actual'], 60)
        self.assertEqual(progress['percentage'], 60.0)
        self.assertEqual(progress['status'], 'on-track')

    def test_session_based_progress(self):
        """Test session-based progress calculation."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='sessions',
            period='weekly',
            target=5
        )

        now = timezone.now()
        period_start, _ = get_period_bounds('weekly', now)

        for i in range(3):
            session_start = period_start + timedelta(hours=i + 1)
            Sessions.objects.create(
                user=self.user,
                project=self.project,
                start_time=session_start,
                end_time=session_start + timedelta(minutes=30),
                is_active=False
            )

        progress = get_commitment_progress(commitment)

        self.assertEqual(progress['actual'], 3)
        self.assertEqual(progress['target'], 5)
        self.assertEqual(progress['percentage'], 60.0)

    def test_complete_status(self):
        """Test that 100%+ progress shows complete status."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='sessions',
            period='weekly',
            target=2
        )

        now = timezone.now()
        period_start, _ = get_period_bounds('weekly', now)

        for i in range(3):
            session_start = period_start + timedelta(hours=i + 1)
            Sessions.objects.create(
                user=self.user,
                project=self.project,
                start_time=session_start,
                end_time=session_start + timedelta(minutes=30),
                is_active=False
            )

        progress = get_commitment_progress(commitment)

        self.assertEqual(progress['status'], 'complete')
        self.assertEqual(progress['percentage'], 100)


class ReconciliationTests(TestCase):
    """Test the reconcile_commitment utility function."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='reconuser',
            email='recon@example.com',
            password='testpass123'
        )
        self.context = Context.objects.create(user=self.user, name='General')
        self.project = Projects.objects.create(
            user=self.user,
            name='Reconciliation Test Project',
            context=self.context
        )

    def test_balance_capping_max(self):
        """Test that balance is capped at max_balance."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='daily',
            target=60,
            max_balance=100,
            min_balance=-100,
            banking_enabled=True
        )

        commitment.balance = 90
        commitment.save()

        self.assertTrue(commitment.balance <= commitment.max_balance)

    def test_balance_capping_min(self):
        """Test that balance is capped at min_balance."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='daily',
            target=60,
            max_balance=100,
            min_balance=-100,
            banking_enabled=True
        )

        commitment.balance = -90
        commitment.save()

        self.assertTrue(commitment.balance >= commitment.min_balance)

    def test_skip_reconciliation_when_banking_disabled(self):
        """Test that balance doesn't change when banking is disabled."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=300,
            banking_enabled=False
        )

        initial_balance = commitment.balance
        reconcile_commitment(commitment)

        self.assertEqual(commitment.balance, initial_balance)


class CommitmentViewTests(TestCase):
    """Test the commitment views."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='viewuser',
            email='view@example.com',
            password='testpass123'
        )
        self.context = Context.objects.create(user=self.user, name='General')
        self.project = Projects.objects.create(
            user=self.user,
            name='View Test Project',
            context=self.context
        )
        self.client.login(username='viewuser', password='testpass123')

    def test_create_commitment_view_get(self):
        """Test GET request to create commitment page."""
        response = self.client.get(
            reverse('create_commitment', kwargs={'project_pk': self.project.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/create_commitment.html')

    def test_create_commitment_view_post(self):
        """Test POST request to create commitment."""
        response = self.client.post(
            reverse('create_commitment', kwargs={'project_pk': self.project.pk}),
            {
                'commitment_type': 'time',
                'period': 'weekly',
                'target': 300,
                'banking_enabled': True,
                'max_balance': 600,
                'min_balance': -600,
            }
        )
        self.assertEqual(response.status_code, 302)

        commitment = Commitment.objects.get(project=self.project)
        self.assertEqual(commitment.target, 300)
        self.assertEqual(commitment.commitment_type, 'time')

    def test_update_commitment_view_get(self):
        """Test GET request to update commitment page."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=300
        )
        response = self.client.get(
            reverse('update_commitment', kwargs={'pk': commitment.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/update_commitment.html')

    def test_update_commitment_view_post(self):
        """Test POST request to update commitment."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=300
        )
        response = self.client.post(
            reverse('update_commitment', kwargs={'pk': commitment.pk}),
            {
                'commitment_type': 'time',
                'period': 'daily',
                'target': 60,
                'banking_enabled': True,
                'max_balance': 600,
                'min_balance': -600,
                'active': True,
            }
        )
        self.assertEqual(response.status_code, 302)

        commitment.refresh_from_db()
        self.assertEqual(commitment.period, 'daily')
        self.assertEqual(commitment.target, 60)

    def test_delete_commitment_view_get(self):
        """Test GET request to delete commitment page."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=300
        )
        response = self.client.get(
            reverse('delete_commitment', kwargs={'pk': commitment.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/delete_commitment.html')

    def test_delete_commitment_view_post(self):
        """Test POST request to delete commitment."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=300
        )
        response = self.client.post(
            reverse('delete_commitment', kwargs={'pk': commitment.pk})
        )
        self.assertEqual(response.status_code, 302)

        self.assertFalse(Commitment.objects.filter(pk=commitment.pk).exists())

    def test_views_require_login(self):
        """Test that commitment views require login."""
        self.client.logout()

        response = self.client.get(
            reverse('create_commitment', kwargs={'project_pk': self.project.pk})
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_cannot_access_other_users_commitment(self):
        """Test that users cannot access other users' commitments."""
        other_user = User.objects.create_user(
            username='otherviewuser',
            email='otherview@example.com',
            password='otherpass123'
        )
        other_context = Context.objects.create(user=other_user, name='General')
        other_project = Projects.objects.create(
            user=other_user,
            name='Other View Project',
            context=other_context
        )
        other_commitment = Commitment.objects.create(
            user=other_user,
            project=other_project,
            commitment_type='time',
            period='weekly',
            target=300
        )

        response = self.client.get(
            reverse('update_commitment', kwargs={'pk': other_commitment.pk})
        )
        self.assertEqual(response.status_code, 404)


class UpdateProjectViewCommitmentTests(TestCase):
    """Test that the UpdateProjectView correctly shows commitment info."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='projviewuser',
            email='projview@example.com',
            password='testpass123'
        )
        self.context = Context.objects.create(user=self.user, name='General')
        self.project = Projects.objects.create(
            user=self.user,
            name='Proj View Test Project',
            context=self.context
        )
        self.client.login(username='projviewuser', password='testpass123')

    def test_project_page_shows_no_commitment(self):
        """Test project page when no commitment exists."""
        response = self.client.get(
            reverse('update_project', kwargs={'pk': self.project.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No commitment set')
        self.assertContains(response, 'Add Commitment')

    def test_project_page_shows_commitment(self):
        """Test project page when commitment exists."""
        Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=300
        )
        response = self.client.get(
            reverse('update_project', kwargs={'pk': self.project.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '300')
        self.assertContains(response, 'Edit Commitment')


class ProjectsListViewCommitmentTests(TestCase):
    """Test that the ProjectsListView includes commitment progress."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='listviewuser',
            email='listview@example.com',
            password='testpass123'
        )
        self.context = Context.objects.create(user=self.user, name='General')
        self.project = Projects.objects.create(
            user=self.user,
            name='List View Test Project',
            context=self.context
        )
        self.client.login(username='listviewuser', password='testpass123')

    def test_projects_list_includes_commitment_progress(self):
        """Test that commitment progress is included in context."""
        Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='sessions',
            period='weekly',
            target=5
        )
        response = self.client.get(reverse('projects'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('commitment_progress', response.context)
        self.assertIn(self.project.id, response.context['commitment_progress'])

    def test_projects_list_no_commitment(self):
        """Test projects list when no commitment exists."""
        response = self.client.get(reverse('projects'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('commitment_progress', response.context)
        self.assertEqual(len(response.context['commitment_progress']), 0)


# =============================================================================
# Dashboard Feature Tests
# =============================================================================


class DashboardViewTests(TestCase):
    """Test the DashboardView."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='dashuser',
            email='dash@example.com',
            password='testpass123'
        )
        self.context = Context.objects.create(user=self.user, name='General')
        self.project = Projects.objects.create(
            user=self.user,
            name='Dashboard Test Project',
            context=self.context
        )
        self.client.login(username='dashuser', password='testpass123')

    def test_dashboard_loads_successfully(self):
        """Test that the dashboard page loads."""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/dashboard.html')

    def test_dashboard_shows_quick_stats(self):
        """Test that quick stats are in context."""
        response = self.client.get(reverse('home'))
        self.assertIn('today_total', response.context)
        self.assertIn('week_total', response.context)
        self.assertIn('active_timers_count', response.context)

    def test_dashboard_shows_active_timers_count(self):
        """Test that active timers count is correct."""
        # Create an active timer
        Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=timezone.now() - timedelta(hours=1),
            is_active=True
        )
        response = self.client.get(reverse('home'))
        self.assertEqual(response.context['active_timers_count'], 1)

    def test_dashboard_shows_commitments_with_progress(self):
        """Test that commitments with progress are displayed."""
        Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=300
        )
        response = self.client.get(reverse('home'))
        self.assertIn('commitments_data', response.context)
        self.assertEqual(len(response.context['commitments_data']), 1)
        self.assertIn('progress', response.context['commitments_data'][0])
        self.assertIn('streak', response.context['commitments_data'][0])

    def test_dashboard_shows_daily_streak(self):
        """Test that daily streak data is displayed."""
        response = self.client.get(reverse('home'))
        self.assertIn('daily_streak', response.context)
        self.assertIn('current_streak', response.context['daily_streak'])
        self.assertIn('recent_days', response.context['daily_streak'])

    def test_dashboard_requires_login(self):
        """Test that dashboard requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)


class DailyStreakTests(TestCase):
    """Test the calculate_daily_activity_streak function."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='streakuser',
            email='streak@example.com',
            password='testpass123'
        )
        self.context = Context.objects.create(user=self.user, name='General')
        self.project = Projects.objects.create(
            user=self.user,
            name='Streak Test Project',
            context=self.context
        )

    def test_streak_zero_with_no_sessions(self):
        """Test that streak is 0 with no sessions."""
        result = calculate_daily_activity_streak(self.user)
        self.assertEqual(result['current_streak'], 0)

    def test_streak_counts_consecutive_days(self):
        """Test that streak counts consecutive days correctly."""
        now = timezone.now()
        # Create sessions for today and yesterday
        for i in range(3):
            day_start = now - timedelta(days=i)
            Sessions.objects.create(
                user=self.user,
                project=self.project,
                start_time=day_start - timedelta(hours=1),
                end_time=day_start,
                is_active=False
            )
        result = calculate_daily_activity_streak(self.user)
        self.assertEqual(result['current_streak'], 3)

    def test_streak_breaks_on_gap_day(self):
        """Test that streak breaks when there's a gap."""
        now = timezone.now()
        # Create session for today
        Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=now - timedelta(hours=1),
            end_time=now,
            is_active=False
        )
        # Create session for 2 days ago (skipping yesterday)
        day_before = now - timedelta(days=2)
        Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=day_before - timedelta(hours=1),
            end_time=day_before,
            is_active=False
        )
        result = calculate_daily_activity_streak(self.user)
        self.assertEqual(result['current_streak'], 1)

    def test_streak_returns_14_days_visual(self):
        """Test that 14 days are returned for visual display."""
        result = calculate_daily_activity_streak(self.user)
        self.assertEqual(len(result['recent_days']), 14)

    def test_streak_starts_from_yesterday_if_no_activity_today(self):
        """Test that streak calculation starts from yesterday if no activity today."""
        now = timezone.now()
        # Create sessions for yesterday and day before
        for i in range(1, 3):
            day = now - timedelta(days=i)
            Sessions.objects.create(
                user=self.user,
                project=self.project,
                start_time=day - timedelta(hours=1),
                end_time=day,
                is_active=False
            )
        result = calculate_daily_activity_streak(self.user)
        self.assertEqual(result['current_streak'], 2)


class CommitmentStreakTests(TestCase):
    """Test the calculate_commitment_streak function."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='commitstreakuser',
            email='commitstreak@example.com',
            password='testpass123'
        )
        self.context = Context.objects.create(user=self.user, name='General')
        self.project = Projects.objects.create(
            user=self.user,
            name='Commitment Streak Test Project',
            context=self.context
        )

    def test_commitment_streak_zero_with_no_sessions(self):
        """Test that commitment streak is 0 with no sessions."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=300
        )
        result = calculate_commitment_streak(commitment)
        self.assertEqual(result['current_streak'], 0)

    def test_commitment_streak_counts_consecutive_met_periods(self):
        """Test that commitment streak counts consecutive met periods."""
        now = timezone.now()

        # Create commitment with created_at in the past (before the periods we're testing)
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='sessions',
            period='daily',
            target=1
        )
        # Manually set created_at to 5 days ago so periods aren't skipped
        Commitment.objects.filter(pk=commitment.pk).update(
            created_at=now - timedelta(days=5)
        )
        commitment.refresh_from_db()

        # Create sessions for yesterday and day before (within their period bounds)
        for i in range(1, 3):
            # Get the period bounds for each day
            day = now - timedelta(days=i)
            period_start, period_end = get_period_bounds('daily', day)
            # Create a session in the middle of that period
            session_time = period_start + timedelta(hours=12)
            Sessions.objects.create(
                user=self.user,
                project=self.project,
                start_time=session_time - timedelta(hours=1),
                end_time=session_time,
                is_active=False
            )

        result = calculate_commitment_streak(commitment)
        self.assertGreaterEqual(result['current_streak'], 1)

    def test_commitment_streak_returns_periods_list(self):
        """Test that commitment streak returns a list of periods."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=60
        )
        result = calculate_commitment_streak(commitment, num_periods=8)
        self.assertIn('periods', result)
        self.assertLessEqual(len(result['periods']), 8)

    def test_commitment_streak_handles_partial_current_period(self):
        """Test that current period is marked correctly."""
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=60
        )
        result = calculate_commitment_streak(commitment)
        # Find the current period
        current_periods = [p for p in result['periods'] if p['is_current']]
        self.assertEqual(len(current_periods), 1)


class ProjectsListStillWorksTests(TestCase):
    """Test that /projects/ still works after dashboard changes."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='projlistuser',
            email='projlist@example.com',
            password='testpass123'
        )
        self.context = Context.objects.create(user=self.user, name='General')
        self.project = Projects.objects.create(
            user=self.user,
            name='Projects List Test Project',
            context=self.context
        )
        self.client.login(username='projlistuser', password='testpass123')

    def test_projects_list_still_accessible(self):
        """Test that /projects/ URL still works."""
        response = self.client.get(reverse('projects'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/projects_list.html')

    def test_projects_list_shows_projects(self):
        """Test that projects list shows projects."""
        response = self.client.get(reverse('projects'))
        self.assertIn('grouped_projects', response.context)
        self.assertTrue(response.context['has_projects'])
