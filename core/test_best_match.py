"""Best match and optional Decisions ordering, with fictional data only."""
import json
from decimal import Decimal
from unittest.mock import patch

import httpx
from django.core.cache import cache
from django.urls import reverse
from openai import OpenAI

from core.models import RecommendationUsage, SessionEmbedding
from core.services.semantic_search import DIMENSIONS, encode_vector
from core.test_rerank import scored
from core.test_semantic_search import FakeOpenAI, SemanticSearchTestCase


class BestMatchTests(SemanticSearchTestCase):
    def test_best_scores_direct_and_related_with_one_query_embedding(self):
        self.failure_note.note = "sign-in failure invoice billing watered plants"
        self.failure_note.save()
        self._sync()
        unembedded = self._session(self.identity, "sign-in failure pending embedding")
        FakeOpenAI.instances = []
        cache.clear()
        response = self._search("sign-in failure", ordering="best")
        self.assertEqual(
            [(row["id"], row["match"]) for row in response.json()["sessions"]],
            [(self.oauth.pk, "related"), (self.failure_note.pk, "direct"), (unembedded.pk, "direct")],
        )
        self.assertEqual(FakeOpenAI.all_inputs(), [["sign-in failure"]])
        # Pagination follows the same order; vectors below the cutoff cannot
        # remove a direct match. AI off must fall back without embedding.
        self.assertEqual(self._search("sign-in failure", ordering="best", offset=1, limit=1).json()["sessions"][0]["id"], self.failure_note.pk)
        self.user.profile.ai_features_enabled = False
        self.user.profile.save()
        FakeOpenAI.instances = []
        response = self._search("sign-in failure", ordering="best")
        self.assertEqual([row["id"] for row in response.json()["sessions"]], [unembedded.pk, self.failure_note.pk])
        self.assertEqual(FakeOpenAI.all_inputs(), [])

    def test_ai_order_keeps_top_30_admits_only_relevant_near_misses_and_records_cost(self):
        for index in range(29):
            self._session(self.identity, f"sign-in failure investigation {index}")
        admitted = self._session(self.identity, "OAuth invoice review")
        rejected = self._session(self.identity, "OAuth payment review")
        self._sync()
        for session in (admitted, rejected):
            vector = [0.0] * DIMENSIONS
            vector[0], vector[1] = 0.35, (1 - 0.35 ** 2) ** 0.5
            SessionEmbedding.objects.filter(session=session).update(vector=encode_vector(vector))
        self.user.profile.search_ranker = "near"
        self.user.profile.save()
        params = {"search": "sign-in failure", "related": "true", "include": "note,note_html"}
        baseline = self._search("sign-in failure", ordering="best", limit=30).json()["sessions"]
        ids = [row["id"] for row in baseline]
        requests, fail = [], False

        def handle(request):
            body = json.loads(request.content)
            requests.append(body)
            answers = [scored(int(q["name"][1:]), 3 if q["name"] in {f"c{ids[-1]}", f"c{admitted.pk}"} else 1)
                       for q in body["questions"]]
            answers[0] = {"type": "refusal", "name": answers[0]["name"]}
            return httpx.Response(503 if fail else 200, json={"answers": answers, "usage": {
                "input_tokens": 1000, "output_tokens": 999,
                "input_tokens_details": {"cached_tokens": 100, "cache_write_tokens": 100},
            }})

        def client(**kwargs):
            return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle)))

        url = reverse("api_v2:sessions-best-match-order")
        with patch("core.services.rerank.OpenAI", side_effect=client):
            response = self.client.get(url, params)
            self.assertEqual(response.status_code, 200, response.content)
            result = response.json()
            self.assertTrue(result["reranked"])
            self.assertEqual(result["added"], 1)
            rows = result["sessions"]
            self.assertEqual(len(rows), 31)
            self.assertEqual(rows[0]["id"], ids[-1])
            self.assertEqual({row["id"] for row in rows}, set(ids) | {admitted.pk})
            self.assertEqual(next(row["match"] for row in rows if row["id"] == admitted.pk), "related")
            self.assertEqual(len(requests[0]["questions"]), 32)
            usage = RecommendationUsage.objects.get(provider="luna-search")
            self.assertEqual((usage.effort, usage.auth_route, usage.success), ("near", "api_key", True))
            self.assertEqual(usage.pricing["usd_per_million"]["output"], "0")
            self.assertEqual(usage.estimated_cost_usd, Decimal("0.00009350"))
            fail = True
            with self.assertLogs("core.api_v2.views.sessions", "WARNING"):
                failed = self.client.get(url, params).json()
            self.assertFalse(failed["reranked"])
            self.assertEqual([row["id"] for row in failed["sessions"]], ids)
            self.assertTrue(RecommendationUsage.objects.filter(provider="luna-search", success=False).exists())
            for field, value in (("search_ranker", "off"), ("ai_features_enabled", False), ("openai_api_key_enc", None)):
                with self.subTest(field=field):
                    profile = self.user.profile
                    profile.search_ranker, profile.ai_features_enabled = "near", True
                    setattr(profile, field, value)
                    profile.save()
                    before = len(requests)
                    self.assertFalse(self.client.get(url, params).json()["reranked"])
                    self.assertEqual(len(requests), before)
