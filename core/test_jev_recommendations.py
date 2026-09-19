"""Provider-boundary coverage for rich Jev timer recommendations.

These tests exercise payload construction and the installed TypeSafe SDK's
response models without making a network request. The view owns Django ORM
assembly; this module verifies that the provider boundary is bounded,
fail-closed, and explicit about its independent score questions.
"""

import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from typesafe_sdk import ScoreAnswer, SystemOneResponse

from core.services.jev_recommendations import (
    JEV_MODEL,
    JevRecommendationError,
    build_jev_payload,
    rank_timer_candidates,
    recommend_timer_candidates,
)


def _candidates():
    return [
        {
            "id": "project:17:subprojects:31",
            "project_id": 17,
            "project_name": "Autumn",
            "subprojects": [
                {
                    "id": 31,
                    "name": "Timer suggestions",
                    "description": "Improve the recommendation surface.",
                }
            ],
            "context_reason": "Recent notes contain an unfinished implementation step.",
            "commitment_ids": ["commitment-1"],
            "signals": [
                {
                    "kind": "recent",
                    "detail": "Worked on yesterday with an unfinished step",
                    "metric": 2,
                },
                {
                    "kind": "commitment",
                    "detail": "30 minutes remain this period",
                    "metric": "30 min",
                },
            ],
        },
        {
            "id": "project:22:subprojects:",
            "project_id": 22,
            "project_name": "Czech",
            "subprojects": [],
            "context_reason": "A reasonable practice option.",
            "commitment_ids": [],
            "signals": [
                {
                    "kind": "usual_time",
                    "detail": "Often practiced in this weekday/time window",
                    "metric": 0.8,
                }
            ],
        },
    ]


def _context():
    return {
        "now": {
            "local_datetime": "2026-09-19T18:00:00+02:00",
            "local_date": "2026-09-19",
            "local_time": "18:00",
            "weekday": "Saturday",
            "timezone": "Europe/Prague",
        },
        "active_context": {"id": 4, "name": "Work", "mode": "selected"},
        "history_coverage": {
            "requested_days": 30,
            "recent_sessions_before_budget": 1,
            "older_latest_sessions_before_budget": 1,
        },
        "projects": [
            {
                "id": 17,
                "name": "Autumn",
                "status": "active",
                "description": "A time-aware work tracker.",
                "context": "Work",
                "tags": ["software"],
                "subprojects": [
                    {
                        "id": 31,
                        "name": "Timer suggestions",
                        "description": "Make the next action easier to choose.",
                    }
                ],
            }
        ],
        "commitments": [
            {
                "id": "commitment-1",
                "target": 120,
                "actual": 90,
                "banked_credit": 20,
                "covered_actual": 110,
                "remaining": 10,
                "fulfilled": False,
                "period_start": "2026-09-14",
                "period_end": "2026-09-20",
                "eligible_candidate_ids": ["project:17:subprojects:31"],
            }
        ],
        "recent_completed_sessions": [
            {
                "id": "session-recent",
                "project_id": 17,
                "project_name": "Autumn",
                "start": "2026-09-18T16:00:00+02:00",
                "end": "2026-09-18T16:45:00+02:00",
                "duration_seconds": 2700,
                "note": "The payload builder still needs a provider response fixture.",
                "subproject_ids": [31],
            }
        ],
        "older_latest_sessions": [
            {
                "id": "session-older",
                "project_id": 17,
                "start": "2026-08-20T16:00:00+02:00",
                "end": "2026-08-20T16:30:00+02:00",
                "duration_seconds": 1800,
                "note": "An older note.",
            }
        ],
        "running_timers": [
            {
                "id": "session-running",
                "project_id": 22,
                "project_name": "Czech",
                "elapsed_seconds": 900,
            }
        ],
        "candidate_coverage": {
            "project:17:subprojects:31": {"eligible": True},
            "project:22:subprojects:": {"eligible": True},
        },
    }


def _score_answer(score, confidence):
    return ScoreAnswer(
        type="score",
        score=score,
        confidence=confidence,
        legend={
            0: "against",
            1: "little evidence",
            2: "reasonable",
            3: "strong",
            4: "especially timely",
        },
        probabilities={0: 0.0, 1: 0.1, 2: 0.2, 3: 0.3, 4: 0.4},
    )


