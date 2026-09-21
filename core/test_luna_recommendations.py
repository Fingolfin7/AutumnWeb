import json
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.services.luna_recommendations import rank_luna_candidates
from core import test_jev_timer_recommendations as jev_tests


class LunaServiceTests(SimpleTestCase):
    def call(self, rows, *, streamed=False, status="completed"):
        state = {"candidates": [{"id": "no_activity"}], "recent_completed_sessions": []}
        with mock.patch("core.services.luna_recommendations.build_jev_payload", return_value={"state": state}), mock.patch(
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
            result = rank_luna_candidates({"openai_chatgpt": "test-key"}, [], {})
            request = create.call_args.kwargs
            self.assertEqual(client.call_args.kwargs["timeout"], 120.0)
            self.assertEqual(request["reasoning"], {"effort": "xhigh"})
            self.assertEqual(request["model"], "gpt-5.6-luna")
            self.assertFalse(request["store"])
            self.assertTrue(request["stream"])
            self.assertEqual(json.loads(request["input"][0]["content"][0]["text"]), state)
            return result

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
            self.assertEqual(call.call_args_list, [mock.call("token", [], {}, oauth=True), mock.call("key", [], {}, oauth=False)])

    def test_successful_oauth_does_not_use_api_key(self):
        with mock.patch("core.services.luna_recommendations._rank_once", return_value={"recommendations": []}) as call:
            rank_luna_candidates({"openai_chatgpt": "token", "openai": "key"}, [], {})
            call.assert_called_once_with("token", [], {}, oauth=True)


class LunaViewTests(TestCase):
    setUp = jev_tests.JevTimerRecommendationTests.setUp
    def _enable_key(self):
        return mock.patch("users.codex_auth.get_profile_access_token", return_value="oauth-test-token")

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
