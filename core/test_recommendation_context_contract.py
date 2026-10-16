"""Independent integration checks for domain data crossing the Recommendation boundary."""

import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.utils import timezone
from freezegun import freeze_time

from core.models import Projects, Sessions, SubProjects
from core.services.recommendation_state import build_recommendation_state
from core.services.timer_recommendation_context import build_recommendation_candidates, build_recommendation_context


@freeze_time("2026-09-19 12:00:00+00:00")
class RecommendationContextContractTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("luna-contract", email="contract@example.com")
        self.project = Projects.objects.create(user=self.user, name="Own project")
        self.request = RequestFactory().get("/timers/luna-recommendations/")
        self.request.user = self.user
        self.request.session = {}

    def payload(self):
        candidates = build_recommendation_candidates(self.user, self.request)
        context = build_recommendation_context(self.user, self.request, candidates)
        return build_recommendation_state(candidates, context)


    def test_other_account_and_malformed_foreign_links_never_supply_text(self):
        other = User.objects.create_user("luna-other", email="other@example.com")
        foreign = Projects.objects.create(
            user=other, name="FOREIGN_PROJECT", description="FOREIGN_DESCRIPTION",
        )
        sub = SubProjects.objects.create(
            user=other, parent_project=foreign, name="FOREIGN_SUBPROJECT",
            description="FOREIGN_SUBPROJECT_DESCRIPTION",
        )
        end = timezone.now() - timedelta(hours=1)
        Sessions.objects.create(
            user=other, project=foreign, start_time=end - timedelta(minutes=30),
            end_time=end, note="FOREIGN_NOTE",
        )
        # Legacy/imported malformed links must not defeat account isolation.
        Sessions.objects.create(
            user=self.user, project=foreign, start_time=end - timedelta(minutes=30),
            end_time=end, note="MALFORMED_FOREIGN_PROJECT_NOTE",
        )
        running = Sessions.objects.create(
            user=self.user, project=self.project, start_time=end,
        )
        running.subprojects.add(sub)
        Projects.objects.create(user=self.user, name="Available")

        serialized = json.dumps(self.payload())

        self.assertNotIn("FOREIGN", serialized)
