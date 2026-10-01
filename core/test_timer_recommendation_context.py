"""Rich timer context assembly and stable fingerprint coverage."""
import json
from datetime import timedelta
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from core.models import Context, Projects, Sessions
from core.services.timer_recommendation_context import build_recommendation_candidates, build_recommendation_context, recommendation_cache_key


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

    def test_rich_context_contains_account_history_project_metadata_ytd_and_running_timers(self):
        history_project = Projects.objects.create(
            user=self.user,
            name="History project",
            description="Purpose from the project record.",
            context=self.context,
            status="active",
        )
        completed_at = timezone.now() - timedelta(days=2)
        Sessions.objects.create(
            user=self.user,
            project=history_project,
            start_time=completed_at - timedelta(minutes=35),
            end_time=completed_at,
            note="Full note with the unfinished next step.",
        )
        Sessions.objects.create(
            user=self.user,
            project=self.active,
            start_time=timezone.now() - timedelta(minutes=4),
        )
        request = self.client.get(reverse("luna_timer_recommendations")).wsgi_request
        candidates = build_recommendation_candidates(self.user, request)
        context = build_recommendation_context(self.user, request, candidates)

        project = next(row for row in context["projects"] if row["id"] == history_project.id)
        session = next(
            row for row in context["recent_completed_sessions"]
            if row["project_id"] == history_project.id
        )
        self.assertEqual(project["description"], "Purpose from the project record.")
        self.assertEqual(session["note"], "Full note with the unfinished next step.")
        self.assertEqual(session["duration_minutes"], 35.0)
        self.assertTrue(project["ytd_monthly_totals"])
        self.assertIn("running_timers", context)
        self.assertIn(self.active.id, {row["project_id"] for row in context["running_timers"]})
        self.assertEqual(context["history_coverage"]["requested_days"], 30)
        self.assertFalse(context["history_coverage"]["notes_truncated"])

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
        request = self.client.get(reverse("luna_timer_recommendations")).wsgi_request
        candidates = build_recommendation_candidates(self.user, request)
        context = build_recommendation_context(self.user, request, candidates)
        self.assertNotIn(other_project.id, {candidate["project_id"] for candidate in candidates})
        self.assertIn(
            "Other-context history should remain evidence.",
            {row["note"] for row in context["recent_completed_sessions"]},
        )

    def test_cache_bucket_ignores_exact_clock_but_changes_with_note(self):
        request = self.client.get(reverse("luna_timer_recommendations")).wsgi_request
        candidates = build_recommendation_candidates(self.user, request)
        context = build_recommendation_context(self.user, request, candidates)
        first = recommendation_cache_key(self.user, request, candidates, context)
        changed = json.loads(json.dumps(context))
        changed["now"]["local_datetime"] = "2099-01-01T01:02:03+00:00"
        changed["now"]["local_time"] = "01:02:03"
        changed["now"]["cache_bucket"] += 1
        self.assertEqual(first, recommendation_cache_key(self.user, request, candidates, changed))
        changed["recent_completed_sessions"].append(
            {"id": 999, "project_id": self.active.id, "note": "new evidence"}
        )
        self.assertNotEqual(first, recommendation_cache_key(self.user, request, candidates, changed))
