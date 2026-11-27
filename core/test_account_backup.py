import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TransactionTestCase
from PIL import Image
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.models import (
    Commitment, CommitmentAdjustment, CommitmentPeriod, CommitmentRevision,
    Context, NotificationPreference, Projects, ScheduledReminder, SessionSubproject, Sessions, SubProjects, Tag,
)
from llm_insights.attachments import create_attachment
from llm_insights.models import LLMChat, LLMMessage


class AccountBackupTests(TransactionTestCase):
    def setUp(self):
        self.api = APIClient()
        self.source = User.objects.create_user("source", email="source@example.test")
        self.destination = User.objects.create_user("destination", email="destination@example.test")
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        self.enterContext(self.settings(MEDIA_ROOT=media.name))

    def download(self, *, files=False):
        self.api.force_authenticate(self.source)
        response = self.api.get(f"/api/v2/backup/?include_attachments={str(files).lower()}", HTTP_ACCEPT="application/zip")
        self.assertEqual(response.status_code, 200, getattr(response, "data", None))
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("no-store", response["Cache-Control"])
        # Django's test client closes a streaming response when consumed.
        return b"".join(response.streaming_content)

    def submit(self, stage, data, token=None, *, user=None):
        self.api.force_authenticate(user or self.destination)
        body = {"file": SimpleUploadedFile("backup.zip", data, content_type="application/zip")}
        if token is not None:
            body["preview_token"] = token
        return self.api.post(f"/api/v2/backup/{stage}/", body, format="multipart")

    def preview(self, data):
        response = self.submit("preview", data)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_round_trip_and_replay(self):
        at = datetime(2026, 10, 5, 8, tzinfo=UTC)
        context = Context.objects.create(user=self.source, name="Studio", description="Deep work")
        tag = Tag.objects.create(user=self.source, name="Build", color="#336699")
        Tag.objects.create(user=self.source, name="Unused", color="#558833")
        project = Projects.objects.create(user=self.source, name="A project", context=context)
        project.tags.add(tag)
        Projects.objects.create(user=self.source, name="Empty project", status="archived", context=context)
        subproject = SubProjects.objects.create(user=self.source, parent_project=project, name="Plan")
        session = Sessions.objects.create(user=self.source, project=project, start_time=at,
                                          end_time=at + timedelta(hours=1), note="**Finished** the plan")
        SessionSubproject.objects.create(session=session, subproject=subproject, allocation_bp=7500)
        Sessions.objects.create(user=self.source, project=project, start_time=at)
        commitment = Commitment.objects.create(user=self.source, project=project, target=30, start_date=at.date())
        revision = CommitmentRevision.objects.create(
            commitment=commitment, effective_from_instant=at, status=CommitmentRevision.STATUS_ACTIVE, aggregation_type="project",
            target_id=project.pk, target_name=project.name, commitment_type="time", cadence="weekly",
            target_value=30, start_date=at.date(), timezone="UTC",
        )
        CommitmentPeriod.objects.create(
            commitment=commitment, revision=revision, period_start=at, period_end=at + timedelta(days=7),
            session_count=1, balance_out=30, closed_at=at + timedelta(days=7),
        )
        CommitmentAdjustment.objects.create(
            commitment=commitment, seq=0, kind="manual", amount=15, effective_at=at, reason="Carryover",
        )
        profile = self.source.profile
        profile.timezone = "Africa/Johannesburg"
        profile.active_context = context
        profile.openai_api_key_enc = b"example-ciphertext"
        picture = io.BytesIO()
        Image.new("RGB", (4, 4), "green").save(picture, format="PNG")
        profile.image.save("backup-test.png", ContentFile(picture.getvalue()), save=False)
        profile.save()
        NotificationPreference.objects.create(user=self.source, weekly_review_enabled=True)
        reminder = ScheduledReminder.objects.create(
            user=self.source, project=project, message="Record the review", cadence="weekly", timezone="UTC",
            anchor_date=at.date(), anchor_time=at.time(), next_fire_at=at + timedelta(days=7),
        )
        reminder.subprojects.add(subproject)
        token = Token.objects.create(user=self.source).key
        chat = LLMChat.objects.create(
            user=self.source, title="Project discussion", model="example",
            filters={"include_projects": [str(project.pk)]},
        )
        message = LLMMessage.objects.create(chat=chat, role="user", content="What changed?", metadata={
            "model": "example", "sources": [{"title": "Retained title"}],
        })
        attachment = create_attachment(self.source, SimpleUploadedFile("draft.txt", b"An attached draft."))
        attachment.message = message
        attachment.save(update_fields=["message"])

        data = self.download(files=True)
        self.assertNotIn(token.encode(), data)
        with ZipFile(io.BytesIO(data)) as archive:
            manifest = archive.read("manifest.json")
        self.assertNotIn(b"example-ciphertext", manifest)
        self.assertNotIn(token.encode(), manifest)
        preview = self.preview(data)
        self.assertTrue(preview["can_restore"], preview)
        self.assertFalse(preview["same_account"])
        self.assertEqual(preview["counts"]["insight_attachments"]["add"], 1)
        self.assertFalse(Sessions.objects.filter(user=self.destination).exists())

        response = self.submit("restore", data, preview["preview_token"])
        self.assertEqual(response.status_code, 200, response.data)
        restored = Sessions.objects.get(user=self.destination)
        self.assertEqual((restored.uuid, restored.note), (session.uuid, session.note))
        self.assertEqual(restored.subproject_links.get().allocation_bp, 7500)
        self.assertEqual(Projects.objects.get(user=self.destination, name="Empty project").status, "archived")
        self.assertEqual(Tag.objects.get(user=self.destination, name="Unused").color, "#558833")
        self.assertEqual(restored.project.context.description, "Deep work")
        self.destination.profile.refresh_from_db()
        self.assertEqual(self.destination.profile.active_context, restored.project.context)
        self.assertEqual(self.destination.profile.timezone, profile.timezone)
        self.assertIsNone(self.destination.profile.openai_api_key_enc)
        with self.destination.profile.image.open("rb") as file:
            self.assertEqual(file.read(), picture.getvalue())
        self.assertTrue(NotificationPreference.objects.get(user=self.destination).weekly_review_enabled)
        copied_schedule = ScheduledReminder.objects.get(user=self.destination)
        self.assertEqual(copied_schedule.project, restored.project)
        self.assertEqual(copied_schedule.subprojects.get().name, subproject.name)
        self.assertIsNotNone(copied_schedule.next_fire_at)
        ledger = Commitment.objects.get(user=self.destination)
        self.assertEqual(ledger.period_rows.get().balance_out, 30)
        self.assertEqual(ledger.adjustments.get().amount, 15)
        self.assertEqual(ledger.revisions.get().target_id, restored.project.pk)
        copied_chat = LLMChat.objects.get(user=self.destination)
        self.assertEqual(copied_chat.filters["include_projects"], [str(restored.project.pk)])
        copied_message = copied_chat.messages.get()
        self.assertEqual(copied_message.metadata["model"], "example")
        with copied_message.attachments.get().file.open("rb") as file:
            self.assertEqual(file.read(), b"An attached draft.")

        repeated = self.submit("restore", data, preview["preview_token"])
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertEqual(repeated.data["restored"], 0)
        self.assertTrue(self.preview(data)["can_restore"])

    def test_conflict_blocks_restore_and_preview_cannot_be_reused_for_other_account(self):
        Projects.objects.create(user=self.source, name="Overlapping", description="Backup")
        Projects.objects.create(user=self.source, name="Would be added")
        data = self.download()
        preview = self.preview(data)
        other = self.submit("restore", data, preview["preview_token"], user=self.source)
        self.assertEqual(other.status_code, 409, other.data)
        Projects.objects.create(user=self.destination, name="Overlapping", description="Keep this")
        report = self.preview(data)
        self.assertFalse(report["can_restore"])
        self.assertEqual(report["counts"]["projects"]["conflict"], 1)
        response = self.submit("restore", data, preview["preview_token"])
        self.assertEqual(response.status_code, 409, response.data)
        self.assertFalse(Projects.objects.filter(user=self.destination, name="Would be added").exists())

    def test_invalid_manifest_and_zip_members_are_rejected(self):
        data = self.download()
        with ZipFile(io.BytesIO(data)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        manifest["source"]["account_id"] = "invalid UUID"
        for name in ["manifest.json", "../manifest.json"]:
            buffer = io.BytesIO()
            with ZipFile(buffer, "w") as archive:
                archive.writestr(name, json.dumps(manifest))
            response = self.submit("preview", buffer.getvalue())
            self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Projects.objects.filter(user=self.destination, name="Would be added").exists())

    def test_recovery_command_previews_creates_account_and_replays(self):
        Projects.objects.create(user=self.source, name="Archived work", status="archived")
        data = self.download()
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "backup.zip"
            archive.write_bytes(data)
            args = ("recovering", str(archive), "--create-user", "recovery@example.test")
            preview = io.StringIO()
            call_command("restore_account_backup", *args, stdout=preview)
            self.assertIn("Preview only", preview.getvalue())
            self.assertFalse(User.objects.filter(username="recovering").exists())

            call_command("restore_account_backup", *args, "--apply", stdout=io.StringIO())
            recovered = User.objects.get(username="recovering")
            self.assertFalse(recovered.has_usable_password())
            self.assertEqual(Projects.objects.get(user=recovered, name="Archived work").status, "archived")

            repeated = io.StringIO()
            call_command("restore_account_backup", *args, "--apply", stdout=repeated)
            self.assertIn("Restored 0 record(s)", repeated.getvalue())
