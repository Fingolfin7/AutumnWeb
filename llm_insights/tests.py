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

    def test_gemini_models_include_updated_pro_preview(self):
        provider_models = self.view._provider_models(self.user)

        self.assertEqual(
            provider_models["gemini"],
            [
                ("gemini-3-flash-preview", "Gemini 3 Flash"),
                ("gemini-3.1-pro-preview", "Gemini 3.1 Pro Preview"),
            ],
        )

    def test_openai_models_include_new_gpt_variants_when_key_present(self):
        self.user.profile.set_api_key("openai", "test-openai-key")
        self.user.profile.save()

        provider_models = self.view._provider_models(self.user)

        self.assertEqual(
            provider_models["openai"],
            [
                ("gpt-5-mini", "GPT-5 Mini"),
                ("gpt-5", "GPT-5"),
                ("gpt-5.1", "GPT-5.1"),
                ("gpt-5.2", "GPT-5.2"),
                ("gpt-5.3", "GPT-5.3"),
                ("gpt-5.4", "GPT-5.4"),
                ("gpt-5.4-thinking", "GPT-5.4 Thinking"),
            ],
        )


class GetLlmHandlerTests(SimpleTestCase):
    def test_routes_updated_gemini_model_to_gemini_handler(self):
        handler = get_llm_handler(
            "gemini-3.1-pro-preview", api_keys={"gemini": "test-gemini-key"}
        )

        self.assertIsInstance(handler, GeminiHandler)
        self.assertEqual(handler.model, "gemini-3.1-pro-preview")

    def test_routes_new_openai_thinking_model_to_openai_handler(self):
        handler = get_llm_handler(
            "gpt-5.4-thinking", api_keys={"openai": "test-openai-key"}
        )

        self.assertIsInstance(handler, OpenAIHandler)
        self.assertEqual(handler.model, "gpt-5.4-thinking")
