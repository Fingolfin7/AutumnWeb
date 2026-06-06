from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from asgiref.sync import async_to_sync
from unittest.mock import patch

from llm_insights.gemini_handler import GeminiHandler
from llm_insights.llm_handlers import get_llm_handler
from llm_insights.models import LLMChat, LLMMessage
from llm_insights.openai_handler import OpenAIHandler
from llm_insights.views import InsightsView, perform_llm_analysis_stream
from users.codex_auth import serialize_token_bundle


class InsightsViewProviderModelsTests(TestCase):
    def setUp(self):
        self.view = InsightsView()
        self.user = User.objects.create_user(
            username="llm-user", password="test-pass-123"
        )

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
        self.assertIn(("gpt-5.5", "GPT-5.5"), provider_models["openai"])

    def test_openai_models_are_available_when_server_key_present(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-server-key"}):
            provider_models = self.view._provider_models(self.user)

        self.assert_has_model_choices(provider_models, "openai")

    def test_openai_models_are_available_when_chatgpt_token_present(self):
        self.user.profile.set_api_key(
            "openai_chatgpt",
            serialize_token_bundle(
                {
                    "id_token": "id-token",
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                }
            ),
        )
        self.user.profile.save()

        provider_models = self.view._provider_models(self.user)

        self.assert_has_model_choices(provider_models, "openai")
        self.assertIn(("gpt-5.5", "GPT-5.5"), provider_models["openai"])
        self.assertNotIn("openai_chatgpt", provider_models)

    def test_openai_reasoning_effort_defaults_to_medium(self):
        self.assertEqual(
            self.view._validate_reasoning_effort("openai", "unexpected"),
            "medium",
        )

    def test_reasoning_effort_is_ignored_for_non_openai_providers(self):
        self.assertEqual(
            self.view._validate_reasoning_effort("gemini", "high"),
            "",
        )


class GetLlmHandlerTests(SimpleTestCase):
    def test_routes_gemini_models_to_gemini_handler(self):
        handler = get_llm_handler(
            "gemini-test-model", api_keys={"gemini": "test-gemini-key"}
        )

        self.assertIsInstance(handler, GeminiHandler)
        self.assertEqual(handler.model, "gemini-test-model")

    def test_routes_gpt_models_to_openai_handler(self):
        handler = get_llm_handler(
            "gpt-test-model",
            api_keys={"openai": "test-openai-key"},
            reasoning_effort="high",
        )

        self.assertIsInstance(handler, OpenAIHandler)
        self.assertEqual(handler.model, "gpt-test-model")
        self.assertEqual(handler.reasoning_effort, "high")
        self.assertEqual(handler.auth_mode, OpenAIHandler.AUTH_API)

    def test_routes_codex_models_to_openai_handler_with_codex_auth_mode(self):
        handler = get_llm_handler(
            "gpt-5-codex",
            api_keys={"openai_chatgpt": "test-chatgpt-token"},
            reasoning_effort="medium",
        )

        self.assertIsInstance(handler, OpenAIHandler)
        self.assertEqual(handler.model, "gpt-5-codex")
        self.assertEqual(handler.reasoning_effort, "medium")
        self.assertEqual(handler.auth_mode, OpenAIHandler.AUTH_CODEX)

    def test_routes_gpt_models_to_openai_handler_with_codex_auth_mode(self):
        handler = get_llm_handler(
            "gpt-5.5",
            api_keys={"openai_chatgpt": "test-chatgpt-token"},
            reasoning_effort="medium",
        )

        self.assertIsInstance(handler, OpenAIHandler)
        self.assertEqual(handler.model, "gpt-5.5")
        self.assertEqual(handler.auth_mode, OpenAIHandler.AUTH_CODEX)

    def test_routes_gpt_models_to_openai_handler_with_codex_primary_api_fallback(self):
        handler = get_llm_handler(
            "gpt-5.5",
            api_keys={
                "openai": "test-openai-key",
                "openai_chatgpt": "test-chatgpt-token",
            },
            reasoning_effort="medium",
        )

        self.assertIsInstance(handler, OpenAIHandler)
        self.assertEqual(handler.auth_mode, OpenAIHandler.AUTH_CODEX_WITH_API_FALLBACK)


class FakeStreamingHandler:
    def __init__(self):
        self.conversation_history = []
        self.initialized = False

    def initialize_chat(self, username, sessions):
        self.initialized = True

    async def stream_message(self, message):
        yield "Hello"
        yield " world"
        self.conversation_history = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": "Hello world",
                "sources": [{"link": "https://example.com", "title": "Example"}],
                "model": "fake-model",
                "usage": {"prompt": 1, "response": 2},
            },
        ]

    def get_conversation_history(self):
        return self.conversation_history


class PerformLlmAnalysisStreamTests(TestCase):
    def test_streaming_analysis_yields_chunks_and_persists_final_history(self):
        user = User.objects.create_user(username="stream-user")
        chat = LLMChat.objects.create(
            user=user,
            title="Stream test",
            model="fake:fake-model",
        )
        handler = FakeStreamingHandler()

        async def collect_chunks():
            chunks = []
            async for chunk in perform_llm_analysis_stream(
                llm_handler=handler,
                sessions=[],
                user_prompt="Say hello",
                username=user.username,
                conversation_history=[],
                sessions_updated=False,
                chat_obj=chat.id,
            ):
                chunks.append(chunk)
            return chunks

        chunks = async_to_sync(collect_chunks)()

        self.assertEqual(chunks, ["Hello", " world"])
        self.assertTrue(handler.initialized)
        self.assertEqual(LLMMessage.objects.filter(chat=chat).count(), 3)
        assistant = LLMMessage.objects.get(chat=chat, role="assistant")
        self.assertEqual(assistant.content, "Hello world")
        self.assertEqual(assistant.metadata["model"], "fake-model")
        self.assertEqual(assistant.metadata["usage"], {"prompt": 1, "response": 2})
