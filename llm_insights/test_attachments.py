"""Files attached to Insights questions: what is extracted at upload, who can
reach a file, how it reaches each provider, and that it leaves storage with its
chat."""

import io
import shutil
import tempfile
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings
from PIL import Image

from llm_insights.attachments import docx_text, files_to_send, gemini_parts, transcript_text
from llm_insights.base_handler import BaseLLMHandler
from llm_insights.claude_handler import ClaudeHandler
from llm_insights.models import LLMAttachment, LLMMessage
from llm_insights.openai_handler import OpenAIHandler

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(body_xml):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", f"<w:document {W}><w:body>{body_xml}</w:body></w:document>")
    return buffer.getvalue()


def png(width, height):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "orange").save(buffer, "PNG")
    return buffer.getvalue()


class ExtractionTests(SimpleTestCase):
    def test_docx_keeps_headings_lists_and_tables(self):
        raw = make_docx(
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Sprint notes</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>Ship the </w:t></w:r><w:r><w:t>importer</w:t></w:r></w:p>'
            "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Owner</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>Hours</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        )
        self.assertEqual(docx_text(raw, "notes.docx").strip(), "## Sprint notes\n- Ship the importer\nOwner | Hours")

    def test_transcripts_drop_timings_and_join_a_speakers_cues(self):
        zoom = (
            "WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\nAda: We slipped a day.\n\n"
            "2\n00:00:03.500 --> 00:00:05.000\nAda: Tests were flaky.\n\n"
            "3\n00:00:05.500 --> 00:00:07.000\nGrace: I'll pair on it.\n"
        )
        self.assertEqual(transcript_text(zoom), "Ada: We slipped a day. Tests were flaky.\nGrace: I'll pair on it.")
        teams = "WEBVTT\n\nab12/3-0\n00:00:01.000 --> 00:00:02.000\n<v Grace Hopper>Morning all.</v>\n"
        self.assertEqual(transcript_text(teams), "Grace Hopper: Morning all.")

    def test_only_the_newest_files_fit_one_request(self):
        # Every turn resends the chat's files; past the budget the oldest are
        # left out (and named in a note) so the provider never refuses the request.
        mb = 1024 * 1024
        newest_first = [
            SimpleNamespace(id="new", kind="image", size=4 * mb),
            SimpleNamespace(id="doc", kind="text", size=9 * mb),
            SimpleNamespace(id="pdf", kind="pdf", size=7 * mb),
            SimpleNamespace(id="old", kind="image", size=2 * mb),
        ]
        self.assertEqual(files_to_send(newest_first), {"new", "pdf"})


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class AttachmentApiTests(TransactionTestCase):
    # TransactionTestCase: the stream closes DB connections, and the stored
    # file is removed on commit.

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.user = self._user("attacher")
        self.client = Client()
        self.client.force_login(self.user)

    def _user(self, name):
        user = User.objects.create_user(username=name, email=f"{name}@example.com", password="test-pass-123")
        user.profile.ai_features_enabled = True
        user.profile.set_api_key("claude", "test-key")
        user.profile.save()
        return user

    def _upload(self, name, content, client=None):
        return (client or self.client).post(
            "/api/v2/insights/attachments/", {"file": SimpleUploadedFile(name, content)}
        )

    def test_images_are_downscaled_and_unsupported_files_explained(self):
        response = self._upload("screenshot.png", png(3000, 1200))
        self.assertEqual(response.status_code, 201)
        attachment = LLMAttachment.objects.get(pk=response.json()["id"])
        with attachment.file.open("rb") as handle:
            self.assertEqual(Image.open(handle).size, (2000, 800))

        refused = self._upload("budget.xlsx", b"PK\x03\x04")
        self.assertEqual(refused.status_code, 400)
        self.assertIn(".csv", str(refused.json()))

    def test_files_are_private_to_their_owner(self):
        attachment_id = self._upload("notes.txt", b"standup notes").json()["id"]
        self.assertEqual(self.client.get(f"/api/v2/insights/attachments/{attachment_id}").status_code, 200)

        other = Client()
        other.force_login(self._user("nosy"))
        self.assertEqual(other.get(f"/api/v2/insights/attachments/{attachment_id}").status_code, 404)
        self.assertEqual(other.delete(f"/api/v2/insights/attachments/{attachment_id}").status_code, 404)
        refused = other.post(
            "/api/v2/insights/stream/",
            {"message": "what's in it?", "attachment_ids": [attachment_id]},
            content_type="application/json",
        )
        self.assertEqual(refused.status_code, 400)

    def test_sent_files_reach_the_model_and_leave_storage_with_the_chat(self):
        attachment_id = self._upload("standup.vtt", b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nAda: Blocked on review.\n").json()["id"]
        seen = {}

        class RecordingHandler(BaseLLMHandler):
            def __init__(self):
                self.conversation_history = []

            def initialize_chat(self, username, sessions):
                pass

            async def send_message(self, message):
                raise NotImplementedError

            async def update_session_data(self, sessions_data, user_prompt):
                raise NotImplementedError

            async def stream_message(self, message, attachments=None):
                seen["attachments"] = attachments
                self.conversation_history.append({"role": "system", "content": "system"})
                self.conversation_history.append(self._user_entry(message, attachments))
                self.conversation_history.append({"role": "assistant", "content": "Ada is blocked."})
                yield "Ada is blocked."

            def get_conversation_history(self):
                return self.conversation_history

        with patch("llm_insights.services.streaming.get_llm_handler", return_value=RecordingHandler()), patch(
            "llm_insights.services.streaming.generate_and_save_chat_title", return_value="Standup"
        ):
            response = self.client.post(
                "/api/v2/insights/stream/",
                {"message": "Who is blocked?", "attachment_ids": [attachment_id]},
                content_type="application/json",
            )
            b"".join(response.streaming_content)

        self.assertEqual(seen["attachments"][0]["text"], "Ada: Blocked on review.")
        attachment = LLMAttachment.objects.get(pk=attachment_id)
        self.assertEqual(attachment.message.content, "Who is blocked?")

        chat = attachment.message.chat
        detail = self.client.get(f"/api/v2/insights/chats/{chat.id}").json()
        user_turn = next(m for m in detail["messages"] if m["role"] == "user")
        self.assertEqual([a["name"] for a in user_turn["attachments"]], ["standup.vtt"])

        stored = attachment.file.name
        self.assertTrue(default_storage.exists(stored))
        self.client.delete(f"/api/v2/insights/chats/{chat.id}")
        self.assertFalse(LLMMessage.objects.filter(chat=chat).exists())
        self.assertFalse(default_storage.exists(stored))


class ProviderFormatTests(SimpleTestCase):
    """A history turn with a screenshot and a transcript, as each provider is sent it."""

    history = [
        {"role": "system", "content": "system"},
        {
            "role": "user",
            "content": "Summarise",
            "attachments": [
                {"id": "1", "kind": "image", "name": "slack.png", "mime": "image/png", "data": b"img"},
                {"id": "2", "kind": "text", "name": "call.vtt", "text": "Ada: hi"},
            ],
        },
        {"role": "assistant", "content": "Done"},
    ]

    def test_each_provider_gets_the_image_and_the_text(self):
        claude = ClaudeHandler(model="claude-sonnet-5-5", api_key="k")
        claude.set_conversation_history(self.history)
        blocks = claude._api_messages(new_user_message="And?")[0]["content"]
        self.assertEqual(blocks[0]["type"], "image")
        self.assertIn("Ada: hi", blocks[-1]["text"])
        self.assertTrue(blocks[-1]["text"].endswith("Summarise"))

        openai = OpenAIHandler(model="gpt-6-luna", api_key="k")
        openai.set_conversation_history(self.history)
        messages = openai._messages_from_history(new_user_message="And?")
        parts = messages[1]["content"]
        self.assertEqual([p["type"] for p in parts], ["input_image", "input_text"])
        self.assertEqual(openai._codex_input(messages[1:2])[0]["content"], parts)

        gemini = gemini_parts("Summarise", self.history[1]["attachments"])
        self.assertEqual(gemini[0]["inline_data"], {"mime_type": "image/png", "data": b"img"})
        self.assertIn("Ada: hi", gemini[-1]["text"])

        # No attachments, no change: the prompt stays a plain string.
        self.assertEqual(claude._api_messages(new_user_message="And?")[-1]["content"], "And?")
