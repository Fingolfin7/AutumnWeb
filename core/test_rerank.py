"""All Decisions requests use an in-process HTTP transport, never the network."""

import json
from unittest.mock import patch

from django.test import SimpleTestCase
import httpx
from openai import OpenAI

from core.services.rerank import rerank


def scored(pk, score):
    probabilities = [0.0] * 4
    probabilities[score] = 1.0
    return {"type": "score", "name": f"c{pk}", "score": score,
            "probabilities": probabilities, "confidence": 1.0}


class RerankTests(SimpleTestCase):
    def call(self, candidates, answers, *, status=200, **kwargs):
        requests = []

        def handle(request):
            self.assertEqual(str(request.url), "https://api.openai.com/v1/decisions")
            requests.append(json.loads(request.content))
            return httpx.Response(status, json={"answers": answers, "usage": {"input_tokens": 123}})

        client = OpenAI(api_key="fictional-test-key", max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(handle)))
        with patch("core.services.rerank.OpenAI", return_value=client):
            result = rerank("fictional search", candidates, api_key="fictional-test-key", **kwargs)
        return result, requests

    def test_scores_reorder_stably_and_build_bounded_request(self):
        usage = {}
        result, requests = self.call([(1, "x" * 2000), (2, "second"), (3, "third")],
                                     [scored(3, 3), scored(1, 1), scored(2, 3)], usage=usage)
        self.assertEqual(result, [2, 3, 1])
        body = requests[0]
        self.assertEqual(body["model"], "gpt-6-luna")
        self.assertIn("own time-tracking journal", body["input"])
        self.assertEqual(len(body["questions"][0]["levels"]), 4)
        self.assertTrue(body["questions"][0]["instructions"].endswith("x" * 1500))
        self.assertNotIn("x" * 1501, body["questions"][0]["instructions"])
        self.assertEqual(usage, {"requests": 1, "input_tokens": 123})

    def test_refusals_failures_and_malformed_answers_never_drop(self):
        candidates = [(i, "fictional entry") for i in range(1, 5)]
        refused = [{"type": "refusal", "name": f"c{i}"} for i in (1, 3)]
        result, _ = self.call(candidates, [refused[0], scored(2, 3), refused[1], scored(4, 0)])
        self.assertEqual(result, [2, 1, 3, 4])  # Refusals use median 1.5, retain their order.
        result, _ = self.call(candidates, [{"type": "refusal", "name": f"c{i}"} for i in range(1, 5)])
        self.assertEqual(result, [1, 2, 3, 4])
        malformed = [scored(1, 3), scored(2, 3), scored(3, 3),
                     {"type": "score", "name": "c4", "score": "invalid"}]
        for status, answers in [(503, []), (200, []), (200, [scored(1, 3)] * 4), (200, malformed)]:
            with self.subTest(status=status, answers=answers), self.assertLogs("core.services.rerank", "WARNING"):
                usage = {}
                result, _ = self.call(candidates, answers, status=status, usage=usage)
                self.assertEqual(result, [1, 2, 3, 4])
                self.assertEqual(usage["failures"], 1)

    def test_limit_preserves_tail_and_caps_requests_at_400(self):
        for count, kwargs, prefix in [(35, {}, 30), (405, {"limit": 1000}, 400)]:
            candidates = [(i, "fictional entry") for i in range(count)]
            result, requests = self.call(candidates, [scored(i, int(i == prefix - 1) * 3)
                                                     for i in range(prefix)], **kwargs)
            self.assertEqual(result[0], prefix - 1)
            self.assertEqual(result[prefix:], list(range(prefix, count)))
            self.assertCountEqual(result, range(count))
            self.assertEqual(len(requests[0]["questions"]), prefix)
