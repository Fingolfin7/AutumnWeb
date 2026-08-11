import queue
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.http import StreamingHttpResponse
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from asgiref.sync import async_to_sync
from unittest.mock import patch

from llm_insights.base_handler import BaseLLMHandler
from llm_insights.claude_handler import ClaudeHandler
from llm_insights.gemini_handler import GeminiHandler
from llm_insights.llm_handlers import get_llm_handler
from llm_insights.models import LLMChat, LLMMessage
from llm_insights.openai_handler import OpenAIHandler
from llm_insights.views import (
    InsightsView,
    clean_generated_chat_title,
    configure_sse_response,
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

    def test_gemini_models_require_a_profile_api_key(self):
        provider_models = self.view._provider_models(self.user)

        self.assertNotIn("gemini", provider_models)

        self.user.profile.set_api_key("gemini", "test-gemini-key")
        self.user.profile.save()

        provider_models = self.view._provider_models(self.user)
        self.assert_has_model_choices(provider_models, "gemini")

    def test_openai_models_are_available_when_key_present(self):
        self.user.profile.set_api_key("openai", "test-openai-key")
        self.user.profile.save()

        provider_models = self.view._provider_models(self.user)

        self.assert_has_model_choices(provider_models, "openai")
        self.assertEqual(
            provider_models["openai"],
            [
                ("gpt-5.6-luna", "GPT-5.6 Luna"),
                ("gpt-5.6-sol", "GPT-5.6 Sol"),
                ("gpt-5.6-terra", "GPT-5.6 Terra"),
                ("gpt-5.5", "GPT-5.5"),
            ],
        )

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
        self.assertIn(("gpt-5.6-sol", "GPT-5.6 Sol"), provider_models["openai"])
        self.assertNotIn("openai_chatgpt", provider_models)

    def test_openai_reasoning_effort_defaults_to_high(self):
        self.assertEqual(
            self.view._validate_reasoning_effort("openai", "unexpected"),
            "high",
        )

    def test_xhigh_reasoning_effort_is_available(self):
        self.assertIn("xhigh", self.view.OPENAI_REASONING_EFFORTS)
        self.assertEqual(
            self.view._validate_reasoning_effort("openai", "xhigh", "gpt-5.5"),
            "xhigh",
        )

    def test_legacy_extra_high_reasoning_effort_is_normalized(self):
        self.assertEqual(
            self.view._validate_reasoning_effort(
                "openai", "extra-high", "gpt-5.6-sol"
            ),
            "xhigh",
        )

    def test_max_reasoning_effort_is_only_available_for_gpt_5_6(self):
        self.assertEqual(
            self.view._validate_reasoning_effort("openai", "max", "gpt-5.6-sol"),
            "max",
        )
        self.assertEqual(
            self.view._validate_reasoning_effort("openai", "max", "gpt-5.5"),
            "high",
        )

    def test_openai_is_the_default_provider_and_model_when_available(self):
        self.user.profile.set_api_key("openai", "test-openai-key")
        self.user.profile.save()

        provider_models = self.view._provider_models(self.user)

        self.assertEqual(
            self.view._validate_selection(provider_models, None, None),
            ("openai", "gpt-5.6-luna"),
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

    def test_insights_page_redirects_when_no_profile_credentials_exist(self):
        self.user.profile.ai_features_enabled = True
        self.user.profile.save()
        client = Client()
        client.force_login(self.user)

        response = client.get(reverse("insights"))

        self.assertRedirects(response, reverse("home"))

        home_response = client.get(reverse("home"))
        self.assertNotContains(home_response, f'href="{reverse("insights")}"')


class TokenUsageHeaderTests(TestCase):
    def test_header_reports_cached_tokens_alongside_in_and_out(self):
        user = User.objects.create_user(username="usage-user", password="test-pass-123")
        user.profile.set_api_key("gemini", "test-gemini-key")
        user.profile.ai_features_enabled = True
        user.profile.save()
        chat = LLMChat.objects.create(
            user=user, title="Usage test", model="gemini:gemini-3.1-flash-lite"
        )
        for cached in (0, 3054):
            LLMMessage.objects.create(
                chat=chat,
                role="assistant",
                content="answer",
                metadata={"usage": {"prompt": 7878, "response": 31, "cached": cached}},
            )
        client = Client()
        client.force_login(user)

        response = client.get(
            reverse("insights_detail", kwargs={"chat_id": chat.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "In: 15756")
        self.assertContains(response, "Cached: 3054")
        self.assertContains(response, 'data-cached="3054"')

    def test_header_omits_cached_when_nothing_was_cached(self):
        user = User.objects.create_user(username="nocache-user", password="test-pass-123")
        user.profile.set_api_key("gemini", "test-gemini-key")
        user.profile.ai_features_enabled = True
        user.profile.save()
        chat = LLMChat.objects.create(
            user=user, title="No cache", model="gemini:gemini-3.1-flash-lite"
        )
        LLMMessage.objects.create(
            chat=chat,
            role="assistant",
            content="answer",
            metadata={"usage": {"prompt": 100, "response": 10, "cached": 0}},
        )
        client = Client()
        client.force_login(user)

        response = client.get(
            reverse("insights_detail", kwargs={"chat_id": chat.id})
        )

        self.assertNotContains(response, "Cached:")


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

    def test_openai_title_requests_always_use_luna(self):
        handler = OpenAIHandler(model="gpt-5.6-terra")

        self.assertEqual(
            handler._api_title_response_kwargs("title this")["model"],
            "gpt-5.6-luna",
        )
        self.assertEqual(
            handler._codex_title_response_kwargs("title this")["model"],
            "gpt-5.6-luna",
        )


class GeminiHandlerUsageTests(SimpleTestCase):
    def test_gemini_does_not_use_a_global_environment_key(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "global-key"}):
            with self.assertRaisesRegex(RuntimeError, "not configured"):
                GeminiHandler()

    def test_update_usage_counts_thought_tokens_in_response(self):
        handler = object.__new__(GeminiHandler)
        handler.usage_stats = {"prompt": 0, "response": 0, "cached": 0, "total": 0}
        handler.conversation_history = []
        response = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=100,
                candidates_token_count=50,
                thoughts_token_count=25,
                cached_content_token_count=40,
                total_token_count=175,
            )
        )

        handler._update_usage(response)

        self.assertEqual(
            handler.usage_stats,
            {"prompt": 100, "response": 75, "cached": 40, "total": 175},
        )


PAYLOAD = "SESSION-PAYLOAD-MARKER"


class FakeClaudeMessages:
    def __init__(self):
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(text="ok")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=2),
        )


