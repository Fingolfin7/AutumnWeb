from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from llm_insights.gemini_handler import GeminiHandler
from llm_insights.llm_handlers import get_llm_handler
from llm_insights.openai_handler import OpenAIHandler
from llm_insights.views import InsightsView


class InsightsViewProviderModelsTests(TestCase):
    def setUp(self):
        self.view = InsightsView()
        self.user = User.objects.create_user(username="llm-user", password="test-pass-123")

    def assert_has_model_choices(self, provider_models, provider):
        self.assertIn(provider, provider_models)
        self.assertGreater(len(provider_models[provider]), 0)
        for model_value, model_label in provider_models[provider]:
            self.assertIsInstance(model_value, str)
            self.assertIsInstance(model_label, str)
            self.assertTrue(model_value)
            self.assertTrue(model_label)

    def test_gemini_models_are_available_without_api_key(self):
        provider_models = self.view._provider_models(self.user)

        self.assert_has_model_choices(provider_models, "gemini")

    def test_openai_models_are_available_when_key_present(self):
        self.user.profile.set_api_key("openai", "test-openai-key")
        self.user.profile.save()

        provider_models = self.view._provider_models(self.user)

        self.assert_has_model_choices(provider_models, "openai")


class GetLlmHandlerTests(SimpleTestCase):
    def test_routes_gemini_models_to_gemini_handler(self):
        handler = get_llm_handler("gemini-test-model", api_keys={"gemini": "test-gemini-key"})

        self.assertIsInstance(handler, GeminiHandler)
        self.assertEqual(handler.model, "gemini-test-model")

    def test_routes_gpt_models_to_openai_handler(self):
        handler = get_llm_handler("gpt-test-model", api_keys={"openai": "test-openai-key"})

        self.assertIsInstance(handler, OpenAIHandler)
        self.assertEqual(handler.model, "gpt-test-model")
