"""APOD's new feed supplies a still image for photos, GIFs, and videos."""

from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.templatetags import background_images as apod


class ApodBackgroundTests(TestCase):
    def setUp(self):
        apod._cached_nasa_data = {}
        apod._nasa_expiry = timezone.now() - timedelta(days=1)

    def tearDown(self):
        apod._cached_nasa_data = {}
        apod._nasa_expiry = timezone.now() - timedelta(days=1)

    def _feed(self, entry):
        response = Mock()
        response.json.return_value = [entry]
        response.raise_for_status.return_value = None
        return patch.object(apod.requests, "get", return_value=response)

    def _render_shell(self):
        user = User.objects.create_user(username="apod-viewer", password="pw")
        profile = user.profile
        profile.automatic_background = True
        profile.nasa_apod_background = True
        profile.save()
        request = RequestFactory().get("/")
        request.user = user
        request.session = SessionStore()
        return render_to_string("core/base.html", {"user": user}, request=request)

    def test_image_uses_hdurl_not_the_new_api_permalink(self):
        entry = {
            "date": "2026-10-01", "title": "Moon &amp; Etna", "media_type": "image",
            "hdurl": "https://assets.science.nasa.gov/moon.jpg?w=1600&h=1000",
            "url": "https://science.nasa.gov/image-article/moon/",
            "explanation": "<strong>Explanation:</strong> A moon.",
        }
        with self._feed(entry) as get:
            media = apod.nasa_apod_media()
            html = self._render_shell()
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.kwargs["params"], {"per_page": 1})
        self.assertEqual(media["title"], "Moon & Etna")
        self.assertEqual(media["explanation"], "Explanation: A moon.")
        self.assertIn("moon.jpg", html)
        self.assertIn("bg-active", html)
        self.assertNotIn('class="workspace-bg-video"', html)


    def test_direct_video_uses_poster_and_playable_source(self):
        entry = {
            "date": "2026-09-13", "media_type": "video",
            "hdurl": "https://assets.science.nasa.gov/comet.png",
            "permalink": "https://science.nasa.gov/image-article/comet/",
            "basic_html": '<video controls><source src="https://assets.science.nasa.gov/comet.mp4" type="video/mp4"></video>',
        }
        with self._feed(entry):
            media = apod.nasa_apod_media()
            html = self._render_shell()
        self.assertEqual(media["video_url"], "https://assets.science.nasa.gov/comet.mp4")
        self.assertIn('class="workspace-bg-video"', html)
        self.assertIn('poster="https://assets.science.nasa.gov/comet.png"', html)
        self.assertIn('src="https://assets.science.nasa.gov/comet.mp4"', html)


    def test_failed_refresh_keeps_last_good_background(self):
        apod._cached_nasa_data = {"image_url": "https://assets.science.nasa.gov/last.jpg"}
        with patch.object(apod.requests, "get", side_effect=ConnectionError("offline")):
            self.assertEqual(apod.nasa_apod_background(), "https://assets.science.nasa.gov/last.jpg")