def _sdk_response(*answers):
    return SystemOneResponse(
        model=JEV_MODEL,
        usage={"input_tokens": 1, "output_tokens": 1},
        answers={
            f"candidate_{index}": answer for index, answer in enumerate(answers)
        },
    )


class JevPayloadTests(IsolatedAsyncioTestCase):
    def test_payload_contains_rich_context_and_independent_id_questions(self):
        payload = build_jev_payload(_candidates(), _context())

        self.assertEqual(payload["model"], JEV_MODEL)
        self.assertEqual(payload["state"]["now"]["weekday"], "Saturday")
        self.assertEqual(payload["state"]["active_context"]["name"], "Work")
        self.assertEqual(
            payload["state"]["recent_completed_sessions"][0]["note"],
            "The payload builder still needs a provider response fixture.",
        )
        self.assertEqual(
            payload["state"]["projects"][0]["description"],
            "A time-aware work tracker.",
        )
        self.assertEqual(payload["state"]["commitments"][0]["banked_credit"], 20)

        self.assertEqual(set(payload["questions"]), {"candidate_0", "candidate_1"})
        first = payload["questions"]["candidate_0"]
        second = payload["questions"]["candidate_1"]
        self.assertEqual(first["type"], "score")
        self.assertIn("project:17:subprojects:31", first["instructions"])
        self.assertIn("project:22:subprojects:", second["instructions"])
        self.assertNotIn("Autumn", first["instructions"])
        self.assertNotIn("Czech", second["instructions"])
        self.assertNotIn("next_timer_candidate", payload["questions"])
        self.assertTrue(first["criteria"][0].startswith("0 "))
        self.assertTrue(first["criteria"][4].startswith("4 "))
        self.assertIn("banked credit", json.dumps(payload))
        self.assertIn("Do not force catch-up", json.dumps(payload))

    def test_payload_normalizes_ids_and_rejects_duplicate_ids(self):
        candidate = {
            "id": "  candidate  ",
            "project_id": "17",
            "project_name": "Autumn",
            "subprojects": [{"id": "31", "name": "Sub", "description": ""}],
            "commitment_ids": [" c1 "],
            "signals": [],
        }
        payload = build_jev_payload([candidate], {})
        normalized = payload["state"]["candidates"][0]
        self.assertEqual(normalized["id"], "candidate")
        self.assertEqual(normalized["project_id"], "17")
        self.assertEqual(normalized["subprojects"][0]["id"], "31")
        self.assertEqual(normalized["commitment_ids"], ["c1"])

        with self.assertRaises(JevRecommendationError):
            build_jev_payload([candidate, {**candidate, "id": "candidate"}], {})

    def test_oldest_continuity_history_is_trimmed_before_recent_notes(self):
        context = _context()
        context["older_latest_sessions"] = [
            {
                "id": "old-1",
                "project_id": 17,
                "note": "x" * 70_000,
            }
        ]

        payload = build_jev_payload(_candidates(), context)

        self.assertEqual(
            payload["state"]["recent_completed_sessions"][0]["id"],
            "session-recent",
        )
        self.assertEqual(payload["state"]["older_latest_sessions"], [])
        self.assertEqual(
            payload["state"]["history_coverage"]["omitted_session_ids"], ["old-1"]
        )
        self.assertTrue(payload["state"]["history_coverage"]["truncated"])

    def test_oversized_core_metadata_fails_closed(self):
        context = _context()
        context["projects"] = [{"id": 17, "name": "Autumn", "description": "x" * 70_000}]

        with self.assertRaisesRegex(JevRecommendationError, "too large"):
            build_jev_payload(_candidates(), context)

    def test_malformed_shapes_and_nonfinite_values_fail_as_service_errors(self):
        with self.assertRaises(JevRecommendationError):
            build_jev_payload(_candidates(), {"history_coverage": []})
        with self.assertRaises(JevRecommendationError):
            build_jev_payload(_candidates(), {"recent_completed_sessions": "oops"})
        with self.assertRaises(JevRecommendationError):
            build_jev_payload([{**_candidates()[0], "project_id": object()}], {})
        with self.assertRaises(JevRecommendationError):
            build_jev_payload(
                [{**_candidates()[0], "subprojects": [{"id": object(), "name": "x"}]}],
                {},
            )
        with self.assertRaises(JevRecommendationError):
            build_jev_payload(
                [{**_candidates()[0], "commitment_ids": "commitment-1"}], {},
            )
        with self.assertRaises(JevRecommendationError):
            build_jev_payload(
                _candidates(), {"projects": [{"id": 1, "hours": float("nan")}]}
            )


