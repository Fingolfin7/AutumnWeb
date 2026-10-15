from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import Projects, SubProjects, Sessions, Commitment, Tag
from core.services import SessionMutationService
from django.contrib.auth.models import User
from datetime import datetime, timedelta
from django.core.management import call_command
from django.conf import settings
import io
import json
import os
import shutil
import tempfile
import time
from unittest.mock import patch
from freezegun import freeze_time
from core.models import Context
from rest_framework.authtoken.models import Token
from core.utils import (
    get_period_bounds,
    calculate_daily_activity_streak,
)
from core.commitments import (
    calculate_commitment_streak,
    get_commitment_progress,
    get_commitment_sessions_queryset,
    reconcile_commitment,
)
from core.templatetags.markdown_render import markdown
from core.totals import derived_project_totals, derived_subproject_totals


def derived_project_total(user, project):
    return derived_project_totals(user, [project.pk])[project.pk]


def derived_subproject_total(user, subproject):
    return derived_subproject_totals(user, [subproject.pk])[subproject.pk]


class MarkdownRenderTests(TestCase):
    def test_pipe_table_renders_as_table(self):
        rendered = markdown(
            "| Lift | Recent log | Verdict |\n"
            "| --- | --- | --- |\n"
            "| Bench press | 55kg x 6 | Decent novice |"
        )

        self.assertIn("<table>", rendered)
        self.assertIn("<th>Lift</th>", rendered)
        self.assertIn("<td>Bench press</td>", rendered)
        self.assertNotIn("<p>| Lift |", rendered)

    def test_pipe_table_supports_column_alignment(self):
        rendered = markdown(
            "| Left | Center | Right |\n"
            "| :--- | :---: | ---: |\n"
            "| A | B | C |"
        )

        self.assertIn('style="text-align: left;"', rendered)
        self.assertIn('style="text-align: center;"', rendered)
        self.assertIn('style="text-align: right;"', rendered)

    def test_pipe_table_does_not_insert_breaks_between_table_elements(self):
        rendered = markdown("| A | B |\n| --- | --- |\n| 1 | 2 |")

        self.assertNotIn("<br", rendered)
        self.assertNotIn("<p><table>", rendered)

    def test_single_tilde_renders_as_strikethrough(self):
        rendered = markdown("testing ~single tilde~ support")

        self.assertIn("<del>single tilde</del>", rendered)
        self.assertNotIn("<sub>single tilde</sub>", rendered)

    def test_double_tilde_still_renders_as_strikethrough(self):
        rendered = markdown("testing ~~double tilde~~ support")

        self.assertIn("<del>double tilde</del>", rendered)

    def test_inline_subscript_style_tilde_is_left_literal(self):
        rendered = markdown("H~2~O")

        self.assertIn("H~2~O", rendered)
        self.assertNotIn("<sub>2</sub>", rendered)
        self.assertNotIn("<del>2</del>", rendered)