class ClaudeHandlerRequestShapeTests(SimpleTestCase):
    def build_handler(self, history=None):
        handler = ClaudeHandler(model="claude-sonnet-5", api_key="test-key")
        messages = FakeClaudeMessages()
        handler.client = SimpleNamespace(messages=messages)
        if history is None:
            handler.username = "kuda"
            handler.session_data = PAYLOAD
        else:
            handler.set_conversation_history(history)
        return handler, messages

    def test_session_payload_rides_in_system_with_a_cache_breakpoint(self):
        handler, messages = self.build_handler()

        async_to_sync(handler.send_message)("what did I work on?")

        system = messages.kwargs["system"]
        self.assertEqual(len(system), 1)
        self.assertIn(PAYLOAD, system[0]["text"])
        self.assertEqual(system[0]["cache_control"], {"type": "ephemeral"})

    def test_user_prompt_stays_out_of_the_cached_prefix(self):
        handler, messages = self.build_handler()

        async_to_sync(handler.send_message)("what did I work on?")

        self.assertNotIn("what did I work on?", messages.kwargs["system"][0]["text"])
        self.assertEqual(
            messages.kwargs["messages"],
            [{"role": "user", "content": "what did I work on?"}],
        )

    def test_resumed_chat_still_sends_the_session_payload(self):
        # Regression: the payload used to live in a history entry with role
        # "system", which the message builder skipped — so every turn after the
        # first ran with no data and no instructions.
        handler, messages = self.build_handler(
            history=[
                {"role": "system", "content": f"instructions\n{PAYLOAD}"},
                {"role": "user", "content": "first question"},
                {"role": "assistant", "content": "first answer"},
            ]
        )

        async_to_sync(handler.send_message)("follow-up question")

        self.assertIn(PAYLOAD, messages.kwargs["system"][0]["text"])
        self.assertEqual(
            [m["role"] for m in messages.kwargs["messages"]],
            ["user", "assistant", "user"],
        )

    def test_payload_is_not_duplicated_into_the_message_list(self):
        handler, messages = self.build_handler()

        async_to_sync(handler.send_message)("what did I work on?")

        for message in messages.kwargs["messages"]:
            self.assertNotIn(PAYLOAD, message["content"])

    def test_max_tokens_tracks_the_model_ceiling(self):
        handler, messages = self.build_handler()

        # Non-streaming is capped below the ceiling so the SDK does not refuse
        # the request on its own timeout estimate.
        async_to_sync(handler.send_message)("summarise my month")
        self.assertEqual(
            messages.kwargs["max_tokens"], handler.NON_STREAMING_MAX_OUTPUT_TOKENS
        )

        self.assertEqual(handler._max_tokens(streaming=True), 128000)
        handler.model = "claude-haiku-4-5"
        self.assertEqual(handler._max_tokens(streaming=True), 64000)
        handler.model = "some-future-model"
        self.assertEqual(
            handler._max_tokens(streaming=True), handler.DEFAULT_MAX_OUTPUT_TOKENS
        )

    def test_safety_refusals_surface_as_readable_text(self):
        handler, _ = self.build_handler()

        text = handler._refusal_text(
            SimpleNamespace(
                stop_reason="refusal",
                stop_details=SimpleNamespace(category="cyber"),
            )
        )

        self.assertIn("declined", text)
        self.assertIn("cyber", text)
        self.assertIsNone(handler._refusal_text(SimpleNamespace(stop_reason="end_turn")))


