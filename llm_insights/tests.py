from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from asgiref.sync import async_to_sync
from unittest.mock import patch

from llm_insights.base_handler import BaseLLMHandler
from llm_insights.claude_handler import ClaudeHandler
from llm_insights.gemini_handler import GeminiHandler
from llm_insights.llm_handlers import get_llm_handler
from llm_insights.models import LLMChat, LLMMessage
from llm_insights.openai_handler import OpenAIHandler
from llm_insights.services import handlers as insight_handlers
from llm_insights.services.analysis import perform_llm_analysis_stream
from llm_insights.services.chats import (
    fallback_chat_title,
    save_partial_stream_messages,
)


class InsightsViewProviderModelsTests(TestCase):
    """Model and reasoning-effort choices (llm_insights.services.handlers)."""

    OPENAI_REASONING_EFFORTS = insight_handlers.OPENAI_REASONING_EFFORTS

    def setUp(self):
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
        provider_models = insight_handlers.provider_models(self.user)

        self.assertNotIn("gemini", provider_models)

        self.user.profile.set_api_key("gemini", "test-gemini-key")
        self.user.profile.save()

        provider_models = insight_handlers.provider_models(self.user)
        self.assert_has_model_choices(provider_models, "gemini")

    def test_openai_models_are_available_when_key_present(self):
        self.user.profile.set_api_key("openai", "test-openai-key")
        self.user.profile.save()

        provider_models = insight_handlers.provider_models(self.user)

        self.assert_has_model_choices(provider_models, "openai")
        self.assertEqual(
            provider_models["openai"],
            [
                ("gpt-6-luna", "GPT-6 Luna"),
                ("gpt-6.1-sol", "GPT-6.1 Sol"),
                ("gpt-6-astra", "GPT-6 Astra"),
                ("gpt-5.5", "GPT-5.5"),
            ],
        )


    def test_openai_is_the_default_provider_and_model_when_available(self):
        self.user.profile.set_api_key("openai", "test-openai-key")
        self.user.profile.save()

        provider_models = insight_handlers.provider_models(self.user)

        self.assertEqual(
            insight_handlers.validate_selection(provider_models, None, None),
            ("openai", "gpt-6-luna"),
        )

    def test_options_expose_current_models_and_sol_max_effort(self):
        self.user.profile.ai_features_enabled = True
        for provider in ("openai", "claude"):
            self.user.profile.set_api_key(provider, "test-key")
        self.user.profile.save()
        self.client.force_login(self.user)

        response = self.client.get("/api/v2/insights/options/")

        self.assertEqual(response.status_code, 200)
        providers = {p["provider"]: p["models"] for p in response.json()["providers"]}
        sol = next(m for m in providers["openai"] if m["value"] == "gpt-6.1-sol")
        self.assertEqual(sol["reasoning_efforts"], ["low", "medium", "high", "xhigh", "max"])
        self.assertEqual(
            [(m["value"], m["label"]) for m in providers["claude"]],
            [
                ("claude-haiku-5-5", "Claude Haiku 5.5"),
                ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
                ("claude-opus-5-5", "Claude Opus 5.5"),
                ("claude-fable-5-1", "Claude Fable 5.1"),
            ],
        )

    def test_saved_models_follow_replacements(self):
        for provider in ("openai", "claude"):
            self.user.profile.set_api_key(provider, "test-key")
        self.user.profile.save()
        models = insight_handlers.provider_models(self.user)
        for provider, old, new in (
            ("openai", "gpt-6-sol", "gpt-6.1-sol"),
            ("openai", "gpt-5.6-sol", "gpt-6.1-sol"),
            ("openai", "gpt-5.6", "gpt-6.1-sol"),
            ("openai", "gpt-5.6-terra", "gpt-6.1-sol"),
            ("claude", "claude-haiku-4-5", "claude-haiku-5-5"),
            ("claude", "claude-sonnet-5", "claude-sonnet-5-5"),
            ("claude", "claude-opus-5", "claude-opus-5-5"),
            ("claude", "claude-fable-5", "claude-fable-5-1"),
        ):
            with self.subTest(model=old):
                self.assertEqual(insight_handlers.validate_selection(models, provider, old), (provider, new))
        self.assertEqual(insight_handlers.validate_reasoning_effort("openai", "max", "gpt-6.1-sol"), "max")
        self.assertEqual(insight_handlers.validate_reasoning_effort("openai", "max", "gpt-5.5"), "high")


class ClaudeOutputLimitTests(SimpleTestCase):
    def test_current_models_use_their_streaming_ceiling_and_bounded_nonstreaming_limit(self):
        for model in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"):
            with self.subTest(model=model):
                handler = ClaudeHandler(model=model, api_key="test-key")
                self.assertEqual(handler._max_tokens(streaming=True), 128000)
                self.assertEqual(handler._max_tokens(streaming=False), 16000)


class InsightsAccessAndUsageApiTests(TestCase):
    """The Insights page (React) reads chats and token usage from /api/v2/insights/."""

    def _user(self, name, *, ai=True, key=True):
        user = User.objects.create_user(username=name, email=f"{name}@example.com", password="test-pass-123")
        user.profile.ai_features_enabled = ai
        if key:
            user.profile.set_api_key("gemini", "test-gemini-key")
        user.profile.save()
        return user

    def test_access_is_refused_when_ai_features_are_disabled(self):
        client = Client()
        client.force_login(self._user("noai", ai=False))
        for path in ("/api/v2/insights/chats/", "/api/v2/insights/options/"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 403)

    def test_access_is_refused_without_provider_credentials(self):
        client = Client()
        client.force_login(self._user("nokey", key=False))
        self.assertEqual(client.get("/api/v2/insights/chats/").status_code, 403)


    def test_another_users_chat_is_not_found(self):
        owner = self._user("owner")
        chat = LLMChat.objects.create(user=owner, title="Private", model="gemini:gemini-3.1-flash-lite")
        client = Client()
        client.force_login(self._user("intruder"))
        self.assertEqual(client.get(f"/api/v2/insights/chats/{chat.id}").status_code, 404)
        self.assertEqual(client.delete(f"/api/v2/insights/chats/{chat.id}").status_code, 404)
        self.assertTrue(LLMChat.objects.filter(pk=chat.pk).exists())


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


    def test_routes_gpt_models_to_openai_handler_with_codex_auth_mode(self):
        handler = get_llm_handler(
            "gpt-5.5",
            api_keys={"openai_chatgpt": "test-chatgpt-token"},
            reasoning_effort="medium",
        )

        self.assertIsInstance(handler, OpenAIHandler)
        self.assertEqual(handler.model, "gpt-5.5")
        self.assertEqual(handler.auth_mode, OpenAIHandler.AUTH_CODEX)


class GeminiHandlerUsageTests(SimpleTestCase):
    def test_gemini_does_not_use_a_global_environment_key(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "global-key"}):
            with self.assertRaisesRegex(RuntimeError, "not configured"):
                GeminiHandler()


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


class OpenAIMessageAssemblyTests(SimpleTestCase):
    def build_resumed_handler(self):
        """A handler as the view builds it on turn 4: no session data of its
        own, history loaded from the database with two system snapshots — the
        original, and the one written by a filter change."""
        handler = OpenAIHandler(model="gpt-6-luna", api_key="test-key")
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


    def test_openai_reads_cached_tokens_from_either_details_shape(self):
        handler = OpenAIHandler(model="gpt-6-luna", api_key="test-key")

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


# TransactionTestCase for the same close_old_connections() reason as above.


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
