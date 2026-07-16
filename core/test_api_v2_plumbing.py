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
from core.serializers import SessionSerializer
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

    def test_v1_timer_start_and_session_serializer_hide_new_identity_fields(self):
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.post(
            reverse("api_timer_start"),
            {"project": self.project.name},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        timer_payload = response.data["session"]
        self.assertNotIn("version", timer_payload)
        self.assertNotIn("uuid", timer_payload)

        session = Sessions.objects.get(pk=timer_payload["id"])
        serializer_payload = SessionSerializer(session).data
        self.assertNotIn("version", serializer_payload)
        self.assertNotIn("uuid", serializer_payload)


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

    def test_profile_timezone_is_active_during_v1_rendering_and_cleaned_up(self):
        self.user.profile.timezone = "America/New_York"
        self.user.profile.save(update_fields=["timezone"])

        response = self.client.get(reverse("api_list_sessions"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["end_time"], "2026-01-15T07:00:00-05:00")
        self.assertEqual(timezone.get_current_timezone_name(), settings.TIME_ZONE)

    def test_invalid_profile_timezone_falls_back_safely_and_cleans_up(self):
        type(self.user.profile).objects.filter(pk=self.user.profile.pk).update(
            timezone="Invalid/Timezone"
        )

        response = self.client.get(reverse("api_list_sessions"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["end_time"], "2026-01-15T13:00:00+01:00")
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