class GeminiSystemInstructionTests(SimpleTestCase):
    def build_handler(self):
        # Construct properly rather than via object.__new__: the prompt
        # templates are set in __init__, so a bare instance silently skips the
        # branch that builds a system prompt from fresh session data.
        handler = GeminiHandler(model="gemini-3.1-flash-lite", api_key="test-key")
        captured = {}

        class FakeChats:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace()

        handler.client = SimpleNamespace(aio=SimpleNamespace(chats=FakeChats()))
        return handler, captured

    def test_fresh_session_data_becomes_the_system_instruction(self):
        handler, captured = self.build_handler()
        handler.username = "kuda"
        handler.session_data = PAYLOAD

        async_to_sync(handler._create_chat)("gemini-3.1-flash-lite")

        self.assertIn(PAYLOAD, captured["config"].system_instruction)

    def test_create_chat_lifts_system_turns_into_system_instruction(self):
        handler, captured = self.build_handler()
        handler.conversation_history = [
            {"role": "system", "content": f"instructions\n{PAYLOAD}"},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
        ]

        async_to_sync(handler._create_chat)("gemini-3.1-flash-lite")

        self.assertIn(PAYLOAD, captured["config"].system_instruction)
        # Regression: system turns used to be replayed as user turns.
        self.assertEqual(
            [entry["role"] for entry in captured["history"]], ["user", "model"]
        )
        for entry in captured["history"]:
            self.assertNotIn(PAYLOAD, entry["parts"][0]["text"])


class OpenAIMessageAssemblyTests(SimpleTestCase):
    def build_resumed_handler(self):
        """A handler as the view builds it on turn 4: no session data of its
        own, history loaded from the database with two system snapshots — the
        original, and the one written by a filter change."""
        handler = OpenAIHandler(model="gpt-5.6-luna", api_key="test-key")
        handler.set_conversation_history(
            [
                {"role": "system", "content": "instructions\nSTALE-PAYLOAD"},
                {"role": "user", "content": "first question"},
                {"role": "assistant", "content": "first answer"},
                {"role": "system", "content": f"instructions\n{PAYLOAD}"},
                {"role": "user", "content": "second question"},
                {"role": "assistant", "content": "second answer"},
            ]
        )
        return handler

    def test_only_the_current_system_message_is_sent(self):
        # Regression: every filter change appended another system turn holding a
        # full payload, and all of them were replayed.
        handler = self.build_resumed_handler()

        messages = handler._messages_from_history(new_user_message="follow-up")

        self.assertEqual(
            [m["role"] for m in messages],
            ["system", "user", "assistant", "user", "assistant", "user"],
        )
        self.assertEqual(sum("STALE-PAYLOAD" in m["content"] for m in messages), 0)
        self.assertEqual(sum(PAYLOAD in m["content"] for m in messages), 1)

    def test_codex_instructions_use_the_current_payload(self):
        handler = self.build_resumed_handler()

        kwargs = handler._codex_response_kwargs(
            handler._messages_from_history(new_user_message="q")
        )

        self.assertIn(PAYLOAD, kwargs["instructions"])
        self.assertNotIn("STALE-PAYLOAD", kwargs["instructions"])
        self.assertNotIn("system", [m["role"] for m in kwargs["input"]])

    def test_xhigh_and_max_use_the_api_enum_values(self):
        handler = OpenAIHandler(
            model="gpt-5.6-sol", api_key="test-key", reasoning_effort="xhigh"
        )
        messages = [{"role": "user", "content": "q"}]

        self.assertEqual(
            handler._api_response_kwargs(messages)["reasoning"],
            {"effort": "xhigh"},
        )
        self.assertEqual(
            handler._codex_response_kwargs(messages)["reasoning"],
            {"effort": "xhigh"},
        )

        handler.reasoning_effort = "max"
        self.assertEqual(
            handler._api_response_kwargs(messages)["reasoning"],
            {"effort": "max"},
        )
        self.assertEqual(
            handler._codex_response_kwargs(messages)["reasoning"],
            {"effort": "max"},
        )