class JevRecommendationTests(IsolatedAsyncioTestCase):
    @patch("core.services.jev_recommendations.recommend_timer_candidates")
    def test_sync_adapter_supports_regular_django_views(self, recommend):
        recommend.side_effect = AsyncMock(return_value={"ordered_candidate_ids": []})

        result = rank_timer_candidates("profile-secret", _candidates(), _context())

        self.assertEqual(result, {"ordered_candidate_ids": []})
        recommend.assert_called_once()

    @patch("core.services.jev_recommendations.AsyncTypeSafeClient")
    async def test_rank_uses_real_sdk_response_and_no_retries(self, client_type):
        response = _sdk_response(
            _score_answer(2.5, 0.10),
            _score_answer(3.25, 0.0),
        )
        client = AsyncMock()
        client.system_one.return_value = response
        client_type.return_value.__aenter__.return_value = client

        result = await recommend_timer_candidates(
            "profile-secret", _candidates(), _context()
        )

        self.assertEqual(
            result["ordered_candidate_ids"],
            ["project:22:subprojects:", "project:17:subprojects:31"],
        )
        self.assertEqual(result["recommendations"][0]["score"], 3.25)
        self.assertEqual(result["recommendations"][0]["confidence"], 0.0)
        self.assertEqual(result["recommendations"][1]["score"], 2.5)
        self.assertEqual(result["model"], JEV_MODEL)
        init_kwargs = client_type.call_args.kwargs
        self.assertEqual(init_kwargs["api_key"], "profile-secret")
        self.assertEqual(init_kwargs["model"], JEV_MODEL)
        self.assertEqual(init_kwargs["retry"].max_retries, 0)
        call_kwargs = client.system_one.call_args.kwargs
        self.assertEqual(call_kwargs["model"], JEV_MODEL)
        self.assertEqual(call_kwargs["retry"].max_retries, 0)
        self.assertEqual(call_kwargs["timeout"], 3.0)
        self.assertNotIn("profile-secret", repr(call_kwargs["state"]))

    @patch("core.services.jev_recommendations.AsyncTypeSafeClient")
    async def test_fractional_scores_are_sorted_and_scores_below_threshold_hidden(
        self, client_type
    ):
        client = AsyncMock()
        client.system_one.return_value = _sdk_response(
            _score_answer(1.99, 0.99),
            _score_answer(2.0, 0.01),
        )
        client_type.return_value.__aenter__.return_value = client

        result = await recommend_timer_candidates(
            "profile-secret", _candidates(), _context()
        )

        self.assertEqual(result["ordered_candidate_ids"], ["project:22:subprojects:"])
        self.assertEqual(len(result["scores"]), 2)
        self.assertEqual(result["scores"][0]["confidence"], 0.99)

    @patch("core.services.jev_recommendations.AsyncTypeSafeClient")
    async def test_missing_or_invalid_score_answers_fail_closed(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client

        client.system_one.return_value = _sdk_response(_score_answer(2.0, 0.5))
        with self.assertRaisesRegex(JevRecommendationError, "omitted"):
            await recommend_timer_candidates(
                "profile-secret", _candidates(), _context()
            )

        client.system_one.return_value = _sdk_response(
            _score_answer(5.0, 0.5), _score_answer(2.0, 0.5)
        )
        with self.assertRaisesRegex(JevRecommendationError, "invalid score"):
            await recommend_timer_candidates(
                "profile-secret", _candidates(), _context()
            )

    @patch("core.services.jev_recommendations.AsyncTypeSafeClient")
    async def test_provider_errors_are_secret_neutral_and_no_retry(self, client_type):
        client_type.side_effect = RuntimeError("request failed for profile-secret")

        with self.assertRaises(JevRecommendationError) as raised:
            await recommend_timer_candidates(
                "profile-secret", _candidates(), _context()
            )

        self.assertNotIn("profile-secret", str(raised.exception))
