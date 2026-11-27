import io
import json
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from queue import Queue
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from django.contrib.auth.models import User
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.core.management import call_command
from django.test import RequestFactory, TransactionTestCase

from core.models import Context, Projects, Sessions
from core.utils import set_active_context
from llm_insights.claude_handler import ClaudeHandler
from llm_insights.gemini_handler import GeminiHandler
from llm_insights.models import LLMChat, LLMMessage
from llm_insights.openai_handler import OpenAIHandler
from llm_insights.services.context import build_post_context
from llm_insights.services.streaming import _prepare_stream_context, _run_stream_worker, stream_insights_response
from llm_insights.session_context import SESSION_DATA_SLOT, compact_session_prompt


class InsightsSessionContextTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user("analyst")
        self.chat = LLMChat.objects.create(user=self.user, model="openai:gpt-6-luna")
        self.project = Projects.objects.create(user=self.user, name="Fictional Project")
        start = datetime(2026, 10, 30, 10, tzinfo=UTC)
        self.session = Sessions.objects.create(
            user=self.user, project=self.project, start_time=start,
            end_time=start + timedelta(hours=1), note="Original note.\nSecond line.",
        )

    def handler(self):
        return OpenAIHandler(api_key="test-key")

    def test_all_providers_rebuild_stored_instructions_without_resetting_history(self):
        for handler_class in (OpenAIHandler, ClaudeHandler, GeminiHandler):
            with self.subTest(provider=handler_class.__name__):
                handler = handler_class(api_key="test-key")
                handler.initialize_chat(self.user.username, [self.session])
                self.assertIn("Original note.", handler._active_system_text())
                instructions = handler._build_system_text()
                history = [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": "Question"},
                    {"role": "assistant", "content": "Reply"},
                ]
                handler.set_conversation_history(history)
                self.session.note = "Current note."
                handler.initialize_chat(self.user.username, [self.session])
                self.assertEqual(handler.get_conversation_history(), history)
                outbound = handler._active_system_text()
                self.assertIn("Current note.", outbound)
                self.assertNotIn(SESSION_DATA_SLOT, outbound)
                unknown = "Unrecognised historical snapshot containing a stale note."
                handler.set_conversation_history([{"role": "system", "content": unknown}])
                self.assertIn("Current note.", handler._active_system_text())
                self.assertEqual(handler.get_conversation_history()[0]["content"], unknown)
                self.session.note = "Original note.\nSecond line."

    def test_missing_or_deleted_context_cannot_fall_back_to_active_context(self):
        context = Context.objects.create(user=self.user, name="Active")
        self.project.context = context
        self.project.save(update_fields=["context"])
        request = RequestFactory().post("/api/v2/insights/stream/", {"prompt": "Follow-up"})
        request.user = self.user
        request.session = {}
        set_active_context(request, str(context.pk))

        legacy = build_post_context(request, self.user, self.chat.pk)
        self.assertTrue(legacy["needs_context_confirmation"])
        self.assertEqual(legacy["sessions"], [])
        response = stream_insights_response(request, self.chat.pk, lambda user: True)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Select sessions in Filters", b"".join(response.streaming_content))

        missing_context_id = context.pk + 100
        namesake = Context.objects.create(user=self.user, name=str(missing_context_id))
        self.project.context = namesake
        self.project.save(update_fields=["context"])
        self.chat.filters = {"context": str(missing_context_id)}
        self.chat.save(update_fields=["filters"])
        with_deleted_context = build_post_context(request, self.user, self.chat.pk)
        self.assertFalse(with_deleted_context["needs_context_confirmation"])
        self.assertEqual(with_deleted_context["sessions"], [])

        self.chat.filters = {"context": None}
        self.chat.save(update_fields=["filters"])
        all_contexts = build_post_context(request, self.user, self.chat.pk)
        self.assertFalse(all_contexts["needs_context_confirmation"])
        self.assertEqual(all_contexts["sessions"], [self.session])

    def test_full_prompt_exists_only_in_request_and_followup_uses_current_sessions(self):
        for provider, handler_class in (
            ("openai", OpenAIHandler), ("claude", ClaudeHandler), ("gemini", GeminiHandler)
        ):
            with self.subTest(provider=provider):
                self.session.note = "Original note."
                self.session.save(update_fields=["note"])
                self._exercise_provider_turns(provider, handler_class)

    def _exercise_provider_turns(self, provider, handler_class):
        chat = LLMChat.objects.create(user=self.user, model=provider)
        outbound = []

        def turn(prompt, filters=None):
            handler = handler_class(api_key="test-key")
            data = {"prompt": prompt}
            if filters is not None:
                data.update(filters, filter="1")
            request = RequestFactory().post("/api/v2/insights/stream/", data)
            request.user, request.session = self.user, SessionStore()

            async def emit_answer(*args):
                yield {"type": "final", "text": "Example answer"}

            async def openai_stream(messages):
                outbound.append((messages[0]["content"], messages[1:]))
                async for result in emit_answer():
                    yield result

            async def claude_stream(messages, system_text):
                outbound.append((system_text, messages))
                async for result in emit_answer():
                    yield result

            async def gemini_chat(model, history, system_text):
                outbound.append((system_text, history))
                handler.chat = object()

            stream_module = "llm_insights.services.streaming"
            with ExitStack() as stack:
                stack.enter_context(patch(f"{stream_module}.validate_selection", return_value=(provider, handler.model)))
                stack.enter_context(patch(f"{stream_module}.get_llm_handler", return_value=handler))
                stack.enter_context(patch(f"{stream_module}.get_chat_title_handler", return_value=handler))
                stack.enter_context(patch.object(handler, "generate_chat_title", AsyncMock(return_value="")))
                if provider == "openai":
                    stack.enter_context(patch.object(handler, "_stream_with_priority_events", openai_stream))
                elif provider == "claude":
                    stack.enter_context(patch.object(handler, "_stream_message_response", claude_stream))
                else:
                    stack.enter_context(patch.object(handler, "_create_chat", gemini_chat))
                    stack.enter_context(patch.object(handler, "_stream_chat_response", emit_answer))
                stream_context = _prepare_stream_context(request, self.user, chat.pk)
                events, done = Queue(), object()
                async_to_sync(_run_stream_worker)(stream_context, events, done)

            received = []
            while (event := events.get_nowait()) is not done:
                received.append(event)
            self.assertIn("event: done", "".join(received))
            self.assertNotIn('"error":', "".join(received))

        first_filters = {"context": "all", "include_projects": [str(self.project.pk)]}
        turn("Example question", first_filters)
        system = chat.messages.get(role="system")
        self.assertIn("When formatting text and links", system.content)
        self.assertIn(SESSION_DATA_SLOT, system.content)
        self.assertNotIn("Original note.", system.content)
        self.assertEqual(system.metadata["session_filters"], first_filters)
        self.assertIn("Original note.", outbound[0][0])

        self.session.note = "Edited note."
        self.session.save(update_fields=["note"])
        turn("Follow-up")
        self.assertEqual(chat.messages.filter(role="system").count(), 1)
        self.assertIn("Edited note.", outbound[1][0])
        self.assertNotIn("Original note.", outbound[1][0])
        self.assertNotIn(SESSION_DATA_SLOT, outbound[1][0])
        self.assertIn("Example question", json.dumps(outbound[1][1]))
        self.assertIn("Example answer", json.dumps(outbound[1][1]))

        new_filters = {"context": "all"}
        turn("New range", new_filters)
        updated = chat.messages.filter(role="system").latest("pk")
        self.assertIn("has updated their session data.", updated.content)
        self.assertNotIn("Edited note.", updated.content)
        self.assertEqual(updated.metadata["session_filters"], new_filters)
        self.assertIn("Edited note.", outbound[2][0])

    def test_cleanup_recognizes_old_toon_and_json_and_preserves_the_rest(self):
        handler = self.handler()
        handler.initialize_chat(self.user.username, [self.session])
        expected = handler._build_system_text()
        original = expected.replace(SESSION_DATA_SLOT, handler.session_data)
        system = LLMMessage.objects.create(chat=self.chat, role="system", content=original)
        user_message = LLMMessage.objects.create(chat=self.chat, role="user", content=original)
        unknown = LLMMessage.objects.create(
            chat=self.chat, role="system",
            content=expected.replace(SESSION_DATA_SLOT, "Custom text to retain."),
        )
        legacy_prefix = expected.replace(
            "        Sessions data:", "        Here is analyst's prompt:\n        Keep this question.\n\n        Sessions data:"
        )
        legacy_json = json.dumps({
            "Fictional Project": {
                "Start Date": "10-30-2026", "Last Updated": "10-30-2026", "Total Time": 60,
                "Status": "active", "Description": "", "Sub Projects": {}, "Session History": [],
            },
        })
        legacy = LLMMessage.objects.create(
            chat=self.chat, role="system", content=legacy_prefix.replace(SESSION_DATA_SLOT, legacy_json)
        )
        ambiguous = original.replace(
            "        Sessions data:", "        Sessions data:\n        A question.\n        Sessions data:"
        )
        self.assertEqual(compact_session_prompt(ambiguous), ambiguous)
        output = io.StringIO()
        call_command("compact_insights_prompts", username=self.user.username, stdout=output)
        self.assertIn("Would compact 2 of 3 system prompts", output.getvalue())
        self.assertIn("Left 1 unrecognised system prompts alone.", output.getvalue())
        system.refresh_from_db()
        self.assertEqual(system.content, original)

        call_command("compact_insights_prompts", username=self.user.username, apply=True, stdout=io.StringIO())
        for entry in (system, legacy, user_message, unknown):
            entry.refresh_from_db()
        self.assertEqual(system.content, expected)
        self.assertEqual(legacy.content, legacy_prefix)
        self.assertEqual(user_message.content, original)
        self.assertIn("Custom text to retain.", unknown.content)
        output = io.StringIO()
        call_command("compact_insights_prompts", username=self.user.username, apply=True, stdout=output)
        self.assertIn("Compacted 0 of 3", output.getvalue())
