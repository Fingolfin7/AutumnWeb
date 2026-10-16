"""Importing through the staged-upload flow the React Import page uses.

POST /api/v2/import/uploads/ stages the file and returns an id;
GET /api/v2/import/uploads/<id>/stream/ imports it and removes it. Ported from
the old import page tests (core.tests ImportIntoContextUITests and
PendingImportCleanupTests).
"""

import json
import os
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import Context, Projects


def project_document(name, context="FileContext"):
    return {
        name: {
            "Start Date": "03-01-2024",
            "Last Updated": "03-02-2024",
            "Total Time": 0.0,
            "Description": "",
            "Status": "active",
            "Context": context,
            "Tags": [],
            "Sub Projects": {},
            "Session History": [],
        }
    }


class ImportUploadTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="importui", password="password")
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        media = override_settings(MEDIA_ROOT=media_root)
        media.enable()
        self.addCleanup(media.disable)
        self.temp_dir = os.path.join(media_root, "temp")
        self.client = self._client()

    def _client(self):
        client = APIClient()
        client.force_authenticate(self.user)
        return client

    def _upload(self, contents, *, client=None, name="export.json", **fields):
        if not isinstance(contents, bytes):
            contents = json.dumps(contents).encode("utf-8")
        return (client or self.client).post(
            "/api/v2/import/uploads/",
            {
                "file": SimpleUploadedFile(name, contents, content_type="application/json"),
                "merge": "true",
                "tolerance": "0.5",
                **fields,
            },
            format="multipart",
        )

    def _stream(self, upload_id, client=None):
        response = (client or self.client).get(f"/api/v2/import/uploads/{upload_id}/stream/")
        self.assertEqual(response.status_code, 200)
        return "".join(
            chunk.decode("utf-8", errors="ignore") if isinstance(chunk, bytes) else chunk
            for chunk in response.streaming_content
        )

    def _staged_files(self):
        return sorted(os.listdir(self.temp_dir)) if os.path.isdir(self.temp_dir) else []


class ImportIntoContextTests(ImportUploadTestCase):
    def test_import_under_an_existing_context(self):
        destination = Context.objects.create(user=self.user, name="DestCtx")
        response = self._upload(project_document("UI Project"), import_context=destination.id)
        self.assertEqual(response.status_code, 201, response.content)

        self.assertIn("Import completed successfully", self._stream(response.json()["upload_id"]))

        project = Projects.objects.get(user=self.user, name="UI Project")
        self.assertEqual(project.context_id, destination.id)
        self.assertFalse(Context.objects.filter(user=self.user, name="FileContext").exists())


    def test_naming_a_new_context_and_picking_one_is_refused_but_the_new_name_alone_works(self):
        dropdown = Context.objects.create(user=self.user, name="DropdownCtx")
        payload = project_document("UI Project 2")

        both = self._upload(payload, import_context=dropdown.id, import_context_new="NewCtxWins")
        self.assertEqual(both.status_code, 400)
        self.assertIn("import_context", both.json()["error"]["details"])
        self.assertEqual(self._staged_files(), [])

        only_new = self._upload(payload, import_context_new="NewCtxWins")
        self.assertEqual(only_new.status_code, 201, only_new.content)
        self.assertIn("Import completed successfully", self._stream(only_new.json()["upload_id"]))
        new_context = Context.objects.get(user=self.user, name="NewCtxWins")
        self.assertEqual(
            Projects.objects.get(user=self.user, name="UI Project 2").context_id, new_context.id
        )

    def test_another_users_context_is_refused(self):
        other = User.objects.create_user(username="other", email="o@example.com", password="pw")
        theirs = Context.objects.create(user=other, name="Theirs")
        response = self._upload(project_document("Sneaky"), import_context=theirs.id)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Projects.objects.filter(name="Sneaky").exists())


class PendingUploadCleanupTests(ImportUploadTestCase):
    """The staged file never outlives its stream, whatever the stream does."""

    def test_a_successful_stream_removes_the_upload(self):
        upload_id = self._upload(project_document("Streamed Project")).json()["upload_id"]
        self.assertEqual(len(self._staged_files()), 1)

        self._stream(upload_id)

        self.assertTrue(Projects.objects.filter(user=self.user, name="Streamed Project").exists())
        self.assertEqual(self._staged_files(), [])

    def test_a_file_that_is_not_json_is_reported_and_removed(self):
        upload_id = self._upload(b"this is not json").json()["upload_id"]
        self.assertEqual(len(self._staged_files()), 1)

        body = self._stream(upload_id)

        self.assertIn("Invalid JSON file", body)
        self.assertEqual(self._staged_files(), [])

    def test_an_upload_can_only_be_streamed_once(self):
        upload_id = self._upload(project_document("Once")).json()["upload_id"]
        self._stream(upload_id)
        self.assertEqual(
            self.client.get(f"/api/v2/import/uploads/{upload_id}/stream/").status_code, 404
        )