class PwaTests(TestCase):
    def test_manifest_contains_installability_basics(self):
        response = self.client.get(reverse("pwa_manifest"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")

        payload = response.json()
        self.assertEqual(payload["name"], "Autumn")
        self.assertEqual(payload["start_url"], "/")
        self.assertEqual(payload["scope"], "/")
        self.assertEqual(payload["display"], "standalone")

        icon_sizes = {icon["sizes"] for icon in payload["icons"]}
        self.assertIn("192x192", icon_sizes)
        self.assertIn("512x512", icon_sizes)
        self.assertTrue(
            any(icon.get("purpose") == "maskable" for icon in payload["icons"])
        )

    def test_service_worker_is_root_scoped(self):
        response = self.client.get(reverse("service_worker"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertIn("text/javascript", response["Content-Type"])

        content = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("self.addEventListener(\"fetch\"", content)
        self.assertIn("/static/core/pwa/offline.html", content)

    def test_app_document_and_login_page_advertise_the_manifest(self):
        # The React shell (core/templates/core/spa.html) links the manifest and
        # frontend/src/main.tsx registers /service-worker.js; the server-rendered
        # login page still goes through base.html and pwa.js.
        from unittest import mock

        from core import spa

        User.objects.create_user(username="pwauser", password="password")
        self.client.login(username="pwauser", password="password")

        entry = {"src/main.tsx": {"file": "assets/main-abc123.js", "isEntry": True}}
        with mock.patch.object(spa, "manifest", return_value=entry):
            app_response = self.client.get(reverse("home"))
        self.assertEqual(app_response.status_code, 200)
        self.assertContains(app_response, 'rel="manifest"')
        self.assertContains(app_response, reverse("pwa_manifest"))
        self.assertEqual(self.client.get(reverse("service_worker")).status_code, 200)

        self.client.logout()
        login_response = self.client.get(reverse("login"))
        self.assertContains(login_response, 'rel="manifest"')
        self.assertContains(login_response, "core/js/pwa.js")


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
        self.session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            is_active=False,
            subprojects=[self.subproject1],
        )

    def test_repeated_save_of_completed_session_is_idempotent(self):
        self.session.note = "Only the note changed"
        self.session.save()

        self.assertAlmostEqual(
            derived_project_total(self.user, self.project), 60.0, places=2
        )
        self.assertAlmostEqual(
            derived_subproject_total(self.user, self.subproject1), 60.0, places=2
        )



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

    def test_ui_imports_with_same_filename_keep_uploads_isolated(self):
        other_client = Client()
        self.assertTrue(other_client.login(username="importui", password="password"))
        first_ctx = Context.objects.create(user=self.user, name="FirstDest")
        second_ctx = Context.objects.create(user=self.user, name="SecondDest")

        def payload(project_name):
            return {
                project_name: {
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

        first_response = self.client.post(
            reverse("import"),
            data={
                "file": self._make_upload_file(payload("First Upload")),
                "merge": "on",
                "tolerance": "0.5",
                "import_context": str(first_ctx.id),
            },
        )
        second_response = other_client.post(
            reverse("import"),
            data={
                "file": self._make_upload_file(payload("Second Upload")),
                "merge": "on",
                "tolerance": "0.5",
                "import_context": str(second_ctx.id),
            },
        )
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)

        first_stream = self._consume_event_stream(
            self.client.get(reverse("import_stream"))
        )
        second_stream = self._consume_event_stream(
            other_client.get(reverse("import_stream"))
        )
        self.assertIn("Import completed successfully", first_stream)
        self.assertIn("Import completed successfully", second_stream)
        self.assertEqual(
            Projects.objects.get(user=self.user, name="First Upload").context_id,
            first_ctx.id,
        )
        self.assertEqual(
            Projects.objects.get(user=self.user, name="Second Upload").context_id,
            second_ctx.id,
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


class PendingImportCleanupTests(TestCase):
    """Uploads are staged on disk between the import POST and the stream GET.

    Only the stream used to delete them, so any session that never streamed
    left a file behind for good.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="tempclean", password="password")
        self.client.login(username="tempclean", password="password")

        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        media = override_settings(MEDIA_ROOT=media_root)
        media.enable()
        self.addCleanup(media.disable)

        self.media_root = media_root
        self.temp_dir = os.path.join(media_root, "temp")

    def _post_upload(self, contents: bytes, name: str = "export.json") -> str:
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(
            reverse("import"),
            data={
                "file": SimpleUploadedFile(
                    name, contents, content_type="application/json"
                ),
                "merge": "on",
                "tolerance": "0.5",
            },
        )
        self.assertEqual(response.status_code, 200)
        return self.client.session["file_path"]

    def _upload_project(self, project_name: str) -> str:
        payload = {
            project_name: {
                "Start Date": "05-01-2024",
                "Last Updated": "05-02-2024",
                "Total Time": 0.0,
                "Description": "",
                "Status": "active",
                "Context": "FileContext",
                "Tags": [],
                "Sub Projects": {},
                "Session History": [],
            }
        }
        return self._post_upload(json.dumps(payload).encode("utf-8"))

    def _staged_files(self):
        if not os.path.isdir(self.temp_dir):
            return []
        return sorted(os.listdir(self.temp_dir))

    def _write_staged(self, name: str, age_hours: float) -> str:
        os.makedirs(self.temp_dir, exist_ok=True)
        path = os.path.join(self.temp_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("{}")
        stamp = time.time() - age_hours * 3600
        os.utime(path, (stamp, stamp))
        return path

    def test_revisiting_the_import_page_reclaims_an_abandoned_upload(self):
        path = self._upload_project("Abandoned Project")
        self.assertTrue(os.path.exists(path))

        # The user never opened the stream; they just came back to the form.
        self.assertEqual(self.client.get(reverse("import")).status_code, 200)

        self.assertFalse(os.path.exists(path))
        self.assertEqual(self._staged_files(), [])

    def test_a_second_upload_discards_the_first(self):
        first = self._upload_project("First Upload")
        second = self._upload_project("Second Upload")

        # Unique paths, so the second no longer overwrites the first.
        self.assertNotEqual(first, second)
        self.assertFalse(os.path.exists(first))
        self.assertTrue(os.path.exists(second))
        self.assertEqual(self._staged_files(), [os.path.basename(second)])

    def test_stream_removes_the_upload_even_when_the_file_is_not_json(self):
        path = self._post_upload(b"this is not json")

        response = self.client.get(reverse("import_stream"))
        body = "".join(
            chunk.decode("utf-8", errors="ignore") if isinstance(chunk, bytes) else chunk
            for chunk in response.streaming_content
        )

        self.assertIn("Invalid JSON file", body)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self._staged_files(), [])

    def test_successful_stream_still_removes_the_upload(self):
        path = self._upload_project("Streamed Project")

        response = self.client.get(reverse("import_stream"))
        for _ in response.streaming_content:
            pass

        self.assertTrue(Projects.objects.filter(user=self.user, name="Streamed Project").exists())
        self.assertFalse(os.path.exists(path))

    def test_sweep_removes_only_uploads_past_the_age_threshold(self):
        from core.temp_uploads import sweep

        stale = self._write_staged("import_stale.json", age_hours=48)
        fresh = self._write_staged("import_fresh.json", age_hours=1)

        removed, freed = sweep(max_age_seconds=24 * 3600, dry_run=True)
        self.assertEqual(removed, [stale])
        self.assertEqual(freed, 2)
        self.assertTrue(os.path.exists(stale), "dry run must not delete")

        removed, freed = sweep(max_age_seconds=24 * 3600)
        self.assertEqual(removed, [stale])
        self.assertEqual(freed, 2)
        self.assertFalse(os.path.exists(stale))
        self.assertTrue(os.path.exists(fresh))

    def test_sweep_is_a_no_op_when_nothing_has_been_staged_yet(self):
        from core.temp_uploads import sweep

        self.assertEqual(sweep(max_age_seconds=0), ([], 0))

    def test_discard_upload_refuses_paths_outside_the_staging_directory(self):
        from core.temp_uploads import discard_upload

        outside = os.path.join(self.media_root, "keep_me.json")
        with open(outside, "w", encoding="utf-8") as f:
            f.write("{}")

        self.assertFalse(discard_upload(outside))
        self.assertTrue(os.path.exists(outside))
        self.assertFalse(discard_upload(None))
        self.assertFalse(discard_upload(os.path.join(self.temp_dir, "gone.json")))

    def test_clear_temp_uploads_command_sweeps_stale_uploads(self):
        stale = self._write_staged("import_stale.json", age_hours=48)
        fresh = self._write_staged("import_fresh.json", age_hours=1)

        out = io.StringIO()
        call_command("clear_temp_uploads", "--older-than-hours=24", stdout=out)
        output = out.getvalue()

        self.assertIn("Removed", output)
        self.assertIn("import_stale.json", output)
        self.assertNotIn("import_fresh.json", output)
        self.assertFalse(os.path.exists(stale))
        self.assertTrue(os.path.exists(fresh))


class ProjectsGroupedApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")
        # DRF token auth for API endpoints
        self.token = Token.objects.create(user=self.user)



class TrackApiRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="trackuser", password="password")
        self.client.login(username="trackuser", password="password")
        self.token = Token.objects.create(user=self.user)

        self.project = Projects.objects.create(user=self.user, name="Track Project")



class CreateSubprojectApiCompatTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="subprojapiuser", password="password"
        )
        self.client.login(username="subprojapiuser", password="password")
        self.token = Token.objects.create(user=self.user)
        self.project = Projects.objects.create(user=self.user, name="API Parent")




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


@freeze_time("2026-09-09 12:00:00+00:00")
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
        now = timezone.localtime(timezone.now())
        period_start, _ = get_period_bounds('weekly', now)
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='weekly',
            target=100,
            start_date=period_start.date(),
        )

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
        now = timezone.localtime(timezone.now())
        period_start, _ = get_period_bounds('weekly', now)
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='sessions',
            period='weekly',
            target=5,
            start_date=period_start.date(),
        )

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
        now = timezone.localtime(timezone.now())
        period_start, _ = get_period_bounds('weekly', now)
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='sessions',
            period='weekly',
            target=2,
            start_date=period_start.date(),
        )

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


# =============================================================================
# Dashboard Feature Tests
# =============================================================================


class ActiveTimersFragmentTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="fragmentuser",
            email="fragment@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            username="otherfragmentuser",
            email="other-fragment@example.com",
            password="testpass123",
        )
        self.context = Context.objects.create(user=self.user, name="General")
        self.project = Projects.objects.create(
            user=self.user,
            name="Fragment Project",
            context=self.context,
        )
        self.other_project = Projects.objects.create(
            user=self.other_user,
            name="Other Fragment Project",
        )
        self.client.login(username="fragmentuser", password="testpass123")

    def create_active_session(self, project=None, start_time=None):
        return Sessions.objects.create(
            user=self.user,
            project=project or self.project,
            start_time=start_time or timezone.now() - timedelta(minutes=10),
            is_active=True,
        )

    def test_fragment_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse("active_timers_fragment"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_fragment_rejects_unknown_surface(self):
        response = self.client.get(
            reverse("active_timers_fragment"),
            {"surface": "not-real"},
        )

        self.assertEqual(response.status_code, 400)

    @patch("core.services.timer_suggestions.build_timer_suggestions")
    def test_timers_fragment_renders_active_timer_only(self, build_timer_suggestions):
        active = self.create_active_session()
        Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            is_active=False,
            note="completed-session-marker",
        )
        Sessions.objects.create(
            user=self.other_user,
            project=self.other_project,
            start_time=timezone.now() - timedelta(minutes=5),
            is_active=True,
        )

        response = self.client.get(
            reverse("active_timers_fragment"),
            {"surface": "timers"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertContains(response, 'data-timer-surface="timers"')
        self.assertContains(response, f'id="timer-{active.id}"')
        self.assertContains(response, "Fragment Project")
        self.assertNotContains(response, "completed-session-marker")
        self.assertNotContains(response, "Other Fragment Project")
        build_timer_suggestions.assert_not_called()

    def test_dashboard_fragment_exists_when_empty_and_appears_with_timer(self):
        # The Focus Desk deck no longer hides itself when nothing is running:
        # the "start something" card sits beside these cards and is always on
        # screen, so an idle fragment is simply an empty container.
        empty_response = self.client.get(
            reverse("active_timers_fragment"),
            {"surface": "dashboard"},
        )
        self.assertContains(empty_response, 'id="active-timers"')
        self.assertNotContains(empty_response, "data-timer-id")

        self.create_active_session()
        active_response = self.client.get(
            reverse("active_timers_fragment"),
            {"surface": "dashboard"},
        )

        self.assertContains(active_response, 'data-timer-surface="dashboard"')
        self.assertContains(active_response, "Fragment Project")
        self.assertContains(active_response, "data-timer-id")

    def test_dashboard_fragment_limits_to_five_timers(self):
        now = timezone.now()
        for index in range(6):
            project = Projects.objects.create(
                user=self.user,
                name=f"Timer Project {index}",
                context=self.context,
            )
            self.create_active_session(
                project=project,
                start_time=now - timedelta(minutes=index),
            )

        response = self.client.get(
            reverse("active_timers_fragment"),
            {"surface": "dashboard"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Timer Project 0")
        self.assertContains(response, "Timer Project 4")
        self.assertNotContains(response, "Timer Project 5")


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
        now = timezone.localtime(timezone.now())
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
        now = timezone.localtime(timezone.now())
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
        now = timezone.localtime(timezone.now())
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
        now = timezone.localtime(timezone.now())

        # Create commitment with created_at in the past (before the periods we're testing)
        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='sessions',
            period='daily',
            target=1
        )
        # Manually set start_date to 5 days ago so periods aren't skipped
        Commitment.objects.filter(pk=commitment.pk).update(
            start_date=(now - timedelta(days=2)).date()
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

    def test_streak_preserved_by_bank(self):
        """Test that banked time preserves streak when a period is missed."""
        now = timezone.localtime(timezone.now())

        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='daily',
            target=60,  # 60 minutes per day
            banking_enabled=True,
            max_balance=600,
            min_balance=-600,
        )
        # Set start_date to day -3 so no empty periods before sessions
        day3 = now - timedelta(days=3)
        ps_day3, _ = get_period_bounds('daily', day3)
        Commitment.objects.filter(pk=commitment.pk).update(
            start_date=ps_day3.date()
        )
        commitment.refresh_from_db()

        # Day -3: log 120 min (surplus of 60 → banked)
        ps, pe = get_period_bounds('daily', day3)
        session_time = ps + timedelta(hours=6)
        Sessions.objects.create(
            user=self.user, project=self.project,
            start_time=session_time, end_time=session_time + timedelta(minutes=120),
            is_active=False
        )

        # Day -2: log 30 min (deficit of 30 → covered by bank)
        day2 = now - timedelta(days=2)
        ps2, pe2 = get_period_bounds('daily', day2)
        session_time2 = ps2 + timedelta(hours=6)
        Sessions.objects.create(
            user=self.user, project=self.project,
            start_time=session_time2, end_time=session_time2 + timedelta(minutes=30),
            is_active=False
        )

        # Day -1: log 60 min (met exactly)
        day1 = now - timedelta(days=1)
        ps1, pe1 = get_period_bounds('daily', day1)
        session_time1 = ps1 + timedelta(hours=6)
        Sessions.objects.create(
            user=self.user, project=self.project,
            start_time=session_time1, end_time=session_time1 + timedelta(minutes=60),
            is_active=False
        )

        result = calculate_commitment_streak(commitment)
        # Streak should be 3 (day -3 met, day -2 saved by bank, day -1 met)
        self.assertEqual(result['current_streak'], 3)

        # Day -2 should be marked as saved_by_bank
        completed = [p for p in result['periods'] if not p['is_current']]
        # Find the day -2 period (second from oldest of the 3 completed days)
        day2_period = None
        for p in completed:
            if p['period_start'] <= day2 < p['period_end']:
                day2_period = p
                break
        self.assertIsNotNone(day2_period)
        self.assertTrue(day2_period['saved_by_bank'])
        self.assertTrue(day2_period['met'])

    def test_streak_breaks_when_bank_insufficient(self):
        """Test that streak breaks when bank can't cover the deficit."""
        now = timezone.localtime(timezone.now())

        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='time',
            period='daily',
            target=60,
            banking_enabled=True,
            max_balance=600,
            min_balance=-600,
        )
        day3 = now - timedelta(days=3)
        ps_day3, _ = get_period_bounds('daily', day3)
        Commitment.objects.filter(pk=commitment.pk).update(
            start_date=ps_day3.date()
        )
        commitment.refresh_from_db()

        # Day -3: log 70 min (surplus of 10)
        ps, pe = get_period_bounds('daily', day3)
        st = ps + timedelta(hours=6)
        Sessions.objects.create(
            user=self.user, project=self.project,
            start_time=st, end_time=st + timedelta(minutes=70),
            is_active=False
        )

        # Day -2: log 0 min (deficit of 60, bank only has 10 → not enough)
        # No session created

        # Day -1: log 60 min (met)
        day1 = now - timedelta(days=1)
        ps1, pe1 = get_period_bounds('daily', day1)
        st1 = ps1 + timedelta(hours=6)
        Sessions.objects.create(
            user=self.user, project=self.project,
            start_time=st1, end_time=st1 + timedelta(minutes=60),
            is_active=False
        )

        result = calculate_commitment_streak(commitment)
        # Streak should be 1 (only day -1), because day -2 broke it
        self.assertEqual(result['current_streak'], 1)

    def test_streak_bank_simulation_forward(self):
        """Test that banking balance is simulated forward correctly across periods."""
        now = timezone.localtime(timezone.now())

        commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type='sessions',
            period='daily',
            target=2,  # 2 sessions per day
            banking_enabled=True,
            max_balance=10,
            min_balance=-10,
        )
        day4 = now - timedelta(days=4)
        ps_day4, _ = get_period_bounds('daily', day4)
        Commitment.objects.filter(pk=commitment.pk).update(
            start_date=ps_day4.date()
        )
        commitment.refresh_from_db()

        # Day -4: 4 sessions (surplus 2 → balance = 2)
        ps4, _ = get_period_bounds('daily', day4)
        for j in range(4):
            st = ps4 + timedelta(hours=j + 1)
            Sessions.objects.create(
                user=self.user, project=self.project,
                start_time=st, end_time=st + timedelta(minutes=30),
                is_active=False
            )

        # Day -3: 1 session (deficit 1, balance 2 → saved, balance = 1)
        day3 = now - timedelta(days=3)
        ps3, _ = get_period_bounds('daily', day3)
        st3 = ps3 + timedelta(hours=1)
        Sessions.objects.create(
            user=self.user, project=self.project,
            start_time=st3, end_time=st3 + timedelta(minutes=30),
            is_active=False
        )

        # Day -2: 1 session (deficit 1, balance 1 → saved, balance = 0)
        day2 = now - timedelta(days=2)
        ps2, _ = get_period_bounds('daily', day2)
        st2 = ps2 + timedelta(hours=1)
        Sessions.objects.create(
            user=self.user, project=self.project,
            start_time=st2, end_time=st2 + timedelta(minutes=30),
            is_active=False
        )

        # Day -1: 1 session (deficit 1, balance 0 → NOT saved, streak breaks)
        day1 = now - timedelta(days=1)
        ps1, _ = get_period_bounds('daily', day1)
        st1 = ps1 + timedelta(hours=1)
        Sessions.objects.create(
            user=self.user, project=self.project,
            start_time=st1, end_time=st1 + timedelta(minutes=30),
            is_active=False
        )

        result = calculate_commitment_streak(commitment)
        # Day -1 breaks it because bank is depleted, so streak = 0
        self.assertEqual(result['current_streak'], 0)

        # Verify saved_by_bank flags
        completed = [p for p in result['periods'] if not p['is_current']]
        # Day -3 and Day -2 should be saved_by_bank
        day3_period = next(p for p in completed if p['period_start'] <= day3 < p['period_end'])
        day2_period = next(p for p in completed if p['period_start'] <= day2 < p['period_end'])
        day1_period = next(p for p in completed if p['period_start'] <= day1 < p['period_end'])
        self.assertTrue(day3_period['saved_by_bank'])
        self.assertTrue(day2_period['saved_by_bank'])
        self.assertFalse(day1_period['met'])


class CommitmentComposableRulesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='commitrulesuser',
            email='commitrules@example.com',
            password='testpass123'
        )
        self.context_work = Context.objects.create(user=self.user, name='Work')
        self.context_personal = Context.objects.create(user=self.user, name='Personal')
        self.tag_focus = Tag.objects.create(user=self.user, name='Focus')
        self.tag_admin = Tag.objects.create(user=self.user, name='Admin')

        self.project_alpha = Projects.objects.create(
            user=self.user,
            name='Alpha',
            context=self.context_work,
        )
        self.project_alpha.tags.add(self.tag_focus)

        self.project_beta = Projects.objects.create(
            user=self.user,
            name='Beta',
            context=self.context_work,
        )
        self.project_beta.tags.add(self.tag_admin)

        self.project_gamma = Projects.objects.create(
            user=self.user,
            name='Gamma',
            context=self.context_personal,
        )
        self.project_gamma.tags.add(self.tag_focus)

        self.alpha_sp1 = SubProjects.objects.create(
            user=self.user, name='SP1', parent_project=self.project_alpha
        )
        self.alpha_sp2 = SubProjects.objects.create(
            user=self.user, name='SP2', parent_project=self.project_alpha
        )

        now = timezone.localtime(timezone.now())
        self.period_start, self.period_end = get_period_bounds('daily', now)
        midpoint = self.period_start + timedelta(hours=10)

        self.alpha_sp1_session = Sessions.objects.create(
            user=self.user,
            project=self.project_alpha,
            start_time=midpoint,
            end_time=midpoint + timedelta(minutes=60),
            is_active=False,
        )
        self.alpha_sp1_session.subprojects.add(self.alpha_sp1)

        self.alpha_sp2_session = Sessions.objects.create(
            user=self.user,
            project=self.project_alpha,
            start_time=midpoint + timedelta(hours=2),
            end_time=midpoint + timedelta(hours=2, minutes=60),
            is_active=False,
        )
        self.alpha_sp2_session.subprojects.add(self.alpha_sp2)

        self.beta_session = Sessions.objects.create(
            user=self.user,
            project=self.project_beta,
            start_time=midpoint + timedelta(hours=3),
            end_time=midpoint + timedelta(hours=4),
            is_active=False,
        )

        self.gamma_session = Sessions.objects.create(
            user=self.user,
            project=self.project_gamma,
            start_time=midpoint + timedelta(hours=4),
            end_time=midpoint + timedelta(hours=5),
            is_active=False,
        )

    def test_project_scope_can_exclude_specific_subproject(self):
        commitment = Commitment.objects.create(
            user=self.user,
            aggregation_type='project',
            project=self.project_alpha,
            commitment_type='sessions',
            period='daily',
            target=1,
        )
        commitment.exclude_subprojects.add(self.alpha_sp2)

        sessions = get_commitment_sessions_queryset(
            commitment, self.period_start, self.period_end
        )
        self.assertEqual(list(sessions), [self.alpha_sp1_session])

    def test_project_scope_can_include_only_selected_subproject(self):
        commitment = Commitment.objects.create(
            user=self.user,
            aggregation_type='project',
            project=self.project_alpha,
            commitment_type='sessions',
            period='daily',
            target=1,
        )
        commitment.include_subprojects.add(self.alpha_sp2)

        sessions = get_commitment_sessions_queryset(
            commitment, self.period_start, self.period_end
        )
        self.assertEqual(list(sessions), [self.alpha_sp2_session])

    def test_context_scope_supports_composed_include_exclude_rules(self):
        commitment = Commitment.objects.create(
            user=self.user,
            aggregation_type='context',
            context=self.context_work,
            commitment_type='sessions',
            period='daily',
            target=1,
        )
        commitment.include_tags.add(self.tag_focus)
        commitment.exclude_subprojects.add(self.alpha_sp2)

        sessions = get_commitment_sessions_queryset(
            commitment, self.period_start, self.period_end
        )
        self.assertEqual(list(sessions), [self.alpha_sp1_session])


class DstTransitionSessionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dstuser", password="password")
        self.client.login(username="dstuser", password="password")
        self.project = Projects.objects.create(user=self.user, name="DST Project")

    def test_duration_uses_absolute_elapsed_time_across_spring_transition(self):
        # Europe/Prague spring-forward on March 29, 2026:
        # 01:30 CET -> 03:30 CEST is 60 minutes of real elapsed time.
        start = timezone.make_aware(datetime(2026, 3, 29, 1, 30, 0))
        end = timezone.make_aware(datetime(2026, 3, 29, 3, 30, 0))
        session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=start,
            end_time=end,
            is_active=False,
        )

        self.assertEqual(session.duration, 60.0)
        self.assertTrue(session.crosses_dst_transition)

    def test_duration_uses_absolute_elapsed_time_across_fall_transition(self):
        # Europe/Prague fall-back on October 25, 2026:
        # 01:30 CEST -> 03:30 CET is 180 minutes of real elapsed time.
        start = timezone.make_aware(datetime(2026, 10, 25, 1, 30, 0))
        end = timezone.make_aware(datetime(2026, 10, 25, 3, 30, 0))
        session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=start,
            end_time=end,
            is_active=False,
        )

        self.assertEqual(session.duration, 180.0)
        self.assertTrue(session.crosses_dst_transition)



class McpApiContractTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mcpuser", password="password")
        self.client.login(username="mcpuser", password="password")
        self.project = Projects.objects.create(user=self.user, name="MCP Project")






