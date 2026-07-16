import json
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import Projects, Sessions, SubProjects
from core.services import SessionMutationService
from core.totals import derived_project_totals, derived_subproject_totals


class SessionServiceFlooringTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="flooring-user", password="password"
        )
        self.project = Projects.objects.create(
            user=self.user, name="Flooring Project"
        )

    def test_create_session_floors_all_instants_and_preserves_tzinfo(self):
        tz = dt_timezone(timedelta(hours=5, minutes=30))
        start = datetime(2026, 7, 15, 9, 0, 0, 123456, tzinfo=tz)
        end = datetime(2026, 7, 15, 10, 0, 0, 234567, tzinfo=tz)
        auto_stop_at = datetime(2026, 7, 15, 11, 0, 0, 345678, tzinfo=tz)

        session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=start,
            end_time=end,
            auto_stop_at=auto_stop_at,
            is_active=False,
        )

        for value, original in (
            (session.start_time, start),
            (session.end_time, end),
            (session.auto_stop_at, auto_stop_at),
        ):
            self.assertEqual(value.microsecond, 0)
            self.assertEqual(value.tzinfo, original.tzinfo)

    def test_mutate_session_floors_all_provided_instants(self):
        session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=timezone.now() - timedelta(hours=2),
            is_active=True,
        )
        tz = dt_timezone(timedelta(hours=-4))
        start = datetime(2026, 7, 15, 9, 0, 0, 123456, tzinfo=tz)
        end = datetime(2026, 7, 15, 10, 0, 0, 234567, tzinfo=tz)
        auto_stop_at = datetime(2026, 7, 15, 11, 0, 0, 345678, tzinfo=tz)

        session = SessionMutationService.mutate_session(
            session.pk,
            user=self.user,
            start_time=start,
            end_time=end,
            auto_stop_at=auto_stop_at,
            is_active=False,
        )

        self.assertEqual(session.start_time.microsecond, 0)
        self.assertEqual(session.end_time.microsecond, 0)
        self.assertEqual(session.auto_stop_at.microsecond, 0)

    def test_mutate_session_leaves_untouched_instants_alone(self):
        start = timezone.now().replace(microsecond=123456)
        auto_stop_at = start + timedelta(hours=1, microseconds=111111)
        session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=start,
            auto_stop_at=auto_stop_at,
            is_active=True,
        )

        session = SessionMutationService.mutate_session(
            session.pk, user=self.user, note="Only the note changes"
        )

        self.assertEqual(session.start_time.microsecond, start.microsecond)
        self.assertEqual(
            session.auto_stop_at.microsecond, auto_stop_at.microsecond
        )

    def test_validation_runs_after_flooring(self):
        tz = dt_timezone.utc
        valid_start = datetime(2026, 7, 15, 9, 0, 0, 100000, tzinfo=tz)
        valid_end = datetime(2026, 7, 15, 9, 0, 0, 900000, tzinfo=tz)

        session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=valid_start,
            end_time=valid_end,
            is_active=False,
        )
        self.assertEqual(session.start_time, session.end_time)

        invalid_start = datetime(2026, 7, 15, 9, 0, 1, 100000, tzinfo=tz)
        invalid_end = datetime(2026, 7, 15, 9, 0, 0, 900000, tzinfo=tz)
        with self.assertRaises(ValidationError):
            SessionMutationService.create_session(
                user=self.user,
                project=self.project,
                start_time=invalid_start,
                end_time=invalid_end,
                is_active=False,
            )

    def test_replace_subprojects_moves_derived_totals(self):
        before_subproject = SubProjects.objects.create(
            user=self.user,
            name="Before",
            parent_project=self.project,
        )
        after_subproject = SubProjects.objects.create(
            user=self.user,
            name="After",
            parent_project=self.project,
        )
        start = timezone.now().replace(microsecond=0) - timedelta(minutes=30)
        session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=[before_subproject],
            start_time=start,
            end_time=start + timedelta(minutes=30),
            is_active=False,
        )

        self.assertEqual(
            derived_project_totals(self.user)[self.project.pk], 30
        )
        totals = derived_subproject_totals(self.user)
        self.assertEqual(totals[before_subproject.pk], 30)
        self.assertEqual(totals[after_subproject.pk], 0)

        session = SessionMutationService.replace_subprojects(
            session.pk,
            user=self.user,
            subprojects=[after_subproject],
        )

        self.assertEqual(list(session.subprojects.all()), [after_subproject])
        self.assertEqual(
            derived_project_totals(self.user)[self.project.pk], 30
        )
        totals = derived_subproject_totals(self.user)
        self.assertEqual(totals[before_subproject.pk], 0)
        self.assertEqual(totals[after_subproject.pk], 30)

    def test_timer_start_and_track_apis_floor_instants(self):
        self.client.force_login(self.user)
        timer_start = (timezone.now() - timedelta(hours=2)).replace(
            microsecond=654321
        )
        timer_response = self.client.post(
            "/api/timer/start/",
            data=json.dumps(
                {"project": self.project.name, "start": timer_start.isoformat()}
            ),
            content_type="application/json",
        )
        self.assertEqual(timer_response.status_code, 201)
        timer = Sessions.objects.get(pk=timer_response.json()["session"]["id"])
        self.assertEqual(timer.start_time.microsecond, 0)

        track_start = (timezone.now() - timedelta(hours=4)).replace(
            microsecond=123456
        )
        track_end = (track_start + timedelta(hours=1)).replace(
            microsecond=987654
        )
        track_response = self.client.post(
            "/api/track/",
            data=json.dumps(
                {
                    "project": self.project.name,
                    "start": track_start.isoformat(),
                    "end": track_end.isoformat(),
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(track_response.status_code, 201)
        tracked = Sessions.objects.get(
            pk=track_response.json()["session"]["id"]
        )
        self.assertEqual(tracked.start_time.microsecond, 0)
        self.assertEqual(tracked.end_time.microsecond, 0)
