"""One Sessions search for API v2 (which the React Sessions page uses) and MCP.

Regression for a paraphrase search ("dizzy during leg curls"): two sessions
describe it without the word, and a Related section showing only the five
most similar matches left the one ranked seventh (#5580, a long workout log
where the relevant sentence is a small part) out of reach while the API listed
all nine. Every interface now takes the same ranked list from
core.search.rank_sessions, and pages through it by offset.

Fictional stand-in notes keep the real ids and the production similarity
order; the fake model returns a chosen similarity to the query per note.
"""

import json
import math
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application

from core.models import MCPGrant, MCPGrantAccount, Projects, SessionPassageEmbedding, Sessions
from core.services.semantic_search import DIMENSIONS, RELATED_LIMIT
from core.test_semantic_search import SemanticSearchTestCase

QUERY = "dizzy during leg curls"
KEYWORD = "leg curl"

# (id, project, end, note, similarity to both queries), newest first.
SESSIONS = [
    (5642, "Gym - 67kgs", (2026, 8, 26, 7, 21), "Legs day. Back squat 60 kg x 8. Leg curl: 20 kg x 15. "
     "The leg curls still make my head spin, so I pause before the next exercise.", 0.62),
    (5580, "Gym - 64kgs", (2026, 8, 14, 8, 4), "Leg day! I skipped the last two exercises to get home "
     "before my Czech lesson. Squats 3x6 at 60kgs, then deadlifts 2x6 at 90kgs. "
     "Ended on leg curls, first time on that machine: the room went wobbly for a "
     "moment afterwards. 3 sets of 15 at 15kgs. Morning weigh in 64.60kgs.", 0.48),
    (3420, "Gym - 2023 and 2025", (2025, 7, 22, 7, 18), "Leg day! Squats, Romanian deadlifts, "
     "leg press machine for 4 sets of 10, calf raises.", 0.58),
    (3331, "Gym - 2023 and 2025", (2024, 2, 5, 18, 40), "did more than usual so my legs are jelly", 0.66),
    (3304, "Gym - 2023 and 2025", (2023, 12, 11, 18, 19), "particularly hard squats today", 0.53),
    (3210, "Gym - 2023 and 2025", (2023, 7, 24, 17, 9), "squats where the bar hung from strings", 0.50),
    (2127, "weights", (2023, 4, 24, 4, 2), "alternating curls and hammer curls", 0.47),
    (2095, "weights", (2023, 2, 3, 4, 57), "reverse curls suck", 0.46),
    (2083, "weights", (2023, 1, 19, 5, 15), "five minute workout, swapped in normal curls", 0.55),
    (2001, "Czech", (2023, 1, 10, 9, 0), "vocabulary flashcards", 0.10),
]
RELEVANT = {5580, 5642}
# Passages (of #5580, the only note long enough to split) scored apart from
# their whole note: none by default, so the whole-note order above holds.
PASSAGE_SCORES = {"room went wobbly": None}
# Best first: what the Related section and relevance ordering must list.
BY_SIMILARITY = [pk for pk, *_, score in sorted(SESSIONS, key=lambda row: -row[-1]) if score >= 0.45]


def parity_vector(text):
    """Both queries point one way; each note sits at its chosen cosine to it."""
    vector = [0.0] * DIMENSIONS
    if text in (QUERY, KEYWORD):
        vector[0] = 1.0
        return vector
    for axis, (_, _, _, note, score) in enumerate(SESSIONS, start=1):
        if note in text:
            vector[0], vector[axis] = score, math.sqrt(1 - score * score)
            return vector
    for axis, (marker, score) in enumerate(PASSAGE_SCORES.items(), start=len(SESSIONS) + 1):
        if score is not None and marker in text:
            vector[0], vector[axis] = score, math.sqrt(1 - score * score)
            return vector
    vector[DIMENSIONS - 1] = 1.0  # projects and passages: unrelated to everything
    return vector


