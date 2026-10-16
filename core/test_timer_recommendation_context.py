"""Rich timer context assembly and stable fingerprint coverage."""
from datetime import timedelta
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from core.models import Context, Projects, Sessions
from core.services.timer_recommendation_context import build_recommendation_candidates, build_recommendation_context


class TimerRecommendationContextTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="luna-user", email="luna@example.com", password="pw"
        )
        self.context = Context.objects.create(user=self.user, name="Work")
        self.active = Projects.objects.create(
            user=self.user, name="Active project", context=self.context, status="active"
        )
        self.complete = Projects.objects.create(
            user=self.user,
            name="Completed project",
            context=self.context,
            status="complete",
        )
        self.user.profile.ai_features_enabled = True
        self.user.profile.save(update_fields=["ai_features_enabled"])
        self.client.login(username="luna-user", password="pw")
        cache.clear()


    def test_selected_context_limits_candidates_but_history_remains_account_wide(self):
        other_context = Context.objects.create(user=self.user, name="Personal")
        other_project = Projects.objects.create(
            user=self.user, name="Other context", context=other_context, status="active"
        )
        completed_at = timezone.now() - timedelta(days=1)
        Sessions.objects.create(
            user=self.user,
            project=other_project,
            start_time=completed_at - timedelta(minutes=10),
            end_time=completed_at,
            note="Other-context history should remain evidence.",
        )
        session = self.client.session
        session["active_context_id"] = str(self.context.id)
        session.save()
        request = self.client.get("/api/v2/recommendations/luna/").wsgi_request
        candidates = build_recommendation_candidates(self.user, request)
        context = build_recommendation_context(self.user, request, candidates)
        self.assertNotIn(other_project.id, {candidate["project_id"] for candidate in candidates})
        self.assertIn(
            "Other-context history should remain evidence.",
            {row["note"] for row in context["recent_completed_sessions"]},
        )
