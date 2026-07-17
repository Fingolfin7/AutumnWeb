from datetime import datetime, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import User
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from core.api_v2.exceptions import V2APIView
from core.api_v2.filters import SessionFilterSpec
from core.models import Context, Projects, Sessions, SubProjects, Tag
from core.services import SessionMutationService
from users.forms import ProfileUpdateForm


class ValidationProbeView(V2APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        raise ValidationError({"project_ids": ["Invalid project IDs."]})


class V2EndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="v2-user",
            password="password",
        )
        self.user.profile.timezone = "America/New_York"
        self.user.profile.save(update_fields=["timezone"])
        self.client = APIClient()

    def test_me_shape_with_session_authentication(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("api_v2:me"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "api_version": 2,
                "capabilities": [
                    "timers",
                    "sessions",
                    "projects",
                    "subprojects",
                    "contexts",
                    "tags",
                    "reports",
                    "commitments",
                    "export",
                    "import",
                ],
                "user": {
                    "id": self.user.id,
                    "username": "v2-user",
                    "email": self.user.email,
                    "timezone": "America/New_York",
                },
            },
        )

    def test_me_accepts_token_authentication(self):
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        response = self.client.get(reverse("api_v2:me"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["id"], self.user.id)

    def test_me_unauthenticated_uses_v2_envelope(self):
        response = self.client.get(reverse("api_v2:me"))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "not_authenticated")
        self.assertIsNone(response.json()["error"]["details"])

    def test_unknown_path_and_wrong_method_use_v2_envelope(self):
        response = self.client.get("/api/v2/does-not-exist/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

        self.client.force_authenticate(self.user)
        response = self.client.post(reverse("api_v2:me"), {}, format="json")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()["error"]["code"], "method_not_allowed")

    def test_validation_error_uses_v2_envelope_with_field_details(self):
        request = APIRequestFactory().get("/api/v2/validation-probe/")

        response = ValidationProbeView.as_view()(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertEqual(
            response.data["error"]["details"],
            {"project_ids": ["Invalid project IDs."]},
        )


class SessionVersionAndV1SafetyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="version-user",
            password="password",
        )
        self.project = Projects.objects.create(user=self.user, name="Version Project")

    def test_successful_mutations_increment_version(self):
        start = timezone.now().replace(microsecond=0) - timedelta(hours=1)
        session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=start,
            is_active=True,
        )
        self.assertEqual(session.version, 1)

        session = SessionMutationService.mutate_session(
            session.pk,
            user=self.user,
            end_time=start + timedelta(minutes=30),
            is_active=False,
        )
        self.assertEqual(session.version, 2)

        session = SessionMutationService.mutate_session(
            session.pk,
            user=self.user,
            note="edited",
        )
        self.assertEqual(session.version, 3)



class SessionFilterSpecTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="filter-user",
            password="password",
        )
        self.context = Context.objects.create(user=self.user, name="General")
        self.tag = Tag.objects.create(user=self.user, name="Focused")
        self.project = Projects.objects.create(
            user=self.user,
            name="Filtered Project",
            context=self.context,
        )
        self.project.tags.add(self.tag)
        self.subproject = SubProjects.objects.create(
            user=self.user,
            name="Included Subproject",
            parent_project=self.project,
        )

    def test_parses_typed_query_parameters_and_rejects_names(self):
        params = QueryDict(
            "project_ids={}&subproject_ids={}&context_ids={}&tag_ids={}"
            "&start_date=2026-01-02&end_date=2026-01-03&active=false"
            "&note_snippet=focus".format(
                self.project.id,
                self.subproject.id,
                self.context.id,
                self.tag.id,
            )
        )

        spec = SessionFilterSpec.from_query_params(params, self.user)

        self.assertEqual(spec.project_ids, frozenset({self.project.id}))
        self.assertEqual(spec.subproject_ids, frozenset({self.subproject.id}))
        self.assertEqual(spec.start_date.isoformat(), "2026-01-02")
        self.assertEqual(spec.end_date.isoformat(), "2026-01-03")
        self.assertFalse(spec.active)
        self.assertEqual(spec.note_snippet, "focus")

        with self.assertRaises(ValidationError) as caught:
            SessionFilterSpec.from_query_params(
                QueryDict("project_ids=Filtered Project"),
                self.user,
            )
        self.assertIn("project_ids", caught.exception.detail)

    def test_subproject_membership_filter_is_applied(self):
        other_project = Projects.objects.create(user=self.user, name="Other Project")
        other_subproject = SubProjects.objects.create(
            user=self.user,
            name="Excluded Subproject",
            parent_project=other_project,
        )
        end = timezone.now().replace(microsecond=0)
        included = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=[self.subproject],
            start_time=end - timedelta(minutes=20),
            end_time=end,
            is_active=False,
        )
        SessionMutationService.create_session(
            user=self.user,
            project=other_project,
            subprojects=[other_subproject],
            start_time=end - timedelta(minutes=10),
            end_time=end,
            is_active=False,
        )

        spec = SessionFilterSpec.from_query_params(
            QueryDict(f"subproject_ids={self.subproject.id}"),
            self.user,
        )

        self.assertEqual(
            list(spec.apply(Sessions.objects.filter(user=self.user))),
            [included],
        )

    def test_active_filter_is_applied_at_the_endpoint(self):
        # Regression: is_active became a derived property in S12; the filter
        # must translate to end_time__isnull instead of raising FieldError.
        end = timezone.now().replace(microsecond=0)
        completed = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=end - timedelta(minutes=30),
            end_time=end,
        )
        running = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=end - timedelta(minutes=5),
        )

        client = APIClient()
        client.force_authenticate(self.user)
        # The sessions endpoint is the completed log, so active=true is
        # vacuously empty; the regression is a FieldError 500 on either value.
        for flag, expected_ids in (("true", []), ("false", [completed.id])):
            with self.subTest(active=flag):
                response = client.get("/api/v2/sessions/", {"active": flag})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [row["id"] for row in response.json()["sessions"]],
                    expected_ids,
                )
        self.assertIsNone(running.end_time)

    def test_uuid_filter_returns_the_matching_session(self):
        end = timezone.now().replace(microsecond=0)
        target, other = (
            SessionMutationService.create_session(
                user=self.user,
                project=self.project,
                start_time=end - timedelta(minutes=20 + offset),
                end_time=end - timedelta(minutes=offset),
            )
            for offset in (0, 40)
        )

        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get("/api/v2/sessions/", {"uuid": str(target.uuid)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in response.json()["sessions"]], [target.id]
        )

        response = client.get("/api/v2/sessions/", {"uuid": "not-a-uuid"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("uuid", response.json()["error"]["details"])

    @freeze_time("2026-01-20 12:00:00")
    def test_date_boundaries_use_active_profile_timezone_and_end_time(self):
        self.user.profile.timezone = "America/Los_Angeles"
        self.user.profile.save(update_fields=["timezone"])
        utc = datetime_timezone.utc
        instants = (
            datetime(2026, 1, 15, 7, 59, 59, tzinfo=utc),
            datetime(2026, 1, 15, 8, 0, 0, tzinfo=utc),
            datetime(2026, 1, 16, 7, 59, 59, tzinfo=utc),
            datetime(2026, 1, 16, 8, 0, 0, tzinfo=utc),
        )
        sessions = []
        for index, end in enumerate(instants):
            sessions.append(
                SessionMutationService.create_session(
                    user=self.user,
                    project=self.project,
                    start_time=end - timedelta(minutes=5),
                    end_time=end,
                    note=f"boundary-{index}",
                    is_active=False,
                )
            )

        timezone.activate(ZoneInfo(self.user.profile.timezone))
        try:
            spec = SessionFilterSpec.from_query_params(
                QueryDict("start_date=2026-01-15&end_date=2026-01-15"),
                self.user,
            )
            result_ids = set(
                spec.apply(Sessions.objects.filter(user=self.user)).values_list(
                    "id", flat=True
                )
            )
        finally:
            timezone.deactivate()

        self.assertEqual(result_ids, {sessions[1].id, sessions[2].id})


class UserTimezoneMiddlewareTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="timezone-user",
            password="password",
        )
        self.project = Projects.objects.create(user=self.user, name="Timezone Project")
        self.end = datetime(2026, 1, 15, 12, 0, tzinfo=datetime_timezone.utc)
        SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=self.end - timedelta(hours=1),
            end_time=self.end,
            is_active=False,
        )
        self.client.force_login(self.user)

    def _boundary_session(self):
        # 2026-01-15T04:00Z is Jan 14 in New York but Jan 15 in Prague, so the
        # v2 date filter reveals which timezone the middleware activated.
        from core.services import SessionMutationService

        return SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=datetime(2026, 1, 15, 3, 0, tzinfo=datetime_timezone.utc),
            end_time=datetime(2026, 1, 15, 4, 0, tzinfo=datetime_timezone.utc),
            is_active=False,
        )

    def test_profile_timezone_drives_v2_date_filtering_and_cleans_up(self):
        session = self._boundary_session()
        self.user.profile.timezone = "America/New_York"
        self.user.profile.save(update_fields=["timezone"])

        on_ny_date = self.client.get(
            "/api/v2/sessions/", {"start_date": "2026-01-14", "end_date": "2026-01-14"}
        )
        self.assertIn(
            session.id, [row["id"] for row in on_ny_date.json()["sessions"]]
        )
        off_ny_date = self.client.get(
            "/api/v2/sessions/", {"start_date": "2026-01-15", "end_date": "2026-01-15"}
        )
        self.assertNotIn(
            session.id, [row["id"] for row in off_ny_date.json()["sessions"]]
        )
        self.assertEqual(timezone.get_current_timezone_name(), settings.TIME_ZONE)

    def test_invalid_profile_timezone_falls_back_safely_and_cleans_up(self):
        session = self._boundary_session()
        type(self.user.profile).objects.filter(pk=self.user.profile.pk).update(
            timezone="Invalid/Timezone"
        )

        # Fallback = server default (Europe/Prague): the instant is Jan 15.
        response = self.client.get(
            "/api/v2/sessions/", {"start_date": "2026-01-15", "end_date": "2026-01-15"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            session.id, [row["id"] for row in response.json()["sessions"]]
        )
        self.assertEqual(timezone.get_current_timezone_name(), settings.TIME_ZONE)


class ProfileTimezoneFormTests(TestCase):
    def test_profile_form_runs_iana_timezone_validation(self):
        user = User.objects.create_user(username="profile-form-user")
        form = ProfileUpdateForm(
            {"timezone": "Not/A-Timezone"},
            instance=user.profile,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("timezone", form.errors)