class CachedTokenAccountingTests(SimpleTestCase):
    def test_anthropic_prompt_total_includes_cache_reads_and_writes(self):
        # Anthropic's input_tokens is the uncached remainder, so the three
        # fields have to be summed to get the real prompt size.
        usage = ClaudeHandler._usage_from_response(
            SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=300,
                    cache_read_input_tokens=4000,
                    cache_creation_input_tokens=700,
                    output_tokens=50,
                )
            )
        )

        self.assertEqual(usage, {"prompt": 5000, "response": 50, "cached": 4000})

    def test_gemini_cached_is_a_subset_of_prompt(self):
        usage = GeminiHandler._usage_from_response(
            SimpleNamespace(
                usage_metadata=SimpleNamespace(
                    prompt_token_count=7878,
                    candidates_token_count=30,
                    thoughts_token_count=0,
                    cached_content_token_count=1543,
                )
            )
        )

        self.assertEqual(usage, {"prompt": 7878, "response": 30, "cached": 1543})

    def test_openai_reads_cached_tokens_from_either_details_shape(self):
        handler = OpenAIHandler(model="gpt-5.6-luna", api_key="test-key")

        responses_shape = handler._usage_from_api_response(
            SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=2000,
                    output_tokens=40,
                    input_tokens_details=SimpleNamespace(cached_tokens=1792),
                )
            )
        )
        self.assertEqual(responses_shape, {"prompt": 2000, "response": 40, "cached": 1792})

        completions_shape = handler._usage_from_api_response(
            SimpleNamespace(
                usage=SimpleNamespace(
                    prompt_tokens=2000,
                    completion_tokens=40,
                    prompt_tokens_details={"cached_tokens": 1792},
                )
            )
        )
        self.assertEqual(completions_shape["cached"], 1792)

    def test_missing_usage_is_zeroed_not_crashed(self):
        for extractor, payload in (
            (ClaudeHandler._usage_from_response, SimpleNamespace(usage=None)),
            (GeminiHandler._usage_from_response, SimpleNamespace(usage_metadata=None)),
        ):
            self.assertEqual(
                extractor(payload), {"prompt": 0, "response": 0, "cached": 0}
            )


