import copy
import json
import tempfile
from datetime import datetime, timezone as datetime_timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.core.management import call_command
from rest_framework.test import APIClient

from core.export2 import build_format2_export
from core.models import (
    Context,
    Projects,
    Sessions,
    SessionSubproject,
    SubProjects,
    Tag,
)
from core.services import SessionMutationService
from core.totals import derived_project_totals, derived_subproject_totals
from core.utils import json_decompress


class Format2ExportImportTests(TestCase):
    def setUp(self):
        self.source = User.objects.create_user(
            username="format2-source", email="format2-source@example.com"
        )
        context = Context.objects.create(user=self.source, name="Focused")
        tag_a = Tag.objects.create(user=self.source, name="alpha")
        tag_b = Tag.objects.create(user=self.source, name="beta")
        self.project = Projects.objects.create(
            user=self.source,
            name="Client Work",
            status="paused",
            description="Portable project",
            context=context,
            start_date=self.at(2024, 1, 2, 8),
        )
        self.project.tags.set([tag_b, tag_a])
        self.planning = SubProjects.objects.create(
            user=self.source,
            parent_project=self.project,
            name="Planning",
            description="Plan it",
            start_date=self.project.start_date,
        )
        self.review = SubProjects.objects.create(
            user=self.source,
            parent_project=self.project,
            name="Review",
            description="Review it",
            start_date=self.project.start_date,
        )
        self.legacy = SessionMutationService.create_session(
            user=self.source,
            project=self.project,
            subprojects=[self.planning, self.review],
            start_time=self.at(2024, 1, 2, 9),
            end_time=self.at(2024, 1, 2, 10),
            is_active=False,
            note="Legacy multi-link",
        )
        self.partitioned = Sessions.objects.create(
            user=self.source,
            project=self.project,
            allocation_mode="partitioned",
            start_time=self.at(2024, 1, 2, 11),
            end_time=self.at(2024, 1, 2, 12),
            is_active=False,
            note=None,
        )
        SessionSubproject.objects.create(
            session=self.partitioned,
            subproject=self.planning,
            allocation_bp=3000,
        )
        SessionSubproject.objects.create(
            session=self.partitioned,
            subproject=self.review,
            allocation_bp=7000,
        )
        self.document = self.export_document()
        self.target = User.objects.create_user(
            username="format2-target", email="format2-target@example.com"
        )
        self.client = APIClient()
        self.client.force_login(self.target)

    @staticmethod
    def at(year, month, day, hour):
        return datetime(year, month, day, hour, tzinfo=datetime_timezone.utc)

    def export_document(self):
        return build_format2_export(
            Sessions.objects.filter(user=self.source, end_time__isnull=False)
        )

    def post_import(self, document=None, *, force=False):
        return self.client.post(
            reverse("api_v2:import"),
            {"data": self.document if document is None else document, "force": force},
            format="json",
        )

    def owned_counts(self):
        return (
            Projects.objects.filter(user=self.target).count(),
            SubProjects.objects.filter(user=self.target).count(),
            Sessions.objects.filter(user=self.target).count(),
            Context.objects.filter(user=self.target).count(),
            Tag.objects.filter(user=self.target).count(),
        )

    def test_round_trip_preserves_metadata_identity_allocations_and_totals(self):
        source_project_total = next(iter(derived_project_totals(self.source).values()))
        source_sub_totals = {
            subproject.name: derived_subproject_totals(
                self.source, [subproject.pk]
            )[subproject.pk]
            for subproject in (self.planning, self.review)
        }

        response = self.post_import()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "projects_created": 1,
                "projects_updated": 0,
                "sessions_imported": 2,
                "sessions_skipped": 0,
                "conflicts": [],
            },
        )
        project = Projects.objects.get(user=self.target, name="Client Work")
        self.assertEqual(project.status, "paused")
        self.assertEqual(project.description, "Portable project")
        self.assertEqual(project.context.name, "Focused")
        self.assertEqual(list(project.tags.values_list("name", flat=True)), ["alpha", "beta"])
        self.assertEqual(derived_project_totals(self.target)[project.pk], source_project_total)

        target_subprojects = {
            subproject.name: subproject
            for subproject in SubProjects.objects.filter(parent_project=project)
        }
        self.assertEqual(set(target_subprojects), {"Planning", "Review"})
        self.assertEqual(target_subprojects["Planning"].description, "Plan it")
        for name, subproject in target_subprojects.items():
            self.assertEqual(
                derived_subproject_totals(self.target, [subproject.pk])[subproject.pk],
                source_sub_totals[name],
            )

        imported = {
            str(session.uuid): session
            for session in Sessions.objects.filter(user=self.target)
        }
        self.assertEqual(set(imported), {str(self.legacy.uuid), str(self.partitioned.uuid)})
        split = imported[str(self.partitioned.uuid)]
        self.assertEqual(split.allocation_mode, "partitioned")
        self.assertEqual(
            list(
                split.subproject_links.order_by("subproject__name").values_list(
                    "subproject__name", "allocation_bp"
                )
            ),
            [("Planning", 3000), ("Review", 7000)],
        )
        legacy = imported[str(self.legacy.uuid)]
        self.assertEqual(legacy.allocation_mode, "legacy_full")
        self.assertEqual(
            set(legacy.subproject_links.values_list("allocation_bp", flat=True)),
            {10000},
        )

    def test_idempotent_reimport_skips_every_session_and_creates_no_rows(self):
        self.assertEqual(self.post_import().status_code, 200)
        before = self.owned_counts()

        response = self.post_import()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sessions_imported"], 0)
        self.assertEqual(response.json()["sessions_skipped"], 2)
        self.assertEqual(response.json()["projects_created"], 0)
        self.assertEqual(self.owned_counts(), before)

    def test_conflict_rejects_batch_and_force_updates_in_place(self):
        self.assertEqual(self.post_import().status_code, 200)
        changed = copy.deepcopy(self.document)
        changed_session = changed["projects"][0]["sessions"][0]
        changed_session["note"] = "Changed note"
        session = Sessions.objects.get(user=self.target, uuid=changed_session["uuid"])
        old_id = session.id
        old_version = session.version
        before = self.owned_counts()

        response = self.post_import(changed)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "conflict")
        self.assertEqual(
            response.json()["error"]["details"]["conflicting_uuids"],
            [changed_session["uuid"]],
        )
        self.assertEqual(self.owned_counts(), before)
        session.refresh_from_db()
        self.assertNotEqual(session.note, "Changed note")

        response = self.post_import(changed, force=True)

        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.id, old_id)
        self.assertEqual(session.note, "Changed note")
        self.assertEqual(session.version, old_version + 1)

    def test_duplicate_uuid_in_batch_is_rejected(self):
        duplicate = copy.deepcopy(self.document)
        duplicate["projects"][0]["sessions"][1]["uuid"] = duplicate["projects"][0]["sessions"][0]["uuid"]

        response = self.post_import(duplicate)

        self.assertEqual(response.status_code, 400)
        self.assertIn("duplicate UUID", json.dumps(response.json()))
        self.assertEqual(Sessions.objects.filter(user=self.target).count(), 0)

    def test_invalid_allocations_reject_whole_batch_atomically(self):
        cases = (
            ("zero", 0, 7000),
            ("too_large", 10001, 7000),
            ("partition_sum", 4000, 7000),
        )
        for label, first_bp, second_bp in cases:
            with self.subTest(label=label):
                invalid = copy.deepcopy(self.document)
                split = next(
                    session
                    for session in invalid["projects"][0]["sessions"]
                    if session["allocation_mode"] == "partitioned"
                )
                split["links"][0]["allocation_bp"] = first_bp
                split["links"][1]["allocation_bp"] = second_bp
                before = self.owned_counts()

                response = self.post_import(invalid)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "validation_error")
                self.assertEqual(self.owned_counts(), before)

    def test_legacy_format1_payload_imports_through_v2_endpoint(self):
        payload = {
            "Legacy Project": {
                "Start Date": "01-02-2024",
                "Last Updated": "01-02-2024",
                "Total Time": 60.0,
                "Status": "active",
                "Description": "Legacy",
                "Context": "Legacy Context",
                "Tags": ["legacy"],
                "Sub Projects": {
                    "Bucket": {
                        "Start Date": "01-02-2024",
                        "Last Updated": "01-02-2024",
                        "Total Time": 60.0,
                        "Description": "Bucket",
                    }
                },
                "Session History": [
                    {
                        "Date": "01-02-2024",
                        "Start Time": "09:00:00",
                        "End Time": "10:00:00",
                        "Sub-Projects": ["Bucket"],
                        "Note": "Legacy session",
                    }
                ],
            }
        }

        response = self.post_import(payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sessions_imported"], 1)
        session = Sessions.objects.get(user=self.target)
        self.assertEqual(session.allocation_mode, "legacy_full")
        self.assertEqual(
            session.subproject_links.get().allocation_bp,
            10000,
        )

    def test_export_is_deterministic_and_v1_shape_is_unchanged(self):
        first = json.dumps(self.export_document(), separators=(",", ":"))
        second = json.dumps(self.export_document(), separators=(",", ":"))
        self.assertEqual(first, second)

        self.client.force_login(self.source)
        # Heritage format-1 now lives behind the v2 endpoint's format param.
        v1_response = self.client.get(reverse("api_v2:export"), {"export_format": "1"})
        self.assertEqual(v1_response.status_code, 200)
        v1 = v1_response.json()
        self.assertNotIn("format", v1)
        self.assertIn("Client Work", v1)
        self.assertIn("Session History", v1["Client Work"])

        v2_response = self.client.get(reverse("api_v2:export"))
        self.assertEqual(v2_response.status_code, 200)
        self.assertEqual(v2_response.json(), self.document)
        compressed = self.client.get(reverse("api_v2:export"), {"compress": "true"})
        self.assertEqual(json_decompress(compressed.json()), self.document)

        web_default = self.client.post(reverse("export"), {})
        self.assertEqual(web_default.json()["format"], 2)
        web_legacy = self.client.post(reverse("export"), {"legacy_format": "on"})
        self.assertNotIn("format", web_legacy.json())

    def test_missing_uuid_gets_a_fresh_identity(self):
        without_uuid = copy.deepcopy(self.document)
        without_uuid["projects"][0]["sessions"][0]["uuid"] = None

        response = self.post_import(without_uuid)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Sessions.objects.filter(user=self.target).count(), 2)
        self.assertTrue(
            all(
                session.uuid is not None
                for session in Sessions.objects.filter(user=self.target)
            )
        )

    def test_management_export_defaults_to_format2_and_supports_format1(self):
        with tempfile.TemporaryDirectory(dir="C:\\tmp") as temp_dir, patch(
            "core.management.commands.export.settings.BASE_DIR", Path(temp_dir)
        ):
            call_command("export", self.source.username, output_file="default.json")
            default = json.loads(
                (Path(temp_dir) / "Exports" / "default.json").read_text()
            )
            self.assertEqual(default["format"], 2)

            call_command(
                "export",
                self.source.username,
                output_file="legacy.json",
                format=1,
            )
            legacy = json.loads(
                (Path(temp_dir) / "Exports" / "legacy.json").read_text()
            )
            self.assertNotIn("format", legacy)
