from datetime import datetime, timedelta, timezone as datetime_timezone
from uuid import uuid4

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from freezegun import freeze_time
from rest_framework.test import APIClient

from core.models import Projects, Sessions, SubProjects
from core.services import SessionMutationService


UTC = datetime_timezone.utc


class V2TimersSessionsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="v2-resources", email="v2-resources@example.com"
        )
        self.project = Projects.objects.create(user=self.user, name="Main")
        self.subproject_a = SubProjects.objects.create(
            user=self.user,
            parent_project=self.project,
            name="Alpha",
        )
        self.subproject_b = SubProjects.objects.create(
            user=self.user,
            parent_project=self.project,
            name="Beta",
        )
        self.other_user = User.objects.create_user(
            username="v2-other", email="v2-other@example.com"
        )
        self.foreign_project = Projects.objects.create(
            user=self.other_user, name="Foreign"
        )
        self.foreign_subproject = SubProjects.objects.create(
            user=self.other_user,
            parent_project=self.foreign_project,
            name="Foreign subproject",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _track_payload(self, **overrides):
        payload = {
            "project_id": self.project.id,
            "start": "2026-07-16T09:00:00Z",
            "end": "2026-07-16T10:00:00Z",
        }
        payload.update(overrides)
        return payload

    def _create_completed(self, *, end, note=None, subprojects=()):
        return SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=subprojects,
            start_time=end - timedelta(minutes=30),
            end_time=end,
            note=note,
            is_active=False,
        )

    @freeze_time("2026-07-16 12:00:00")
    def test_timer_start_restart_stop_and_active_delete_happy_paths(self):
        response = self.client.post(
            reverse("api_v2:timers"),
            {
                "project_id": self.project.id,
                "subproject_ids": [self.subproject_a.id],
                "start": "2026-07-16T10:00:00",
                "stop_after_minutes": 30,
                "note": "focus",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        timer_id = response.json()["id"]
        self.assertEqual(response.json()["start"], "2026-07-16T10:00:00+00:00")
        self.assertEqual(
            response.json()["auto_stop_at"], "2026-07-16T10:30:00+00:00"
        )

        response = self.client.post(
            reverse("api_v2:timer-restart", args=[timer_id]),
            {"start": "2026-07-16T10:15:00Z"},
            format="json",
            HTTP_IF_MATCH="1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], 2)
        self.assertEqual(
            response.json()["auto_stop_at"], "2026-07-16T10:45:00+00:00"
        )

        response = self.client.post(
            reverse("api_v2:timer-stop", args=[timer_id]),
            {"end": "2026-07-16T10:25:00+00:00", "note": "done"},
            format="json",
            HTTP_IF_MATCH="2",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["active"])
        self.assertEqual(response.json()["duration_minutes"], 10.0)
        self.assertEqual(response.json()["version"], 3)
        self.assertEqual(response.json()["note"], "done")

        active = self.client.post(
            reverse("api_v2:timers"),
            {"project_id": self.project.id},
            format="json",
        ).json()
        response = self.client.delete(
            reverse("api_v2:timer-detail", args=[active["id"]]),
            HTTP_IF_MATCH=str(active["version"]),
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Sessions.objects.filter(pk=active["id"]).exists())

    @freeze_time("2026-07-16 12:00:00")
    def test_timer_uuid_retry_returns_same_session_with_200(self):
        client_uuid = str(uuid4())
        payload = {
            "project_id": self.project.id,
            "start": "2026-07-16T11:00:00Z",
            "uuid": client_uuid,
        }
        first = self.client.post(reverse("api_v2:timers"), payload, format="json")
        retry = self.client.post(reverse("api_v2:timers"), payload, format="json")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()["id"], first.json()["id"])
        self.assertEqual(Sessions.objects.filter(user=self.user).count(), 1)

    @freeze_time("2026-07-16 12:00:00")
    def test_terminal_retry_precedes_version_and_active_stale_version_conflicts(self):
        start = datetime(2026, 7, 16, 10, 0, tzinfo=UTC)
        stopped = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=start,
            end_time=start + timedelta(minutes=20),
            is_active=False,
        )
        response = self.client.post(
            reverse("api_v2:timer-stop", args=[stopped.id]),
            {"end": "not-an-instant", "note": "ignored"},
            format="json",
            HTTP_IF_MATCH="0",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], 1)
        self.assertIsNone(response.json()["note"])

        active = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=start,
            is_active=True,
        )
        response = self.client.post(
            reverse("api_v2:timer-stop", args=[active.id]),
            {},
            format="json",
            HTTP_IF_MATCH="0",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "version_conflict")
        self.assertEqual(
            response.json()["error"]["details"]["current"]["id"], active.id
        )

        response = self.client.delete(
            reverse("api_v2:timer-detail", args=[999999]),
            HTTP_IF_MATCH="not-an-integer",
        )
        self.assertEqual(response.status_code, 204)

    @freeze_time("2026-07-16 12:00:00")
    def test_track_uuid_dedup_canonical_note_equality_and_conflict(self):
        client_uuid = str(uuid4())
        first_payload = self._track_payload(uuid=client_uuid, note=None)
        first = self.client.post(
            reverse("api_v2:sessions"), first_payload, format="json"
        )
        retry = self.client.post(
            reverse("api_v2:sessions"),
            self._track_payload(uuid=client_uuid, note=""),
            format="json",
        )
        conflict = self.client.post(
            reverse("api_v2:sessions"),
            self._track_payload(uuid=client_uuid, note="different"),
            format="json",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()["id"], first.json()["id"])
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "uuid_conflict")
        self.assertEqual(Sessions.objects.filter(user=self.user).count(), 1)

    def test_sessions_list_pagination_order_notes_and_subproject_filter(self):
        tied_end = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
        older = self._create_completed(
            end=tied_end - timedelta(hours=1), note="older"
        )
        tied_first = self._create_completed(end=tied_end, note="first")
        tied_second = self._create_completed(
            end=tied_end,
            note="second",
            subprojects=[self.subproject_a],
        )

        response = self.client.get(
            reverse("api_v2:sessions"), {"limit": 2, "offset": 0}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 3)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(
            [item["id"] for item in response.json()["sessions"]],
            [tied_second.id, tied_first.id],
        )
        self.assertNotIn("note", response.json()["sessions"][0])

        response = self.client.get(
            reverse("api_v2:sessions"),
            {"include": "note", "subproject_ids": self.subproject_a.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["sessions"][0]["id"], tied_second.id)
        self.assertEqual(response.json()["sessions"][0]["note"], "second")
        self.assertNotEqual(older.id, tied_first.id)

    @freeze_time("2026-01-20 12:00:00")
    def test_sessions_list_date_range_uses_user_timezone(self):
        self.user.profile.timezone = "America/New_York"
        self.user.profile.save(update_fields=["timezone"])
        self.client.force_authenticate(user=None)
        self.client.force_login(self.user)
        instants = [
            datetime(2026, 1, 15, 4, 59, 59, tzinfo=UTC),
            datetime(2026, 1, 15, 5, 0, 0, tzinfo=UTC),
            datetime(2026, 1, 16, 4, 59, 59, tzinfo=UTC),
            datetime(2026, 1, 16, 5, 0, 0, tzinfo=UTC),
        ]
        sessions = [self._create_completed(end=end) for end in instants]

        response = self.client.get(
            reverse("api_v2:sessions"),
            {"start_date": "2026-01-15", "end_date": "2026-01-15"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["id"] for item in response.json()["sessions"]},
            {sessions[1].id, sessions[2].id},
        )

    @freeze_time("2026-07-16 12:00:00")
    def test_session_patch_honors_if_match_and_bumps_version(self):
        session = self._create_completed(
            end=datetime(2026, 7, 16, 10, 0, tzinfo=UTC), note="before"
        )
        response = self.client.patch(
            reverse("api_v2:session-detail", args=[session.id]),
            {"note": "after", "subproject_ids": [self.subproject_b.id]},
            format="json",
            HTTP_IF_MATCH="1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], 2)
        self.assertEqual(response.json()["note"], "after")
        self.assertEqual(
            response.json()["subproject_allocations"][0]["subproject_id"],
            self.subproject_b.id,
        )

        stale = self.client.patch(
            reverse("api_v2:session-detail", args=[session.id]),
            {"note": "stale"},
            format="json",
            HTTP_IF_MATCH="1",
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(
            stale.json()["error"]["details"]["current"]["version"], 2
        )

    @freeze_time("2026-07-16 12:00:00")
    def test_validation_errors_for_ranges_future_and_foreign_resources(self):
        response = self.client.post(
            reverse("api_v2:sessions"),
            self._track_payload(
                start="2026-07-16T10:00:00Z",
                end="2026-07-16T09:00:00Z",
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "validation_error")

        future = self.client.post(
            reverse("api_v2:timers"),
            {"project_id": self.project.id, "start": "2026-07-16T12:06:00Z"},
            format="json",
        )
        self.assertEqual(future.status_code, 400)

        foreign_project = self.client.post(
            reverse("api_v2:timers"),
            {"project_id": self.foreign_project.id},
            format="json",
        )
        self.assertEqual(foreign_project.status_code, 404)
        self.assertEqual(
            foreign_project.json()["error"]["code"], "not_found"
        )

        foreign_subproject = self.client.post(
            reverse("api_v2:timers"),
            {
                "project_id": self.project.id,
                "subproject_ids": [self.foreign_subproject.id],
            },
            format="json",
        )
        self.assertEqual(foreign_subproject.status_code, 400)
        self.assertEqual(
            foreign_subproject.json()["error"]["code"], "validation_error"
        )

        future_track = self.client.post(
            reverse("api_v2:sessions"),
            self._track_payload(end="2026-07-16T12:06:00Z"),
            format="json",
        )
        self.assertEqual(future_track.status_code, 400)

    def test_multi_link_resource_has_stable_allocations_and_legacy_mode(self):
        session = self._create_completed(
            end=datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
            subprojects=[self.subproject_b, self.subproject_a],
        )
        response = self.client.get(
            reverse("api_v2:session-detail", args=[session.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["allocation_mode"], "legacy_full")
        self.assertEqual(
            response.json()["subproject_allocations"],
            [
                {
                    "subproject_id": self.subproject_a.id,
                    "name": "Alpha",
                    "allocation_bp": 10000,
                },
                {
                    "subproject_id": self.subproject_b.id,
                    "name": "Beta",
                    "allocation_bp": 10000,
                },
            ],
        )