class MultiTurnStateMachineTests(SimpleTestCase):
    """turn 1 -> turn 2 -> filter change -> turn 4, asserting exact history.

    Every provider must append exactly the turn's own entries, so the view can
    persist the delta. A path that appends too few re-persists earlier messages;
    too many duplicates the current ones.
    """

    def assert_history_shape(self, history):
        roles = [m["role"] for m in history]
        self.assertEqual(
            roles,
            ["system", "user", "assistant", "user", "assistant",
             "system", "user", "assistant", "user", "assistant"],
        )
        # Only the newest snapshot should be recoverable.
        systems = [m["content"] for m in history if m["role"] == "system"]
        self.assertIn("PAYLOAD_V1", systems[0])
        self.assertIn("PAYLOAD_V2", systems[1])

    def test_claude_history_after_four_turns(self):
        handler = ClaudeHandler(model="claude-sonnet-5", api_key="k")
        messages = FakeClaudeMessages()
        handler.client = SimpleNamespace(messages=messages)
        handler.username = "kuda"
        handler.session_data = "PAYLOAD_V1"

        async_to_sync(handler.send_message)("q1")
        async_to_sync(handler.send_message)("q2")
        with patch("llm_insights.claude_handler.encode", lambda *a, **k: "PAYLOAD_V2"):
            async_to_sync(handler.update_session_data)([], "q3")
        async_to_sync(handler.send_message)("q4")

        self.assert_history_shape(handler.get_conversation_history())
        # Final request: current payload only, and never inside the messages.
        self.assertIn("PAYLOAD_V2", messages.kwargs["system"][0]["text"])
        self.assertNotIn("PAYLOAD_V1", messages.kwargs["system"][0]["text"])
        for message in messages.kwargs["messages"]:
            self.assertNotIn("PAYLOAD_V", message["content"])

    def test_openai_sends_the_system_text_it_stores(self):
        # Regression: the update paths stored a notice-bearing snapshot but sent
        # a recomputed plain one, so turn 4's prefix could not match turn 3's.
        handler = OpenAIHandler(model="gpt-5.6-luna", api_key="k")
        sent = {}

        async def fake_send(messages):
            sent["messages"] = messages
            return {
                "text": "ok",
                "sources": [],
                "usage": {"prompt": 1, "response": 1, "cached": 0},
                "source": "api_key",
            }

        handler._send_with_priority = fake_send
        handler.username = "kuda"
        handler.session_data = "PAYLOAD_V1"

        async_to_sync(handler.send_message)("q1")
        async_to_sync(handler.send_message)("q2")
        with patch("llm_insights.openai_handler.encode", lambda *a, **k: "PAYLOAD_V2"):
            async_to_sync(handler.update_session_data)([], "q3")

        sent_system = next(m["content"] for m in sent["messages"] if m["role"] == "system")
        stored_system = [
            m["content"] for m in handler.get_conversation_history() if m["role"] == "system"
        ][-1]
        self.assertEqual(sent_system, stored_system)
        self.assertIn("has updated their session data", sent_system)

        async_to_sync(handler.send_message)("q4")
        self.assert_history_shape(handler.get_conversation_history())
        turn4_system = next(m["content"] for m in sent["messages"] if m["role"] == "system")
        self.assertEqual(turn4_system, stored_system)


class GeminiFailurePathTests(SimpleTestCase):
    def build_handler(self, raise_on_create=False, raise_on_send=False):
        handler = GeminiHandler(model="gemini-3.1-flash-lite", api_key="k")
        handler.username = "kuda"
        handler.session_data = "PAYLOAD_V1"

        class FakeChat:
            async def send_message(self, msg):
                if raise_on_send:
                    raise RuntimeError("provider exploded")
                return SimpleNamespace(text="ok", usage_metadata=None, candidates=None)

        class FakeChats:
            def create(self, **kwargs):
                if raise_on_create:
                    raise RuntimeError("chat creation failed")
                return FakeChat()

        handler.client = SimpleNamespace(aio=SimpleNamespace(chats=FakeChats()))
        return handler

    def test_failure_during_chat_creation_still_stores_the_snapshot(self):
        # Regression: _handle_error appends only an assistant turn, so bailing
        # before the system/user appends left the history short — the view then
        # persisted a fixed tail and re-saved the previous exchange.
        handler = self.build_handler(raise_on_create=True)

        async_to_sync(handler.send_message)("q1")

        roles = [m["role"] for m in handler.get_conversation_history()]
        self.assertEqual(roles, ["system", "user", "assistant"])
        self.assertIn("PAYLOAD_V1", handler.get_conversation_history()[0]["content"])

    def test_failure_mid_send_stores_exactly_one_turn(self):
        handler = self.build_handler(raise_on_send=True)

        async_to_sync(handler.send_message)("q1")
        before = len(handler.get_conversation_history())
        async_to_sync(handler.send_message)("q2")

        delta = handler.get_conversation_history()[before:]
        self.assertEqual([m["role"] for m in delta], ["user", "assistant"])

    def test_streaming_failure_stores_exactly_one_turn(self):
        # Streaming is the production path, so it gets the same guarantee as
        # the non-streaming one.
        handler = self.build_handler(raise_on_send=True)

        async def drain():
            chunks = []
            async for chunk in handler.stream_message("q1"):
                chunks.append(chunk)
            return chunks

        chunks = async_to_sync(drain)()

        self.assertTrue(any("error occurred" in c.lower() for c in chunks))
        roles = [m["role"] for m in handler.get_conversation_history()]
        self.assertEqual(roles, ["system", "user", "assistant"])

    def test_streaming_failure_during_chat_creation_stores_the_snapshot(self):
        handler = self.build_handler(raise_on_create=True)

        async def drain():
            async for _ in handler.stream_message("q1"):
                pass

        async_to_sync(drain)()

        roles = [m["role"] for m in handler.get_conversation_history()]
        self.assertEqual(roles, ["system", "user", "assistant"])
        self.assertIn("PAYLOAD_V1", handler.get_conversation_history()[0]["content"])

    def test_resumed_history_without_a_system_turn_is_reported(self):
        handler = GeminiHandler(model="gemini-3.1-flash-lite", api_key="k")
        handler.set_conversation_history(
            [
                {"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1"},
            ]
        )

        # The view uses this to decide whether to re-seed session data.
        self.assertFalse(handler.has_system_context())

        handler.initialize_chat("kuda", [])
        self.assertTrue(handler.has_system_context())


