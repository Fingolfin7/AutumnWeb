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
from rest_framework.test import APIClient, APIRequestFactory

from core.api_v2.exceptions import V2APIView
from core.api_v2.filters import SessionFilterSpec
from core.models import Context, Projects, Sessions, SubProjects, Tag
from core.services import SessionMutationService


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


    def test_validation_error_uses_v2_envelope_with_field_details(self):
        request = APIRequestFactory().get("/api/v2/validation-probe/")

        response = ValidationProbeView.as_view()(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertEqual(
            response.data["error"]["details"],
            {"project_ids": ["Invalid project IDs."]},
        )


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
