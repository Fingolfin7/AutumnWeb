"""Independent integration checks for domain data crossing the Recommendation boundary."""

import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.utils import timezone
from freezegun import freeze_time

from core.models import Commitment, Projects, Sessions, SubProjects
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

    def test_frequent_same_combo_does_not_overflow_signal_limit(self):
        for index in range(20):
            end = timezone.now() - timedelta(days=1, minutes=index * 30)
            Sessions.objects.create(
                user=self.user, project=self.project,
                start_time=end - timedelta(minutes=20), end_time=end,
                note=f"Complete evidence {index}",
            )

        state = self.payload()

        self.assertEqual(len(state["recent_completed_sessions"]), 20)
        self.assertEqual(len(state["candidates"]), 2)
        self.assertEqual(state["candidates"][-1]["id"], "no_activity")
        self.assertIn("Complete evidence 0", json.dumps(state))

    def test_banked_fulfilled_subproject_with_no_history_stays_eligible(self):
        sub = SubProjects.objects.create(
            user=self.user, parent_project=self.project,
            name="No-history subproject", description="A specific goal",
        )
        commitment = Commitment.objects.create(
            user=self.user, aggregation_type="subproject", subproject=sub,
            commitment_type="time", period="weekly", target=30,
            banking_enabled=True, balance=60, start_date=timezone.localdate(),
        )

        state = self.payload()

        row = next(row for row in state["commitments"] if row["id"] == commitment.id)
        self.assertEqual(row["actual"], 0)
        self.assertEqual(row["banking"]["banked_credit"], 60)
        self.assertTrue(row["banking"]["covered"])
        self.assertEqual(row["banking"]["remaining"], 0)
        self.assertTrue(row["eligible_candidate_ids"])
        candidate = next(
            row for row in state["candidates"]
            if row["id"] in state["commitments"][0]["eligible_candidate_ids"]
        )
        self.assertIn(sub.id, [item["id"] for item in candidate["subprojects"]])

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

    def test_history_window_and_older_continuity_are_distinct(self):
        boundary = timezone.now() - timedelta(days=30)
        recent = Sessions.objects.create(
            user=self.user, project=self.project,
            start_time=boundary - timedelta(minutes=10), end_time=boundary,
            note="Boundary session",
        )
        dormant = Projects.objects.create(user=self.user, name="Longer-term work")
        older = Sessions.objects.create(
            user=self.user, project=dormant,
            start_time=boundary - timedelta(days=2, minutes=10),
            end_time=boundary - timedelta(days=2), note="Older continuity",
        )

        state = self.payload()

        self.assertEqual([row["id"] for row in state["recent_completed_sessions"]], [recent.id])
        self.assertEqual([row["id"] for row in state["older_latest_sessions"]], [older.id])
        self.assertEqual(state["history_coverage"]["requested_days"], 30)

    def test_older_continuity_uses_latest_session_per_project_with_id_tiebreak(self):
        dormant = Projects.objects.create(user=self.user, name="Dormant")
        other = Projects.objects.create(user=self.user, name="Also dormant")
        end = timezone.now() - timedelta(days=45)
        Sessions.objects.create(
            user=self.user, project=dormant,
            start_time=end - timedelta(days=1, minutes=40),
            end_time=end - timedelta(days=1), note="Too old",
        )
        Sessions.objects.create(
            user=self.user, project=dormant,
            start_time=end - timedelta(minutes=30), end_time=end,
            note="Same end, lower ID",
        )
        latest = Sessions.objects.create(
            user=self.user, project=dormant,
            start_time=end - timedelta(minutes=20), end_time=end,
            note="Same end, higher ID",
        )
        other_latest = Sessions.objects.create(
            user=self.user, project=other,
            start_time=end - timedelta(days=2, minutes=20),
            end_time=end - timedelta(days=2), note="Other project",
        )

        rows = self.payload()["older_latest_sessions"]
        self.assertEqual([row["id"] for row in rows], [latest.id, other_latest.id])
        self.assertEqual([row["note"] for row in rows], ["Same end, higher ID", "Other project"])
