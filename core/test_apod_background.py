"""APOD's new feed supplies a still image for photos, GIFs, and videos."""

from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse
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

    def test_gif_remains_an_animated_image_url(self):
        with self._feed({"media_type": "image", "hdurl": "https://assets.science.nasa.gov/sky.gif"}):
            media = apod.nasa_apod_media()
        self.assertTrue(media["image_url"].endswith("sky.gif"))
        self.assertEqual(media["video_url"], "")

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

    def test_embedded_video_keeps_its_poster_without_inline_source(self):
        entry = {
            "media_type": "video", "hdurl": "https://assets.science.nasa.gov/still.jpg",
            "permalink": "https://science.nasa.gov/image-article/embedded/",
            "basic_html": '<iframe src="https://www.youtube.com/embed/example"></iframe>',
        }
        with self._feed(entry):
            media = apod.nasa_apod_media()
            html = self._render_shell()
        self.assertEqual(media["video_url"], "")
        self.assertIn("still.jpg", html)
        self.assertNotIn('class="workspace-bg-video"', html)

    def test_profile_links_to_the_video_and_labels_the_poster_download(self):
        entry = {
            "media_type": "video", "hdurl": "https://assets.science.nasa.gov/comet.png",
            "permalink": "https://science.nasa.gov/image-article/comet/",
            "basic_html": '<video><source src="https://assets.science.nasa.gov/comet.mp4"></video>',
        }
        user = User.objects.create_user(username="apod-profile", password="pw")
        profile = user.profile
        profile.automatic_background = True
        profile.nasa_apod_background = True
        profile.save()
        self.client.force_login(user)
        with self._feed(entry):
            body = self.client.get(reverse("profile")).content.decode()
        self.assertIn("Watch video at NASA", body)
        self.assertIn("Download preview", body)
        self.assertIn("https://science.nasa.gov/image-article/comet/", body)

    def test_missing_video_poster_uses_a_recent_apod_photo(self):
        latest = Mock()
        latest.json.return_value = [{
            "media_type": "video", "hdurl": None,
            "permalink": "https://science.nasa.gov/image-article/video/",
        }]
        recent = Mock()
        recent.json.return_value = [
            {"media_type": "video", "hdurl": None},
            {"media_type": "image", "hdurl": "https://assets.science.nasa.gov/previous.jpg"},
        ]
        with patch.object(apod.requests, "get", side_effect=[latest, recent]) as get:
            media = apod.nasa_apod_media()
        self.assertEqual(get.call_count, 2)
        self.assertEqual(media["image_url"], "https://assets.science.nasa.gov/previous.jpg")
        self.assertEqual(media["page_url"], "https://science.nasa.gov/image-article/video/")

    def test_failed_refresh_keeps_last_good_background(self):
        apod._cached_nasa_data = {"image_url": "https://assets.science.nasa.gov/last.jpg"}
        with patch.object(apod.requests, "get", side_effect=ConnectionError("offline")):
            self.assertEqual(apod.nasa_apod_background(), "https://assets.science.nasa.gov/last.jpg")
