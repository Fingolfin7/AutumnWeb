"""Focused coverage for the progressive Jev timer recommendation layer."""

import json
import os
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Context, Projects, Sessions, SubProjects
from core.services.jev_timer_context import (
    build_jev_candidates,
    build_jev_context,
    jev_cache_key,
)


class JevTimerRecommendationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="jev-user", email="jev@example.com", password="pw"
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
        self.client.login(username="jev-user", password="pw")
        cache.clear()

    def _enable_key(self):
        return mock.patch.object(
            type(self.user.profile), "get_api_key", return_value="test-key"
        )

    def test_endpoint_requires_authentication(self):
        self.client.logout()
        response = self.client.get(reverse("jev_timer_recommendations"))
        self.assertEqual(response.status_code, 302)

    def test_missing_key_returns_empty_fragment_without_calling_ranker(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "core.views.timers.rank_timer_candidates"
        ) as ranker, mock.patch.object(type(self.user.profile), "get_api_key", return_value=None):
            response = self.client.get(reverse("jev_timer_recommendations"))

        self.assertEqual(response.status_code, 204)
        ranker.assert_not_called()

    @override_settings(DEBUG=False)
    def test_production_does_not_use_global_key_without_profile_key(self):
        with mock.patch.dict(
            os.environ,
            {"TYPESAFE_API_KEY": "global-key", "JEV_KEY": "legacy-key"},
            clear=False,
        ), mock.patch(
            "core.views.timers.rank_timer_candidates"
        ) as ranker, mock.patch.object(
            type(self.user.profile), "get_api_key", return_value=None
        ):
            response = self.client.get(reverse("jev_timer_recommendations"))

        self.assertEqual(response.status_code, 204)
        ranker.assert_not_called()

    def test_candidates_are_active_only_deduplicated_and_exclude_running_projects(self):
        available = Projects.objects.create(
            user=self.user,
            name="Available project",
            context=self.context,
            status="active",
        )
        # This timer must remove the active project from Jev candidates even
        # when historical deterministic suggestions exist for that project.
        Sessions.objects.create(
            user=self.user,
            project=self.active,
            start_time=timezone.now() - timedelta(minutes=4),
        )
        Sessions.objects.create(
            user=self.user,
            project=self.complete,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
        )

        def ranker(**kwargs):
            self.ranker_payload = kwargs
            return {
                "recommendations": [
                    {
                        "candidate_id": candidate["id"],
                        "score": 3.5,
                        "confidence": 0.2,
                    }
                    for candidate in kwargs["candidates"]
                ],
            }

        with self._enable_key(), mock.patch(
            "core.views.timers.rank_timer_candidates", side_effect=ranker
        ):
            response = self.client.get(reverse("jev_timer_recommendations"))

        self.assertEqual(response.status_code, 200)
        candidates = self.ranker_payload["candidates"]
        self.assertTrue(candidates)
        self.assertIn(available.id, {candidate["project_id"] for candidate in candidates})
        self.assertNotIn(self.active.id, {candidate["project_id"] for candidate in candidates})
        self.assertNotIn(self.complete.id, {candidate["project_id"] for candidate in candidates})
        self.assertEqual(
            len({candidate["id"] for candidate in candidates}), len(candidates)
        )
        payload_text = json.dumps(self.ranker_payload)
        self.assertIn("recent_completed_sessions", payload_text)
        self.assertIn("running_timers", payload_text)

    def test_duplicate_timer_combo_aggregates_all_local_signals(self):
        deterministic = {
            "commitments": [
                {
                    "kind": "commitment",
                    "detail": "30 min remaining",
                    "jev_detail": "30 min remaining with 6 days remaining",
                    "metric": "30%",
                    "project": self.active,
                    "subprojects": [],
                }
            ],
            "habits": [
                {
                    "kind": "habit",
                    "detail": "2 matching sessions",
                    "jev_detail": "2 matching sessions within the same weekday +/-2-hour window",
                    "metric": "2x",
                    "project": self.active,
                    "subprojects": [],
                }
            ],
            "recent": [
                {
                    "kind": "recent",
                    "detail": "Last used today",
                    "jev_detail": "Used today",
                    "metric": "recent",
                    "project": self.active,
                    "subprojects": [],
                }
            ],
        }

        with self._enable_key(), mock.patch(
            "core.views.timers.build_timer_suggestions", return_value=deterministic
        ), mock.patch(
            "core.views.timers.rank_timer_candidates",
            side_effect=lambda **kwargs: {
                "recommendations": [
                    {
                        "candidate_id": candidate["id"],
                        "score": 3.0,
                        "confidence": 0.1,
                    }
                    for candidate in kwargs["candidates"]
                ],
            },
        ) as ranker:
            response = self.client.get(reverse("jev_timer_recommendations"))

        self.assertEqual(response.status_code, 200)
        candidate = ranker.call_args.kwargs["candidates"][0]
        self.assertEqual(
            [signal["kind"] for signal in candidate["signals"]],
            ["commitment", "habit", "recent"],
        )
        self.assertEqual(
            [signal["detail"] for signal in candidate["signals"]],
            [
                "30 min remaining with 6 days remaining",
                "2 matching sessions within the same weekday +/-2-hour window",
                "Used today",
            ],
        )
        self.assertEqual(candidate["reason"], "30 min remaining")

    def test_ranked_result_renders_top_three_and_keeps_deterministic_reason(self):
        other = Projects.objects.create(
            user=self.user, name="Another active", context=self.context, status="active"
        )

        with self._enable_key(), mock.patch(
            "core.views.timers.rank_timer_candidates",
            return_value={
                "recommendations": [
                    {
                        "candidate_id": f"project:{self.active.id}:subprojects:",
                        "score": 4.0,
                        "confidence": 0.3,
                    },
                    {
                        "candidate_id": f"project:{other.id}:subprojects:",
                        "score": 3.0,
                        "confidence": 0.2,
                    },
                ],
            },
        ) as ranker:
            response = self.client.get(reverse("jev_timer_recommendations"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jev Recommends")
        self.assertContains(response, "Active project")
        self.assertContains(response, "Another active")
        ranker.assert_called_once()

    def test_uncertain_or_failed_ranker_has_no_jev_section(self):
        with self._enable_key(), mock.patch(
            "core.views.timers.rank_timer_candidates",
            return_value={"candidate_ids": [], "confidence": "uncertain"},
        ):
            response = self.client.get(reverse("jev_timer_recommendations"))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["Cache-Control"], "no-store")

        cache.clear()
        with self._enable_key(), mock.patch(
            "core.views.timers.rank_timer_candidates", side_effect=RuntimeError("down")
        ):
            response = self.client.get(reverse("jev_timer_recommendations"))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_timer_page_keeps_jev_mount_and_collapsed_groups(self):
        Sessions.objects.create(
            user=self.user,
            project=self.active,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
        )
        response = self.client.get(reverse("timers"))
        self.assertContains(response, 'data-jev-url="')
        self.assertContains(response, 'class="suggest-group disclose is-closed"')

    def test_subproject_deleted_during_ranking_does_not_become_base_timer(self):
        sub = SubProjects.objects.create(user=self.user, parent_project=self.active, name="Original combo")
        ended = timezone.now() - timedelta(hours=1)
        session = Sessions.objects.create(
            user=self.user, project=self.active,
            start_time=ended - timedelta(minutes=10), end_time=ended,
        )
        session.subprojects.add(sub)

        def ranker(**kwargs):
            candidate = next(row for row in kwargs["candidates"] if sub.id in row["subproject_ids"])
            sub.delete()
            return {"recommendations": [{"candidate_id": candidate["id"], "score": 4.0}]}

        with self._enable_key(), mock.patch("core.views.timers.rank_timer_candidates", side_effect=ranker):
            response = self.client.get(reverse("jev_timer_recommendations"))
        self.assertEqual(response.status_code, 204)

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
        request = self.client.get(reverse("jev_timer_recommendations")).wsgi_request
        candidates = build_jev_candidates(self.user, request)
        context = build_jev_context(self.user, request, candidates)

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
        request = self.client.get(reverse("jev_timer_recommendations")).wsgi_request
        candidates = build_jev_candidates(self.user, request)
        context = build_jev_context(self.user, request, candidates)
        self.assertNotIn(other_project.id, {candidate["project_id"] for candidate in candidates})
        self.assertIn(
            "Other-context history should remain evidence.",
            {row["note"] for row in context["recent_completed_sessions"]},
        )

    def test_cache_bucket_ignores_exact_clock_but_changes_with_note(self):
        request = self.client.get(reverse("jev_timer_recommendations")).wsgi_request
        candidates = build_jev_candidates(self.user, request)
        context = build_jev_context(self.user, request, candidates)
        first = jev_cache_key(self.user, request, candidates, context)
        changed = json.loads(json.dumps(context))
        changed["now"]["local_datetime"] = "2099-01-01T01:02:03+00:00"
        changed["now"]["local_time"] = "01:02:03"
        self.assertEqual(first, jev_cache_key(self.user, request, candidates, changed))
        changed["recent_completed_sessions"].append(
            {"id": 999, "project_id": self.active.id, "note": "new evidence"}
        )
        self.assertNotEqual(first, jev_cache_key(self.user, request, candidates, changed))
