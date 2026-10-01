"""Bounded Luna evidence validation; no provider requests."""
import json
from django.test import SimpleTestCase
from core.services.recommendation_state import RecommendationContextError, build_recommendation_state


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


class RecommendationStateTests(SimpleTestCase):
    def test_state_contains_rich_context_and_decision_rules(self):
        state = build_recommendation_state(_candidates(), _context())
        self.assertEqual(state["now"]["weekday"], "Saturday")
        self.assertEqual(state["active_context"]["name"], "Work")
        self.assertEqual(state["recent_completed_sessions"][0]["note"],
                         "The payload builder still needs a provider response fixture.")
        self.assertEqual(state["projects"][0]["description"], "A time-aware work tracker.")
        self.assertEqual(state["commitments"][0]["banked_credit"], 20)
        self.assertNotIn("questions", state)
        self.assertNotIn("model", state)
        self.assertNotIn("provider_limits", state["history_coverage"])
        self.assertNotIn("longest_question_byte_ceiling", state["history_coverage"])
        self.assertIn("banked credit", json.dumps(state))
        self.assertIn("Do not force catch-up", json.dumps(state))

    def test_payload_normalizes_ids_and_rejects_duplicate_ids(self):
        candidate = {
            "id": "  candidate  ",
            "project_id": "17",
            "project_name": "Autumn",
            "subprojects": [{"id": "31", "name": "Sub", "description": ""}],
            "commitment_ids": [" c1 "],
            "signals": [],
        }
        payload = build_recommendation_state([candidate], {})
        normalized = payload["candidates"][0]
        self.assertEqual(normalized["id"], "candidate")
        self.assertEqual(normalized["project_id"], "17")
        self.assertEqual(normalized["subprojects"][0]["id"], "31")
        self.assertEqual(normalized["commitment_ids"], ["c1"])

        with self.assertRaises(RecommendationContextError):
            build_recommendation_state([candidate, {**candidate, "id": "candidate"}], {})

    def test_oldest_continuity_history_is_trimmed_before_recent_notes(self):
        context = _context()
        context["older_latest_sessions"] = [
            {
                "id": "old-1",
                "project_id": 17,
                "note": "x" * 70_000,
            }
        ]

        payload = build_recommendation_state(_candidates(), context)

        self.assertEqual(
            payload["recent_completed_sessions"][0]["id"],
            "session-recent",
        )
        self.assertEqual(payload["older_latest_sessions"], [])
        self.assertEqual(
            payload["history_coverage"]["omitted_session_ids"], ["old-1"]
        )
        self.assertTrue(payload["history_coverage"]["truncated"])

    def test_oversized_core_metadata_fails_closed(self):
        context = _context()
        context["projects"] = [{"id": 17, "name": "Autumn", "description": "x" * 70_000}]

        with self.assertRaisesRegex(RecommendationContextError, "too large"):
            build_recommendation_state(_candidates(), context)

    def test_malformed_shapes_and_nonfinite_values_fail_as_service_errors(self):
        with self.assertRaises(RecommendationContextError):
            build_recommendation_state(_candidates(), {"history_coverage": []})
        with self.assertRaises(RecommendationContextError):
            build_recommendation_state(_candidates(), {"recent_completed_sessions": "oops"})
        with self.assertRaises(RecommendationContextError):
            build_recommendation_state([{**_candidates()[0], "project_id": object()}], {})
        with self.assertRaises(RecommendationContextError):
            build_recommendation_state(
                [{**_candidates()[0], "subprojects": [{"id": object(), "name": "x"}]}],
                {},
            )
        with self.assertRaises(RecommendationContextError):
            build_recommendation_state(
                [{**_candidates()[0], "commitment_ids": "commitment-1"}], {},
            )
        with self.assertRaises(RecommendationContextError):
            build_recommendation_state(
                _candidates(), {"projects": [{"id": 1, "hours": float("nan")}]}
            )
