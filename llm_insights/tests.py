import queue
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from asgiref.sync import async_to_sync
from unittest.mock import patch

from llm_insights.gemini_handler import GeminiHandler
from llm_insights.llm_handlers import get_llm_handler
from llm_insights.models import LLMChat, LLMMessage
from llm_insights.openai_handler import OpenAIHandler
from llm_insights.views import (
    InsightsView,
    clean_generated_chat_title,
    fallback_chat_title,
    generate_and_save_chat_title,
    perform_llm_analysis_stream,
    save_llm_messages,
    save_partial_stream_messages,
    stream_keepalive,
    stream_queue_events,
)
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

    def test_insights_page_redirects_when_ai_features_disabled(self):
        self.user.profile.ai_features_enabled = False
        self.user.profile.save()
        client = Client()
        client.force_login(self.user)

        response = client.get(reverse("insights"))

        self.assertRedirects(response, reverse("home"))


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


class GeminiHandlerUsageTests(SimpleTestCase):
    def test_update_usage_counts_thought_tokens_in_response(self):
        handler = object.__new__(GeminiHandler)
        handler.usage_stats = {"prompt": 0, "response": 0, "total": 0}
        handler.conversation_history = []
        response = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=100,
                candidates_token_count=50,
                thoughts_token_count=25,
                total_token_count=175,
            )
        )

        handler._update_usage(response)

        self.assertEqual(
            handler.usage_stats, {"prompt": 100, "response": 75, "total": 175}
        )


class StreamQueueEventsTests(SimpleTestCase):
    def test_stream_queue_events_yields_keepalive_while_idle(self):
        event_queue = queue.Queue()
        stream_done = object()
        stream = stream_queue_events(
            event_queue, stream_done, heartbeat_seconds=0.001
        )

        self.assertEqual(next(stream), stream_keepalive())

        event_queue.put("event: done\ndata: {}\n\n")
        self.assertEqual(next(stream), "event: done\ndata: {}\n\n")

        event_queue.put(stream_done)
        with self.assertRaises(StopIteration):
            next(stream)


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


class FakeTitleHandler:
    async def generate_chat_title(self, prompt):
        self.prompt = prompt
        return '"Project Focus Patterns."'


class ChatTitleGenerationTests(TestCase):
    def test_fallback_chat_title_uses_prompt_until_llm_title_is_available(self):
        self.assertEqual(fallback_chat_title("  What did I work on?  "), "What did I work on?")
        self.assertEqual(fallback_chat_title(""), "New Chat")
        self.assertEqual(
            fallback_chat_title("x" * 45),
            f"{'x' * 40}...",
        )

    def test_clean_generated_chat_title_removes_wrapping_noise(self):
        self.assertEqual(
            clean_generated_chat_title('"Deep Work Rhythm."', "Fallback"),
            "Deep Work Rhythm",
        )
        self.assertEqual(clean_generated_chat_title("", "Fallback"), "Fallback")

    def test_generate_and_save_chat_title_updates_chat(self):
        user = User.objects.create_user(username="title-user")
        chat = LLMChat.objects.create(
            user=user,
            title="What did I work on?",
            model="fake:fake-model",
        )
        handler = FakeTitleHandler()
        history = [
            {"role": "system", "content": "hidden session data"},
            {"role": "user", "content": "What did I work on?"},
            {"role": "assistant", "content": "You spent most of the week on Project Focus."},
        ]

        title = async_to_sync(generate_and_save_chat_title)(chat, handler, history)

        chat.refresh_from_db()
        self.assertEqual(title, "Project Focus Patterns")
        self.assertEqual(chat.title, "Project Focus Patterns")
        self.assertNotIn("hidden session data", handler.prompt)


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

    def test_partial_stream_failure_persists_recoverable_messages(self):
        user = User.objects.create_user(username="partial-stream-user")
        chat = LLMChat.objects.create(
            user=user,
            title="Partial stream test",
            model="fake:fake-model",
        )
        handler = FakeStreamingHandler()

        async_to_sync(save_partial_stream_messages)(
            chat.id,
            previous_history=[],
            llm_handler=handler,
            user_prompt="Start streaming",
            assistant_content="Partial answer\n\nStream error: connection closed",
            model="fake-model",
            error_message="connection closed",
        )

        messages = list(LLMMessage.objects.filter(chat=chat).order_by("created_at"))
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].role, "user")
        self.assertEqual(messages[0].content, "Start streaming")
        self.assertEqual(messages[1].role, "assistant")
        self.assertIn("Partial answer", messages[1].content)
        self.assertTrue(messages[1].metadata["error"])
        self.assertEqual(messages[1].metadata["error_message"], "connection closed")

    def test_save_llm_messages_refreshes_db_connections_around_write(self):
        user = User.objects.create_user(username="fresh-db-user")
        chat = LLMChat.objects.create(
            user=user,
            title="Fresh DB test",
            model="fake:fake-model",
        )

        with patch("llm_insights.views.close_old_connections") as close_connections:
            async_to_sync(save_llm_messages)(
                chat.id,
                [{"role": "user", "content": "hello"}],
            )

        self.assertGreaterEqual(close_connections.call_count, 2)
        message = LLMMessage.objects.get(chat=chat)
        self.assertEqual(message.role, "user")
        self.assertEqual(message.content, "hello")
