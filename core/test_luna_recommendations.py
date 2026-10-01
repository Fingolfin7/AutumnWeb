import json
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from django.core.cache import cache
from core.models import Projects, RecommendationCache, Sessions, SubProjects

from core.services.luna_recommendations import rank_luna_candidates
from core import test_timer_recommendation_context as context_tests


class LunaServiceTests(SimpleTestCase):
    def call(self, rows, *, streamed=False, status="completed", effort="xhigh"):
        state = {"candidates": [{"id": "no_activity"}], "recent_completed_sessions": []}
        with mock.patch("core.services.luna_recommendations.build_recommendation_state", return_value=state), mock.patch(
            "core.services.luna_recommendations.OpenAI"
        ) as client:
            create = client.return_value.__enter__.return_value.responses.create
            text = json.dumps({"recommendations": rows})
            completed = SimpleNamespace(status=status, output_text="" if streamed else text)
            events = ([SimpleNamespace(type="response.output_text.delta", delta=text[:20]),
                       SimpleNamespace(type="response.output_text.delta", delta=text[20:])] if streamed else [])
            events.append(SimpleNamespace(type="response." + status, response=completed))
            create.return_value.__enter__.return_value = create.return_value
            create.return_value.__iter__.return_value = iter(events)
            result = rank_luna_candidates({"openai_chatgpt": "test-key"}, [], {}, effort=effort)
            request = create.call_args.kwargs
            self.assertEqual(client.call_args.kwargs["timeout"], 120.0)
            self.assertEqual(request["reasoning"], {"effort": effort})
            self.assertEqual(request["model"], "gpt-6-luna")
            self.assertFalse(request["store"])
            self.assertTrue(request["stream"])
            self.assertEqual(json.loads(request["input"][0]["content"][0]["text"]), state)
            return result

    def test_high_effort_is_sent_and_recorded_without_changing_evidence(self):
        from core.services.recommendation_usage import collect_attempts
        with collect_attempts() as attempts:
            self.assertEqual(self.call([], effort="high"), {"recommendations": []})
        self.assertEqual(attempts[0]["effort"], "high")
        self.assertTrue(attempts[0]["success"])

    def test_invalid_effort_never_calls_provider(self):
        with mock.patch("core.services.luna_recommendations.OpenAI") as client:
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                rank_luna_candidates({"openai_chatgpt": "token"}, [], {}, effort="invalid")
            client.assert_not_called()

    def test_oauth_only_uses_streamed_text_when_terminal_output_is_empty(self):
        row = {"candidate_id": "no_activity", "score": 3, "reason": "Rest.", "next_step": ""}
        self.assertEqual(self.call([row], streamed=True)["recommendations"], [row])

    def test_incomplete_stream_is_never_accepted_even_with_valid_json(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.call([], streamed=True, status="incomplete")

    def test_oauth_allows_slow_xhigh_completion_but_remains_bounded(self):
        with mock.patch("core.services.luna_recommendations.time.monotonic", side_effect=[0, 75]):
            self.assertEqual(self.call([]), {"recommendations": []})
        with mock.patch("core.services.luna_recommendations.time.monotonic", side_effect=[0, 121]):
            with self.assertRaises(TimeoutError):
                self.call([])

    def test_nothing_is_a_valid_result_and_low_scores_are_filtered(self):
        row = {"candidate_id": "no_activity", "score": 3.2, "reason": "Covered commitments.", "next_step": ""}
        self.assertEqual(self.call([row])["recommendations"], [row])
        self.assertEqual(self.call([{**row, "score": 1.9}])["recommendations"], [])

    def test_unknown_and_duplicate_ids_are_rejected(self):
        row = {"candidate_id": "no_activity", "score": 3, "reason": "", "next_step": ""}
        for rows in ([{**row, "candidate_id": "other-account"}], [row, row]):
            with self.assertRaises(ValueError):
                self.call(rows)

    def test_oauth_first_then_api_fallback(self):
        with mock.patch("core.services.luna_recommendations._rank_once", side_effect=[RuntimeError("unavailable"), {"recommendations": []}]) as call:
            self.assertEqual(rank_luna_candidates({"openai_chatgpt": "token", "openai": "key"}, [], {}), {"recommendations": []})
            self.assertEqual(call.call_args_list, [mock.call("token", [], {}, oauth=True, effort="xhigh"), mock.call("key", [], {}, oauth=False, effort="xhigh")])

    def test_successful_oauth_does_not_use_api_key(self):
        with mock.patch("core.services.luna_recommendations._rank_once", return_value={"recommendations": []}) as call:
            rank_luna_candidates({"openai_chatgpt": "token", "openai": "key"}, [], {})
            call.assert_called_once_with("token", [], {}, oauth=True, effort="xhigh")


class LunaViewTests(TestCase):
    setUp = context_tests.TimerRecommendationContextTests.setUp
    def _enable_key(self):
        return mock.patch("users.codex_auth.get_profile_access_token", return_value="oauth-test-token")

    def test_timer_page_is_luna_only_with_saved_effort_and_collapsed_fallbacks(self):
        self.user.profile.luna_recommendation_effort = "high"
        self.user.profile.save(update_fields=["luna_recommendation_effort"])
        response = self.client.get(reverse("timers"))
        self.assertContains(response, 'data-luna-url="')
        self.assertContains(response, 'value="high" selected')
        self.assertContains(response, "luna_timer_recommendations.js")
        self.assertNotContains(response, "jev")
        self.assertNotContains(response, "recommendation-comparison")
        self.assertEqual(self.client.get("/timers/jev-recommendations/").status_code, 404)

    def test_saved_effort_invalidates_cache_and_is_used_for_generation(self):
        with self._enable_key(), mock.patch("core.services.luna_recommendations.rank_luna_candidates", return_value={"recommendations": []}) as ranker:
            self.client.get(reverse("luna_timer_recommendations"))
            self.assertEqual(ranker.call_args.kwargs["effort"], "xhigh")
            response = self.client.post(reverse("refresh_recommendations"), {"luna_effort": "high"})
            self.assertRedirects(response, reverse("timers"))
            self.user.profile.refresh_from_db()
            self.assertEqual(self.user.profile.luna_recommendation_effort, "high")
            self.client.get(reverse("luna_timer_recommendations"))
            self.client.get(reverse("luna_timer_recommendations"))
            self.assertEqual(ranker.call_count, 2)
            self.assertEqual(ranker.call_args.kwargs["effort"], "high")

    def test_effort_change_does_not_expose_old_inflight_result(self):
        from core.models import RecommendationCache
        from django.utils import timezone
        from datetime import timedelta
        RecommendationCache.objects.create(user=self.user, provider="luna", scope="all:all",
            fingerprint="old-effort", result=None, lease_until=timezone.now() + timedelta(minutes=1))
        self.client.post(reverse("refresh_recommendations"), {"luna_effort": "high"})
        with self._enable_key(), mock.patch("core.services.luna_recommendations.rank_luna_candidates", return_value={"recommendations": []}) as ranker:
            self.assertEqual(self.client.get(reverse("luna_timer_recommendations")).status_code, 202)
            ranker.assert_not_called()
            RecommendationCache.objects.update(result={"recommendations": [{"candidate_id": "no_activity", "score": 4, "reason": "OLD_EFFORT_REPLY", "next_step": ""}]}, lease_until=timezone.now())
            response = self.client.get(reverse("luna_timer_recommendations"))
            self.assertNotContains(response, "OLD_EFFORT_REPLY")
            self.assertEqual(ranker.call_args.kwargs["effort"], "high")

    def test_effort_update_is_authenticated_validated_and_csrf_protected(self):
        from django.test import Client
        self.assertEqual(self.client.get(reverse("refresh_recommendations")).status_code, 405)
        self.assertEqual(self.client.post(reverse("refresh_recommendations"), {"luna_effort": "bogus"}).status_code, 400)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.luna_recommendation_effort, "xhigh")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse("refresh_recommendations"), {"luna_effort": "high"}).status_code, 403)
        self.user.profile.ai_features_enabled = False
        self.user.profile.save(update_fields=["ai_features_enabled"])
        self.assertEqual(self.client.post(reverse("refresh_recommendations"), {"luna_effort": "high"}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.post(reverse("refresh_recommendations"), {"luna_effort": "high"}).status_code, 302)

    def test_luna_has_independent_cache_and_escaped_explanations(self):
        with self._enable_key() as key, mock.patch(
            "core.services.luna_recommendations.rank_luna_candidates",
            return_value={"recommendations": [{"candidate_id": "no_activity", "score": 3.75,
                                               "reason": "<script>bad</script>", "next_step": "Leave time open."}]},
        ) as ranker:
            for _ in range(2):
                response = self.client.get(reverse("luna_timer_recommendations"))
                self.assertContains(response, "Luna Recommends")
                self.assertContains(response, "Luna score 3.75")
                self.assertContains(response, "&lt;script&gt;")
                self.assertNotContains(response, "<form")
            ranker.assert_called_once()
            self.assertEqual(key.call_count, 2)

    def test_luna_missing_key_and_provider_failure_are_nonfatal(self):
        with mock.patch.object(type(self.user.profile), "get_api_key", return_value=None), mock.patch(
            "core.services.luna_recommendations.rank_luna_candidates"
        ) as ranker:
            response = self.client.get(reverse("luna_timer_recommendations"))
            ranker.assert_not_called()
            self.assertContains(response, "connect ChatGPT in Profile")
        with self._enable_key(), mock.patch(
            "core.services.luna_recommendations.rank_luna_candidates", side_effect=RuntimeError("secret")
        ):
            response = self.client.get(reverse("luna_timer_recommendations"))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "secret")

    def test_luna_requires_authentication(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("luna_timer_recommendations")).status_code, 302)

    def test_inflight_returns_retryable_response(self):
        from core.services.recommendation_cache import RecommendationPending
        with self._enable_key(), mock.patch("core.services.recommendation_cache.get_or_generate", side_effect=RecommendationPending):
            response = self.client.get(reverse("luna_timer_recommendations"))
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response["Retry-After"], "5")

    def test_project_description_edit_invalidates_persistent_result(self):
        with self._enable_key(), mock.patch("core.services.luna_recommendations.rank_luna_candidates", return_value={"recommendations": []}) as ranker:
            self.client.get(reverse("luna_timer_recommendations"))
            self.active.description = "A materially different project goal"
            self.active.save(update_fields=["description"])
            self.client.get(reverse("luna_timer_recommendations"))
            self.assertEqual(ranker.call_count, 2)

    def test_habit_label_clock_change_does_not_regenerate_advice(self):
        from datetime import timedelta
        from django.utils import timezone
        from core.models import Sessions
        now = timezone.now().replace(hour=9, minute=1, second=0, microsecond=0)
        Sessions.objects.create(user=self.user, project=self.active,
                                start_time=now - timedelta(days=7),
                                end_time=now - timedelta(days=7) + timedelta(minutes=20))
        with self._enable_key(), mock.patch("core.services.luna_recommendations.rank_luna_candidates", return_value={"recommendations": []}) as ranker:
            for instant in (now, now + timedelta(minutes=5)):
                with mock.patch("django.utils.timezone.now", return_value=instant):
                    self.client.get(reverse("luna_timer_recommendations"))
            self.assertEqual(ranker.call_count, 1)


    def test_nothing_option_is_scored_and_has_no_timer_action_even_without_projects(self):
        Projects.objects.filter(user=self.user).update(status="complete")

        def ranker(**kwargs):
            self.assertEqual([row["id"] for row in kwargs["candidates"]], ["no_activity"])
            return {"recommendations": [{"candidate_id": "no_activity", "score": 3.75}]}

        with self._enable_key(), mock.patch(
            "core.services.luna_recommendations.rank_luna_candidates", side_effect=ranker
        ):
            response = self.client.get(reverse("luna_timer_recommendations"))
        self.assertContains(response, "Start nothing for now")
        self.assertContains(response, 'aria-label="Luna score 3.75"')
        self.assertNotContains(response, '<form')
        self.assertFalse(Sessions.objects.filter(user=self.user).exists())


    def test_candidates_are_active_only_deduplicated_and_exclude_running_projects(self):
        available = Projects.objects.create(
            user=self.user,
            name="Available project",
            context=self.context,
            status="active",
        )
        # This timer must remove the active project from Luna candidates even
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
            "core.services.luna_recommendations.rank_luna_candidates", side_effect=ranker
        ):
            response = self.client.get(reverse("luna_timer_recommendations"))

        self.assertEqual(response.status_code, 200)
        candidates = self.ranker_payload["candidates"]
        self.assertContains(response, 'class="suggest-score"')
        self.assertContains(response, 'aria-label="Luna score 3.50"')
        with self._enable_key(), mock.patch(
            "core.services.luna_recommendations.rank_luna_candidates"
        ) as cached_ranker:
            cached_response = self.client.get(reverse("luna_timer_recommendations"))
        cached_ranker.assert_not_called()
        self.assertContains(cached_response, 'aria-label="Luna score 3.50"')
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


    def test_pending_retry_skips_rich_context_until_lease_expires(self):
        lease = RecommendationCache.objects.create(
            user=self.user,
            provider="luna",
            scope="all:all",
            lease_until=timezone.now() + timedelta(minutes=2),
        )
        with self._enable_key(), mock.patch(
            "core.views.timers.build_recommendation_candidates"
        ) as candidates:
            response = self.client.get(reverse("luna_timer_recommendations"))
        self.assertEqual(response.status_code, 202)
        candidates.assert_not_called()

        lease.lease_until = timezone.now() - timedelta(seconds=1)
        lease.save(update_fields=["lease_until"])
        with self._enable_key(), mock.patch(
            "core.services.luna_recommendations.rank_luna_candidates",
            return_value={"recommendations": []},
        ) as ranker:
            self.client.get(reverse("luna_timer_recommendations"))
        ranker.assert_called_once()


    def test_duplicate_timer_combo_aggregates_all_local_signals(self):
        deterministic = {
            "commitments": [
                {
                    "kind": "commitment",
                    "detail": "30 min remaining",
                    "recommendation_detail": "30 min remaining with 6 days remaining",
                    "metric": "30%",
                    "project": self.active,
                    "subprojects": [],
                }
            ],
            "habits": [
                {
                    "kind": "habit",
                    "detail": "2 matching sessions",
                    "recommendation_detail": "2 matching sessions within the same weekday +/-2-hour window",
                    "metric": "2x",
                    "project": self.active,
                    "subprojects": [],
                }
            ],
            "recent": [
                {
                    "kind": "recent",
                    "detail": "Last used today",
                    "recommendation_detail": "Used today",
                    "metric": "recent",
                    "project": self.active,
                    "subprojects": [],
                }
            ],
        }

        with self._enable_key(), mock.patch(
            "core.views.timers.build_timer_suggestions", return_value=deterministic
        ), mock.patch(
            "core.services.luna_recommendations.rank_luna_candidates",
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
            response = self.client.get(reverse("luna_timer_recommendations"))

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
        self.assertEqual(candidate["reason"], "30 min remaining with 6 days remaining")


    def test_ranked_result_renders_top_three_and_keeps_deterministic_reason(self):
        other = Projects.objects.create(
            user=self.user, name="Another active", context=self.context, status="active"
        )

        with self._enable_key(), mock.patch(
            "core.services.luna_recommendations.rank_luna_candidates",
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
            response = self.client.get(reverse("luna_timer_recommendations"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Luna Recommends")
        self.assertContains(response, "Active project")
        self.assertContains(response, "Another active")
        ranker.assert_called_once()


    def test_timer_page_keeps_luna_mount_and_collapsed_groups(self):
        Sessions.objects.create(
            user=self.user,
            project=self.active,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
        )
        response = self.client.get(reverse("timers"))
        self.assertContains(response, 'data-luna-url="')
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

        with self._enable_key(), mock.patch("core.services.luna_recommendations.rank_luna_candidates", side_effect=ranker):
            response = self.client.get(reverse("luna_timer_recommendations"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<form')