@override_settings(MCP_RESOURCE="http://testserver/mcp")
class SearchParityTests(SemanticSearchTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch("core.test_semantic_search.fake_vector", parity_vector)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.kuda = self._user("parity-kuda", "kuda-key")
        projects = {}
        for pk, project, end, note, _ in SESSIONS:
            if project not in projects:
                projects[project] = Projects.objects.create(user=self.kuda, name=project)
            end = datetime(*end, tzinfo=dt_timezone.utc)
            Sessions.objects.create(
                pk=pk, user=self.kuda, project=projects[project],
                start_time=end - timedelta(minutes=50), end_time=end, note=note,
            )
        self._sync()
        self.client.force_login(self.kuda)

        application = Application.objects.create(
            name="parity", client_type="public", authorization_grant_type="authorization-code"
        )
        grant = MCPGrant.objects.create(
            owner=self.kuda, name="parity", default_account="kuda", oauth_application=application,
            expires_at=timezone.now() + timedelta(days=1),
        )
        MCPGrantAccount.objects.create(grant=grant, user=self.kuda, name="kuda")
        AccessToken.objects.create(
            user=self.kuda, application=application, token="parity-token", scope="autumn:read",
            resource=["http://testserver/mcp"], expires=timezone.now() + timedelta(hours=1),
        )

    # ------------------------------------------------------------ surfaces --

    def _api(self, **params):
        response = self.client.get(reverse("api_v2:sessions"), params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def _mcp(self, **args):
        response = self.client.post(
            "/mcp",
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "list_sessions", "arguments": args}}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer parity-token",
            HTTP_ACCEPT="application/json, text/event-stream",
            HTTP_MCP_PROTOCOL_VERSION="2025-11-25",
        )
        result = response.json()["result"]
        self.assertNotIn("isError", result, result)
        return result["structuredContent"]

    @staticmethod
    def _ids(payload):
        return [row["id"] for row in payload["sessions"]]

    # --------------------------------------------------------------- tests --

    def test_keyword_only_finds_nothing_for_the_paraphrase(self):
        self.assertEqual(self._api(search=QUERY)["total"], 0)
        self.assertEqual(self._mcp(search=QUERY, related=False, limit=500)["total"], 0)

    def test_both_relevant_sessions_are_retrievable_everywhere(self):
        api = self._api(search=QUERY, related="true", include="note")
        self.assertTrue(RELEVANT <= set(self._ids(api)))
        self.assertNotIn("dizzy", " ".join(row["note"] for row in api["sessions"]).lower())
        self.assertTrue(RELEVANT <= set(self._ids(self._mcp(search=QUERY, related=True, limit=100))))

    def test_api_and_mcp_list_the_same_sessions_in_the_same_order(self):
        api = self._api(search=QUERY, related="true")
        mcp = self._mcp(search=QUERY, related=True, include="note", limit=100)
        self.assertEqual(self._ids(api), BY_SIMILARITY)
        self.assertEqual(self._ids(mcp), BY_SIMILARITY)
        self.assertEqual(api["total"], mcp["total"])
        self.assertEqual(api["total"], len(BY_SIMILARITY))
        self.assertEqual({row["match"] for row in api["sessions"]}, {"related"})

    def test_pages_line_up_across_api_and_mcp(self):
        # A client showing RELATED_LIMIT at a time (the Sessions page's
        # Related section did): #5580 is seventh, on the second page.
        first = self._api(search=QUERY, related="true", limit=RELATED_LIMIT)
        self.assertEqual(self._ids(first), BY_SIMILARITY[:RELATED_LIMIT])
        self.assertEqual(first["total"], len(BY_SIMILARITY))
        page_two = BY_SIMILARITY[RELATED_LIMIT : 2 * RELATED_LIMIT]
        self.assertIn(5580, page_two)
        api = self._api(search=QUERY, related="true", offset=RELATED_LIMIT, limit=RELATED_LIMIT)
        self.assertEqual(self._ids(api), page_two)
        mcp = self._mcp(search=QUERY, related=True, offset=RELATED_LIMIT, limit=RELATED_LIMIT)
        self.assertEqual(self._ids(mcp), page_two)
        self.assertEqual(api["total"], len(BY_SIMILARITY))

    def test_ordinary_keyword_search_finds_both(self):
        self.assertEqual(self._ids(self._api(search=KEYWORD)), [5642, 5580])

    def test_related_keeps_keyword_matches_first_and_labelled_direct(self):
        api = self._api(search=KEYWORD, related="true")
        mcp = self._mcp(search=KEYWORD, related=True)
        expected = [5642, 5580] + [pk for pk in BY_SIMILARITY if pk not in RELEVANT]
        self.assertEqual(self._ids(api), expected)
        self.assertEqual(self._ids(mcp), expected)
        self.assertEqual(
            [row["match"] for row in api["sessions"]],
            ["direct", "direct"] + ["related"] * (len(expected) - 2),
        )

    def test_api_and_mcp_pages_cross_from_direct_to_related(self):
        # "leg curl": 2 direct matches, then the other related ones best first.
        everything = self._ids(self._api(search=KEYWORD, related="true", limit=500))
        total = len(everything)
        for offset, limit in [(0, 1), (1, 2), (2, 3), (1, total), (total - 1, 5), (total, 5), (total + 3, 5)]:
            with self.subTest(offset=offset, limit=limit):
                api = self._api(search=KEYWORD, related="true", offset=offset, limit=limit)
                mcp = self._mcp(search=KEYWORD, related=True, offset=offset, limit=limit)
                self.assertEqual(self._ids(api), everything[offset : offset + limit])
                self.assertEqual(self._ids(mcp), self._ids(api))
                self.assertEqual(api["count"], len(everything[offset : offset + limit]))
                self.assertEqual(api["total"], total)
                self.assertEqual(mcp["total"], total)
        crossing = self._api(search=KEYWORD, related="true", offset=1, limit=2)["sessions"]
        self.assertEqual([row["match"] for row in crossing], ["direct", "related"])

    def test_newest_ordering_keeps_the_date_order(self):
        newest = self._api(search=QUERY, related="true", ordering="newest")
        self.assertEqual(self._ids(newest), sorted(BY_SIMILARITY, reverse=True))
        self.assertEqual(newest["total"], len(BY_SIMILARITY))
        self.assertEqual({row["match"] for row in newest["sessions"]}, {"related"})
        newest_mcp = self._mcp(search=QUERY, related=True, ordering="newest")
        self.assertEqual(self._ids(newest_mcp), self._ids(newest))
        response = self.client.get(reverse("api_v2:sessions"), {"search": QUERY, "ordering": "sideways"})
        self.assertEqual(response.status_code, 400)

    def test_a_passage_lifts_the_buried_session_first_everywhere(self):
        self.assertTrue(SessionPassageEmbedding.objects.filter(session_id=5580).exists())
        with mock.patch.dict(PASSAGE_SCORES, {"room went wobbly": 0.70}):
            SessionPassageEmbedding.objects.all().delete()
            self._sync()
        expected = [5580] + [pk for pk in BY_SIMILARITY if pk != 5580]
        self.assertEqual(self._ids(self._api(search=QUERY, related="true")), expected)
        self.assertEqual(self._ids(self._mcp(search=QUERY, related=True)), expected)

    def test_without_search_there_is_no_match_label(self):
        rows = self._api(limit=3)["sessions"]
        self.assertEqual([row["id"] for row in rows], [5642, 5580, 3420])
        self.assertTrue(all("match" not in row for row in rows))