class ClaudeRefusalContextTests(SimpleTestCase):
    def test_refused_pair_is_not_replayed_to_the_provider(self):
        handler = ClaudeHandler(model="claude-opus-5", api_key="k")
        handler.username = "kuda"
        handler.session_data = PAYLOAD
        handler.set_conversation_history(
            [
                {"role": "system", "content": PAYLOAD},
                {"role": "user", "content": "benign question"},
                {"role": "assistant", "content": "benign answer"},
                {"role": "user", "content": "question that tripped a classifier"},
                {"role": "assistant", "content": "declined", "refusal": True},
            ]
        )

        messages = handler._api_messages(new_user_message="rephrased question")

        self.assertEqual(
            [m["content"] for m in messages],
            ["benign question", "benign answer", "rephrased question"],
        )

    def test_ordinary_turns_are_still_replayed(self):
        handler = ClaudeHandler(model="claude-opus-5", api_key="k")
        handler.set_conversation_history(
            [
                {"role": "system", "content": PAYLOAD},
                {"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1", "refusal": False},
            ]
        )

        messages = handler._api_messages(new_user_message="q2")

        self.assertEqual([m["content"] for m in messages], ["q1", "a1", "q2"])



# TransactionTestCase for the same close_old_connections() reason as above.
class ClaudeRefusalPersistenceTests(TransactionTestCase):
    def test_refusal_flag_survives_save_and_reload(self):
        # The flag is only useful if it round-trips: handlers are rebuilt from
        # LLMMessage.metadata on every turn, so a flag that is not persisted is
        # a refused turn that gets replayed to the provider anyway.
        user = User.objects.create_user(username="refusal-user")
        chat = LLMChat.objects.create(
            user=user, title="Refusal", model="claude:claude-opus-5"
        )

        async_to_sync(save_llm_messages)(
            chat.id,
            [
                {"role": "user", "content": "question that tripped a classifier"},
                {"role": "assistant", "content": "declined", "refusal": True},
            ],
        )

        reloaded = [
            {
                "role": m.role,
                "content": m.content,
                "refusal": m.metadata.get("refusal", False),
            }
            for m in chat.messages.all()
        ]
        self.assertTrue(reloaded[1]["refusal"])

        handler = ClaudeHandler(model="claude-opus-5", api_key="k")
        handler.set_conversation_history(reloaded)
        self.assertEqual(
            handler._api_messages(new_user_message="rephrased"),
            [{"role": "user", "content": "rephrased"}],
        )

class StreamQueueEventsTests(SimpleTestCase):
    def test_sse_response_uses_proxy_safe_headers(self):
        response = configure_sse_response(
            StreamingHttpResponse(iter(()), content_type="text/event-stream")
        )

        self.assertEqual(response["Cache-Control"], "no-cache")
        self.assertEqual(response["X-Accel-Buffering"], "no")
        self.assertNotIn("Connection", response)

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


