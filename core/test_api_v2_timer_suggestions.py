"""Timer suggestions (recent, habit, commitment) through GET /api/v2/recommendations/timers/.

Ported from the old Timers page tests in core.tests.TimerSuggestionsTests: the
React Start and Timers pages build their preset lists from this payload.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Commitment, Context, Projects, Sessions, SubProjects

URL = "/api/v2/recommendations/timers/"


class TimerSuggestionsApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="timeruser", email="timer@example.com", password="testpass123"
        )
        self.context = Context.objects.create(user=self.user, name="General")
        self.project = Projects.objects.create(
            user=self.user, name="Timer Project", context=self.context
        )
        self.subproject = SubProjects.objects.create(
            user=self.user, name="Build", parent_project=self.project
        )
        self.client.force_login(self.user)

    def _completed(self, start_time=None, project=None, subprojects=None):
        start_time = start_time or timezone.now() - timedelta(hours=2)
        session = Sessions.objects.create(
            user=self.user,
            project=project or self.project,
            start_time=start_time,
            end_time=start_time + timedelta(minutes=45),
            is_active=False,
        )
        if subprojects:
            session.subprojects.add(*subprojects)
        return session

    def _suggestions(self, **params):
        response = self.client.get(URL, params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_recent_presets_carry_project_and_subprojects(self):
        self._completed(subprojects=[self.subproject])
        recent = self._suggestions()["recent"]
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["project"], {"id": self.project.pk, "name": "Timer Project"})
        self.assertEqual(
            recent[0]["subprojects"], [{"id": self.subproject.pk, "name": "Build"}]
        )

    def test_habit_suggestions_follow_the_same_weekday_and_hour(self):
        self._completed(start_time=timezone.now() - timedelta(days=7))
        habits = self._suggestions()["habits"]
        self.assertEqual(len(habits), 1)
        self.assertEqual(habits[0]["project"]["id"], self.project.pk)
        self.assertEqual(habits[0]["metric"], "1x")

    def test_commitment_suggestions_say_how_much_is_left(self):
        Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type="time",
            period="weekly",
            target=120,
        )
        commitments = self._suggestions()["commitments"]
        self.assertEqual(len(commitments), 1)
        self.assertEqual(commitments[0]["project"]["id"], self.project.pk)
        self.assertIn("remaining", commitments[0]["detail"])

    def test_nothing_to_suggest_without_history_or_commitments(self):
        self.assertEqual(
            self._suggestions(), {"commitments": [], "habits": [], "recent": []}
        )

    def test_a_context_filter_limits_the_suggestions(self):
        other = Context.objects.create(user=self.user, name="Elsewhere")
        elsewhere = Projects.objects.create(user=self.user, name="Elsewhere project", context=other)
        self._completed()
        self._completed(project=elsewhere)
        names = {row["project"]["name"] for row in self._suggestions(context=self.context.pk)["recent"]}
        self.assertEqual(names, {"Timer Project"})

    def test_other_accounts_are_never_suggested(self):
        other_user = User.objects.create_user(username="other", email="o@example.com", password="pw")
        foreign = Projects.objects.create(user=other_user, name="Foreign")
        Sessions.objects.create(
            user=other_user,
            project=foreign,
            start_time=timezone.now() - timedelta(days=7),
            end_time=timezone.now() - timedelta(days=7) + timedelta(minutes=30),
        )
        payload = self._suggestions()
        self.assertEqual(payload, {"commitments": [], "habits": [], "recent": []})
