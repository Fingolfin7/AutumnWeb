import copy
import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Context, Projects, Sessions, SubProjects
from core.totals import derived_project_totals
from core.utils import json_compress


class ImportJsonApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="api-import", password="password")
        self.client.force_login(self.user)
        self.url = reverse("api_v2:import")

    def payload(self):
        return {
            "Client Work": {
                "Start Date": "01-02-2024",
                "Last Updated": "01-02-2024",
                "Total Time": 60.0,
                "Status": "active",
                "Description": "Imported work",
                "Context": "Exported Context",
                "Tags": ["important"],
                "Sub Projects": {
                    "Planning": {
                        "Start Date": "01-02-2024",
                        "Last Updated": "01-02-2024",
                        "Total Time": 60.0,
                        "Description": "Planning work",
                    }
                },
                "Session History": [
                    {
                        "Date": "01-02-2024",
                        "Start Time": "09:00:00",
                        "End Time": "10:00:00",
                        "Sub-Projects": ["Planning"],
                        "Note": "First import",
                    }
                ],
            }
        }

    def post(self, body):
        return self.client.post(
            self.url,
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_fresh_import_creates_project_sessions_and_named_context(self):
        response = self.post({"data": self.payload(), "context": "Focused Work"})

        self.assertEqual(response.status_code, 200)
        summary = response.json()
        self.assertEqual(summary["projects_created"], 1)
        self.assertEqual(summary["sessions_imported"], 1)
        self.assertEqual(summary.get("skipped", []), [])

        context = Context.objects.get(user=self.user, name="Focused Work")
        project = Projects.objects.get(user=self.user, name="Client Work")
        self.assertEqual(project.context, context)
        self.assertEqual(derived_project_totals(self.user)[project.pk], 60.0)
        subproject = SubProjects.objects.get(user=self.user, parent_project=project, name="planning")
        session = Sessions.objects.get(user=self.user, project=project)
        self.assertEqual(list(session.subprojects.all()), [subproject])

        # Context matching is case-insensitive and must not create a duplicate.
        response = self.post(
            {"data": self.payload(), "force": True, "context": "focused work"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Context.objects.filter(user=self.user, name__iexact="focused work").count(), 1)

    def test_reimport_skips_existing_project_and_merge_imports_new_session(self):
        self.post({"data": self.payload()})

        response = self.post({"data": self.payload()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["skipped"], ["Client Work"])

        payload = copy.deepcopy(self.payload())
        project_data = payload["Client Work"]
        project_data["Sub Projects"]["Review"] = {
            "Start Date": "01-02-2024",
            "Last Updated": "01-02-2024",
            "Total Time": 60.0,
            "Description": "Review work",
        }
        project_data["Session History"].append(
            {
                "Date": "01-02-2024",
                "Start Time": "10:00:00",
                "End Time": "11:00:00",
                "Sub-Projects": ["Review"],
                "Note": "Merged import",
            }
        )
        project_data["Total Time"] = 120.0

        response = self.post({"data": payload, "merge": True})
        self.assertEqual(response.status_code, 200)
        summary = response.json()
        self.assertEqual(summary["projects_updated"], 1)
        self.assertEqual(summary["sessions_imported"], 1)
        self.assertEqual(Sessions.objects.filter(user=self.user).count(), 2)
        self.assertTrue(
            SubProjects.objects.filter(user=self.user, name="review").exists()
        )

    def test_tolerance_skips_near_duplicate_session(self):
        self.post({"data": self.payload()})
        payload = copy.deepcopy(self.payload())
        session = payload["Client Work"]["Session History"][0]
        session["Start Time"] = "09:01:00"
        session["End Time"] = "10:01:00"

        response = self.post({"data": payload, "merge": True, "tolerance": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sessions_imported"], 0)
        self.assertEqual(Sessions.objects.filter(user=self.user).count(), 1)

    def test_compressed_payload_and_malformed_payloads(self):
        compressed = json.dumps(json_compress(self.payload()))
        response = self.post({"data_compressed": compressed})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Projects.objects.filter(user=self.user, name="Client Work").exists())

        response = self.post({"data": ["not", "an", "object"]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "validation_error")

        response = self.post({"data": self.payload(), "data_compressed": compressed})
        self.assertEqual(response.status_code, 400)
        self.assertIn("exactly one", str(response.json()["error"]["details"]))