class FakeStreamingHandler(BaseLLMHandler):
    """Subclasses the real base so it inherits set_username /
    has_system_context / set_conversation_history rather than re-stubbing them
    — a hand-rolled double silently drifts as the base grows."""

    def __init__(self):
        self.conversation_history = []
        self.initialized = False
        self.username = None

    def initialize_chat(self, username, sessions):
        self.initialized = True

    async def send_message(self, message):
        raise NotImplementedError

    async def update_session_data(self, sessions_data, user_prompt):
        raise NotImplementedError

    async def stream_message(self, message):
        yield "Hello"
        yield " world"
        # Append in place, like every real handler — replacing the list would
        # hide aliasing defects between the handler and the view's history.
        if not any(m["role"] == "system" for m in self.conversation_history):
            self.conversation_history.append(
                {"role": "system", "content": "system prompt"}
            )
        self.conversation_history.append({"role": "user", "content": message})
        self.conversation_history.append(
            {
                "role": "assistant",
                "content": "Hello world",
                "sources": [{"link": "https://example.com", "title": "Example"}],
                "model": "fake-model",
                "usage": {"prompt": 1, "response": 2},
            }
        )

    def get_conversation_history(self):
        return self.conversation_history


class FakeTitleHandler:
    async def generate_chat_title(self, prompt):
        self.prompt = prompt
        return '"Project Focus Patterns."'


# TransactionTestCase (not TestCase): this code path calls close_old_connections(),
# which closes the connection mid-test when TestCase wraps the test in a transaction.
# SQLite hides this (in-memory test connections can't be closed); Postgres doesn't.
class ChatTitleGenerationTests(TransactionTestCase):
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


# TransactionTestCase for the same close_old_connections() reason as above.
class PerformLlmAnalysisStreamTests(TransactionTestCase):
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

    def test_resumed_turn_persists_only_the_new_entries(self):
        # The distinguishing case for delta persistence: a turn that appends a
        # different number of entries than the old fixed tail assumed. Here the
        # provider fails mid-update, so only two entries are appended — the old
        # history[-3:] would have re-persisted the previous assistant turn.
        user = User.objects.create_user(username="delta-user")
        chat = LLMChat.objects.create(
            user=user, title="Delta", model="fake:fake-model"
        )
        stored = [
            {"role": "system", "content": "old snapshot"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ]

        class ShortTurnHandler(FakeStreamingHandler):
            async def stream_update_session_data(self, sessions, user_prompt):
                yield "boom"
                self.conversation_history.append(
                    {"role": "user", "content": user_prompt}
                )
                self.conversation_history.append(
                    {"role": "assistant", "content": "provider error"}
                )

        handler = ShortTurnHandler()
        handler.set_conversation_history(stored)

        async def run():
            async for _ in perform_llm_analysis_stream(
                llm_handler=handler,
                sessions=[],
                user_prompt="q2",
                username=user.username,
                conversation_history=stored,
                sessions_updated=True,
                chat_obj=chat.id,
            ):
                pass

        async_to_sync(run)()

        persisted = list(LLMMessage.objects.filter(chat=chat).order_by("created_at"))
        self.assertEqual([m.role for m in persisted], ["user", "assistant"])
        self.assertEqual(persisted[0].content, "q2")
        self.assertEqual(persisted[1].content, "provider error")

    def test_partial_recovery_sees_entries_the_handler_appended(self):
        # Regression: the handler used to alias the view's history list, so the
        # recovery boundary moved with the handler, the delta computed to empty,
        # and the turn's real entries were replaced by a synthetic pair.
        user = User.objects.create_user(username="alias-user")
        chat = LLMChat.objects.create(
            user=user, title="Alias", model="fake:fake-model"
        )
        view_history = [
            {"role": "system", "content": "snapshot"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ]
        handler = FakeStreamingHandler()
        handler.set_conversation_history(view_history)
        handler.conversation_history.append({"role": "user", "content": "q2"})
        handler.conversation_history.append(
            {"role": "assistant", "content": "real answer", "usage": {"prompt": 5}}
        )

        self.assertEqual(len(view_history), 3, "handler must not mutate the caller's list")

        async_to_sync(save_partial_stream_messages)(
            chat.id,
            previous_history=view_history,
            llm_handler=handler,
            user_prompt="q2",
            assistant_content="ignored",
            model="fake-model",
            error_message="db blew up",
        )

        persisted = list(LLMMessage.objects.filter(chat=chat).order_by("created_at"))
        self.assertEqual([m.role for m in persisted], ["user", "assistant"])
        self.assertEqual(persisted[1].content, "real answer")

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
