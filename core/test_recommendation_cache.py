from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, SimpleTestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import RecommendationCache, RecommendationUsage
from core.services.recommendation_cache import get_or_generate, RecommendationPending
from core.services.recommendation_usage import collect_attempts, provider_attempt, capture_usage


class PersistentAdviceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("usage", email="usage@example.com")
        self.other = User.objects.create_user("other-usage", email="other-usage@example.com")
        self.generate = mock.Mock(return_value={"recommendations": []})

    def get(self, key="context", provider="luna", user=None, generate=None):
        return get_or_generate(user or self.user, provider, "all", key, generate or self.generate)

    def test_database_cache_survives_memory_clear_and_expires_after_30_minutes(self):
        self.get()
        cache.clear()
        self.get()
        self.generate.assert_called_once()
        self.assertEqual(RecommendationUsage.objects.filter(event="cache_hit").count(), 1)
        row = RecommendationCache.objects.get()
        self.assertEqual(row.expires_at - row.generated_at, timedelta(minutes=30))
        RecommendationCache.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.get()
        self.assertEqual(self.generate.call_count, 2)

    def test_context_provider_and_account_are_isolated(self):
        self.get()
        self.get(key="changed-note-or-description")
        self.get(provider="jev")
        self.get(user=self.other)
        self.assertEqual(self.generate.call_count, 4)
        self.assertEqual(RecommendationCache.objects.count(), 3)

    def test_inflight_request_does_not_launch_duplicate_and_released_result_is_reused(self):
        def generate():
            with self.assertRaises(RecommendationPending):
                self.get()
            return {"recommendations": []}
        self.get(generate=generate)
        self.get()
        self.generate.assert_not_called()

    def test_stale_lease_can_be_reclaimed(self):
        self.get()
        RecommendationCache.objects.update(result=None, lease_until=timezone.now() - timedelta(seconds=1))
        self.get()
        self.assertEqual(self.generate.call_count, 2)

    def test_failure_is_recorded_without_content_and_has_cooldown(self):
        def generate():
            with provider_attempt("luna", "gpt-5.6-luna", "xhigh", "oauth"):
                raise TimeoutError("private prompt must not be saved")
        with self.assertRaises(TimeoutError):
            self.get(generate=generate)
        with self.assertRaises(RecommendationPending):
            self.get()
        row = RecommendationUsage.objects.get()
        self.assertEqual(row.error_category, "TimeoutError")
        self.assertIsNone(row.input_tokens)
        self.assertIsNone(row.estimated_cost_usd)

    def test_oauth_failure_and_api_fallback_are_separate_attempts(self):
        def generate():
            try:
                with provider_attempt("luna", "gpt-5.6-luna", "xhigh", "oauth"):
                    capture_usage({"input_tokens": 1000, "output_tokens": 20})
                    raise ValueError("invalid result")
            except ValueError:
                pass
            with provider_attempt("luna", "gpt-5.6-luna", "xhigh", "api_key"):
                capture_usage({"input_tokens": 1000, "output_tokens": 30})
                return {"recommendations": []}
        self.get(generate=generate)
        self.get()
        attempts = RecommendationUsage.objects.filter(event="attempt")
        self.assertEqual(attempts.count(), 2)
        self.assertEqual(attempts.filter(success=True).count(), 1)
        self.assertTrue(all(r.estimated_cost_usd is not None for r in attempts))

    def test_review_and_export_are_private(self):
        RecommendationUsage.objects.create(user=self.other, provider="secret-provider")
        RecommendationUsage.objects.create(user=self.user, provider="luna", model="gpt-5.6-luna", effort="xhigh", auth_route="oauth")
        url = reverse("recommendation_usage")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.user)
        for suffix in ("", "?format=csv", "?days=invalid"):
            response = self.client.get(url + suffix)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "secret-provider")
            self.assertContains(response, "luna" if suffix == "?format=csv" else "Luna")

    def test_manual_refresh_requires_post_csrf_and_only_expires_own_cache(self):
        self.get()
        self.get(user=self.other)
        self.client.force_login(self.user)
        url = reverse("refresh_recommendations")
        self.assertEqual(self.client.get(url).status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(url).status_code, 403)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertLessEqual(RecommendationCache.objects.get(user=self.user).expires_at, timezone.now())
        self.assertGreater(RecommendationCache.objects.get(user=self.other).expires_at, timezone.now())


class UsageAccountingTests(SimpleTestCase):
    def measure(self, usage, provider="luna", model="gpt-5.6-luna"):
        with collect_attempts() as attempts:
            with provider_attempt(provider, model, "xhigh", "oauth"):
                capture_usage(usage)
        return attempts[0]

    def test_reasoning_is_not_double_counted_and_cached_input_is_discounted(self):
        row = self.measure({"input_tokens": 1000, "output_tokens": 200,
                            "input_tokens_details": {"cached_tokens": 500},
                            "output_tokens_details": {"reasoning_tokens": 150}})
        self.assertEqual(row["estimated_cost_usd"], Decimal("0.00035000"))
        self.assertEqual(row["reasoning_tokens"], 150)

    def test_missing_usage_is_not_zero(self):
        self.assertNotIn("estimated_cost_usd", self.measure(None))
        self.assertNotIn("input_tokens", self.measure({"input_tokens": True}))

    def test_reported_cache_writes_use_write_rate(self):
        row = self.measure({"input_tokens": 1000, "output_tokens": 0,
                            "input_tokens_details": {"cached_tokens": 0, "cache_creation_tokens": 1000}})
        self.assertEqual(row["estimated_cost_usd"], Decimal("0.00025000"))

    def test_jev_output_is_free(self):
        row = self.measure({"input_tokens": 1000, "output_tokens": 100}, "jev", "jev-1.13.0")
        self.assertEqual(row["estimated_cost_usd"], Decimal("0.00004200"))

    def test_long_context_rate_applies_to_whole_request(self):
        row = self.measure({"input_tokens": 300000, "output_tokens": 1000})
        self.assertEqual(row["estimated_cost_usd"], Decimal("0.12180000"))
