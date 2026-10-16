import json
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from datetime import timedelta
from core.models import Projects, Sessions

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


    def test_invalid_effort_never_calls_provider(self):
        with mock.patch("core.services.luna_recommendations.OpenAI") as client:
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                rank_luna_candidates({"openai_chatgpt": "token"}, [], {}, effort="invalid")
            client.assert_not_called()


    def test_incomplete_stream_is_never_accepted_even_with_valid_json(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.call([], streamed=True, status="incomplete")


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


LUNA = "/api/v2/recommendations/luna/"
LUNA_REFRESH = "/api/v2/recommendations/luna/refresh/"


class LunaApiTests(TestCase):
    """Luna recommendations through /api/v2/recommendations/luna/ (and /refresh/).

    The React Timers and Home pages read these; the old Timers page tests of the
    same behaviour were retired with its template.
    """

    setUp = context_tests.TimerRecommendationContextTests.setUp

    def _enable_key(self):
        return mock.patch("users.codex_auth.get_profile_access_token", return_value="oauth-test-token")

    def _luna(self):
        return self.client.get(LUNA)

    def _refresh(self, body=None, client=None):
        return (client or self.client).post(
            LUNA_REFRESH, json.dumps(body or {}), content_type="application/json"
        )


    def test_effort_update_is_authenticated_validated_and_csrf_protected(self):
        from django.test import Client
        self.assertEqual(self.client.get(LUNA_REFRESH).status_code, 405)
        self.assertEqual(self._refresh({"luna_effort": "bogus"}).status_code, 400)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.luna_recommendation_effort, "xhigh")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(self._refresh({"luna_effort": "high"}, client=csrf_client).status_code, 403)
        self.user.profile.ai_features_enabled = False
        self.user.profile.save(update_fields=["ai_features_enabled"])
        self.assertEqual(self._refresh({"luna_effort": "high"}).status_code, 403)
        self.client.logout()
        self.assertIn(self._refresh({"luna_effort": "high"}).status_code, (401, 403))


    def test_luna_missing_key_and_provider_failure_are_nonfatal(self):
        with mock.patch.object(type(self.user.profile), "get_api_key", return_value=None), mock.patch(
            "core.services.luna_recommendations.rank_luna_candidates"
        ) as ranker:
            response = self._luna()
            ranker.assert_not_called()
            self.assertEqual(response.json()["suggestions"], [])
            self.assertIn("connect ChatGPT in Profile", response.json()["advice_status"])
        with self._enable_key(), mock.patch(
            "core.services.luna_recommendations.rank_luna_candidates", side_effect=RuntimeError("secret")
        ):
            response = self._luna()
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("secret", response.content.decode())
            self.assertEqual(response.json()["suggestions"], [])

    def test_luna_requires_authentication(self):
        self.client.logout()
        self.assertIn(self._luna().status_code, (401, 403))


    def test_project_description_edit_invalidates_persistent_result(self):
        with self._enable_key(), mock.patch("core.services.luna_recommendations.rank_luna_candidates", return_value={"recommendations": []}) as ranker:
            self._luna()
            self.active.description = "A materially different project goal"
            self.active.save(update_fields=["description"])
            self._luna()
            self.assertEqual(ranker.call_count, 2)


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
            response = self._luna()

        self.assertEqual(response.status_code, 200)
        candidates = self.ranker_payload["candidates"]
        scores = [row["recommendation_score"] for row in response.json()["suggestions"]]
        self.assertTrue(scores)
        self.assertEqual(set(scores), {3.5})
        with self._enable_key(), mock.patch(
            "core.services.luna_recommendations.rank_luna_candidates"
        ) as cached_ranker:
            cached_response = self._luna()
        cached_ranker.assert_not_called()
        self.assertEqual(
            [row["recommendation_score"] for row in cached_response.json()["suggestions"]], scores
        )
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


    def test_ranked_result_lists_the_top_three_and_keeps_deterministic_reason(self):
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
            response = self._luna()

        self.assertEqual(response.status_code, 200)
        rows = response.json()["suggestions"]
        self.assertLessEqual(len(rows), 3)
        self.assertEqual(
            [row["project"]["name"] for row in rows[:2]], ["Active project", "Another active"]
        )
        self.assertEqual([row["recommendation_score"] for row in rows[:2]], [4.0, 3.0])
        ranker.assert_called_once()
