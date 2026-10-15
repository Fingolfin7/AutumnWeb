import tempfile
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import StreamingHttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient

from core.spa import bootstrap_payload
from core.models import Context, Projects, Sessions
from llm_insights.models import LLMChat


class StreamingNegotiationTests(TestCase):
    def setUp(self):
        self.media_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.user = User.objects.create_user(username="stream-api", password="secret")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _stage_upload(self):
        response = self.client.post(
            "/api/v2/import/uploads/",
            {"file": SimpleUploadedFile("data.json", b"{}", content_type="application/json")},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["upload_id"]

    def test_import_stream_accepts_event_stream_and_wildcard(self):
        for accept in ("text/event-stream", "*/*"):
            with self.subTest(accept=accept), mock.patch(
                "core.api_v2.import_export.iter_import", return_value=iter(["Imported"])
            ):
                upload_id = self._stage_upload()
                response = self.client.get(
                    f"/api/v2/import/uploads/{upload_id}/stream/",
                    HTTP_ACCEPT=accept,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "text/event-stream")
                self.assertIn(b"Imported", b"".join(response.streaming_content))

    def test_streaming_views_negotiate_event_stream_errors(self):
        missing = self.client.get(
            "/api/v2/import/uploads/00000000-0000-0000-0000-000000000000/stream/",
            HTTP_ACCEPT="text/event-stream",
        )
        self.assertEqual(missing.status_code, 404)
        self.assertIn(b'"code"', missing.content)
        self.assertIn(b'"not_found"', missing.content)

        profile = self.user.profile
        profile.ai_features_enabled = True
        profile.set_api_key("openai", "test-key")
        profile.save()
        invalid = self.client.post(
            "/api/v2/insights/stream/",
            {"message": ""},
            format="json",
            HTTP_ACCEPT="text/event-stream",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn(b'"code"', invalid.content)
        self.assertIn(b'"validation_error"', invalid.content)

        unsupported = self.client.get(
            "/api/v2/import/uploads/00000000-0000-0000-0000-000000000000/stream/",
            HTTP_ACCEPT="application/xml",
        )
        self.assertEqual(unsupported.status_code, 406)
        self.assertIn(b'"code"', unsupported.content)
        self.assertIn(b'"not_acceptable"', unsupported.content)

    def test_insights_stream_accepts_event_stream(self):
        profile = self.user.profile
        profile.ai_features_enabled = True
        profile.set_api_key("openai", "test-key")
        profile.save()
        stream = StreamingHttpResponse(
            iter([b"event: done\ndata: {}\n\n"]), content_type="text/event-stream"
        )
        with mock.patch(
            "core.api_v2.views.insights.stream_insights_response", return_value=stream
        ):
            response = self.client.post(
                "/api/v2/insights/stream/",
                {"message": "Summarise"},
                format="json",
                HTTP_ACCEPT="text/event-stream",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")


class ProfileApiGapTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="profile-api", password="secret")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_preferences_report_openai_source_and_background_metadata(self):
        profile = self.user.profile
        profile.ai_features_enabled = True
        profile.automatic_background = True
        profile.bing_background = True
        profile.set_api_key("openai", "test-key")
        profile.save()
        metadata = {
            "title": "Mountain lake",
            "description": "A still lake at sunrise",
            "copyright": "Photographer Example",
            "source_url": "https://www.bing.com/search?q=mountain+lake",
        }
        with mock.patch(
            "core.api_v2.views.me.bing_background",
            return_value="https://www.bing.com/image.jpg",
        ), mock.patch(
            "core.api_v2.views.me.bing_background_metadata", return_value=metadata
        ):
            response = self.client.get("/api/v2/me/preferences/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["openai_source"], "profile")
        self.assertEqual(
            response.json()["background"],
            {
                "mode": "bing",
                "image_url": "https://www.bing.com/image.jpg",
                "video_url": None,
                **metadata,
            },
        )

    def test_background_metadata_is_null_when_unavailable(self):
        response = self.client.get("/api/v2/me/preferences/")
        self.assertEqual(
            response.json()["background"],
            {
                "mode": "none",
                "image_url": None,
                "video_url": None,
                "title": None,
                "description": None,
                "copyright": None,
                "source_url": None,
            },
        )
        self.assertIsNone(response.json()["openai_source"])

    def test_related_similarity_preferences_and_bootstrap_contract(self):
        response = self.client.get("/api/v2/me/preferences/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {
                "value": response.json()["related_similarity"],
                "default": response.json()["related_similarity_default"],
                "min": response.json()["related_similarity_min"],
                "max": response.json()["related_similarity_max"],
            },
            {"value": None, "default": 0.45, "min": 0.25, "max": 0.60},
        )

        changed = self.client.patch(
            "/api/v2/me/preferences/", {"related_similarity": 0.38}, format="json"
        )
        self.assertEqual(changed.status_code, 200, changed.content)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.related_similarity, 0.38)

        invalid = self.client.patch(
            "/api/v2/me/preferences/", {"related_similarity": 0.61}, format="json"
        )
        self.assertEqual(invalid.status_code, 400)

        request = RequestFactory().get("/")
        request.user = self.user
        request.session = {}
        payload = bootstrap_payload(request)
        self.assertEqual(payload["profile"]["related_similarity"], 0.38)
        self.assertEqual(
            payload["semantic_search"],
            {
                "default_similarity": 0.45,
                "min_similarity": 0.25,
                "max_similarity": 0.60,
            },
        )

        reset = self.client.patch(
            "/api/v2/me/preferences/", {"related_similarity": None}, format="json"
        )
        self.assertEqual(reset.status_code, 200, reset.content)
        self.assertIsNone(reset.json()["related_similarity"])

    def test_social_accounts_report_password_safety(self):
        response = self.client.get("/api/v2/me/social-accounts/")
        self.assertTrue(response.json()["has_usable_password"])
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])
        response = self.client.get("/api/v2/me/social-accounts/")
        self.assertFalse(response.json()["has_usable_password"])

    def test_me_delete_and_pending_statuses_match_runtime(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        paths = schema["paths"]
        for path in (
            "/api/v2/me/avatar/",
            "/api/v2/me/background/",
            "/api/v2/me/api-keys/{provider}",
            "/api/v2/me/chatgpt-login/",
        ):
            with self.subTest(path=path):
                self.assertEqual(set(paths[path]["delete"]["responses"]), {"200"})
        self.assertEqual(
            set(paths["/api/v2/me/chatgpt-login/"]["get"]["responses"]),
            {"200", "202"},
        )

    def test_bootstrap_includes_insights_empty_asset(self):
        request = RequestFactory().get("/")
        request.user = self.user
        request.session = {}
        payload = bootstrap_payload(request)
        self.assertTrue(
            payload["static"]["insights_empty"].endswith(
                "/core/images/reddit_such_empty_transparent.png"
            )
        )


class InsightsApiGapTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="insights-api", password="secret")
        profile = self.user.profile
        profile.ai_features_enabled = True
        profile.set_api_key("gemini", "test-key")
        profile.save()
        self.work = Context.objects.create(user=self.user, name="Work")
        self.personal = Context.objects.create(user=self.user, name="Personal")
        self.work_project = Projects.objects.create(
            user=self.user, name="Work project", context=self.work
        )
        self.personal_project = Projects.objects.create(
            user=self.user, name="Personal project", context=self.personal
        )
        now = timezone.now().replace(microsecond=0)
        self.first = Sessions.objects.create(
            user=self.user,
            project=self.work_project,
            start_time=now - timedelta(days=2, hours=1),
            end_time=now - timedelta(days=2),
            note="Alpha",
            is_active=False,
        )
        self.last = Sessions.objects.create(
            user=self.user,
            project=self.personal_project,
            start_time=now - timedelta(hours=1),
            end_time=now,
            note="Beta",
            is_active=False,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        session = self.client.session
        session["active_context_id"] = str(self.work.pk)
        session.save()

    def test_selection_reuses_filters_and_all_contexts(self):
        all_contexts = self.client.get(
            "/api/v2/insights/selection/", {"context": "all"}
        )
        self.assertEqual(all_contexts.status_code, 200, all_contexts.content)
        self.assertEqual(all_contexts.json()["count"], 2)
        self.assertEqual(
            all_contexts.json()["first_date"],
            timezone.localdate(self.first.start_time).isoformat(),
        )
        self.assertEqual(
            all_contexts.json()["last_date"],
            timezone.localdate(self.last.end_time).isoformat(),
        )
        self.assertIsNone(all_contexts.json()["related"])

        one_context = self.client.get(
            "/api/v2/insights/selection/", {"context": self.work.pk}
        )
        self.assertEqual(one_context.json()["count"], 1)

    def test_selection_reports_related_unavailable(self):
        with mock.patch(
            "core.services.semantic_search.semantic_search_available", return_value=False
        ):
            response = self.client.get(
                "/api/v2/insights/selection/",
                {"search": "unmatched phrase", "related": "true", "context": "all"},
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["related"], "unavailable")

    def test_selection_and_stream_validate_and_forward_similarity(self):
        def search_with_outcome(queryset, _term, *, cutoff=None, outcome=None, **_kwargs):
            outcome.requested = True
            outcome.included = True
            outcome.cutoff = cutoff
            return queryset

        with mock.patch("core.utils.search_sessions", side_effect=search_with_outcome):
            selection = self.client.get(
                "/api/v2/insights/selection/",
                {
                    "search": "alpha",
                    "related": "true",
                    "similarity": "0.38",
                    "context": "all",
                },
            )
        self.assertEqual(selection.status_code, 200, selection.content)
        self.assertEqual(selection["X-Autumn-Related-Similarity"], "0.38")

        stream = StreamingHttpResponse(iter([b"event: done\ndata: {}\n\n"]))
        with mock.patch(
            "core.api_v2.views.insights.stream_insights_response",
            return_value=stream,
        ) as streamer:
            response = self.client.post(
                "/api/v2/insights/stream/",
                {"message": "Summarise", "similarity": 0.38},
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(streamer.call_args.args[0].POST["similarity"], "0.38")

        for method in ("get", "post"):
            with self.subTest(method=method):
                if method == "get":
                    invalid = self.client.get(
                        "/api/v2/insights/selection/", {"similarity": "0.61"}
                    )
                else:
                    invalid = self.client.post(
                        "/api/v2/insights/stream/",
                        {"message": "Summarise", "similarity": 0.61},
                        format="json",
                    )
                self.assertEqual(invalid.status_code, 400)

    def test_stream_accepts_all_or_null_context(self):
        stream = StreamingHttpResponse(iter([b"event: done\ndata: {}\n\n"]))
        for context in ("all", None):
            with self.subTest(context=context), mock.patch(
                "core.api_v2.views.insights.stream_insights_response",
                return_value=stream,
            ) as streamer:
                response = self.client.post(
                    "/api/v2/insights/stream/",
                    {"message": "Summarise", "context": context},
                    format="json",
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(streamer.call_args.args[0].POST["context"], "all")

    def test_chat_list_has_optional_limit_and_offset(self):
        for index in range(3):
            LLMChat.objects.create(
                user=self.user,
                title=f"Chat {index}",
                model="gemini:gemini-3.1-flash-lite",
            )
        default = self.client.get("/api/v2/insights/chats/")
        self.assertEqual(set(default.json()), {"groups"})
        self.assertEqual(
            sum(len(group["chats"]) for group in default.json()["groups"]), 3
        )

        page = self.client.get(
            "/api/v2/insights/chats/", {"limit": 1, "offset": 1}
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertEqual(page.json()["total"], 3)
        self.assertEqual(page.json()["limit"], 1)
        self.assertEqual(page.json()["offset"], 1)
        self.assertEqual(
            sum(len(group["chats"]) for group in page.json()["groups"]), 1
        )

    def test_options_report_openai_source_and_selection_is_not_an_mcp_tool(self):
        profile = self.user.profile
        profile.set_api_key("openai", "openai-key")
        profile.save()
        options = self.client.get("/api/v2/insights/options/")
        self.assertEqual(options.json()["openai_source"], "profile")

        schema = SchemaGenerator().get_schema(request=None, public=True)
        selection = schema["paths"]["/api/v2/insights/selection/"]["get"]
        self.assertEqual(selection["x-autumn-mcp"], "exclude")
        context_schema = next(
            parameter["schema"]
            for parameter in selection["parameters"]
            if parameter["name"] == "context"
        )
        self.assertIn({"type": "string", "enum": ["all"]}, context_schema["oneOf"])
