"""Smoke tests for the Focus Desk shell (core/templates/core/base.html).

The shell is pure template, so the realistic failure mode is a typo'd
``{% url %}`` name or a tag that blows up for a given user state. Rendering it
directly catches both before any page depends on it.
"""

from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase


class FocusDeskShellTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="finrod", email="finrod@example.com", password="pw"
        )

    def _render(self, user):
        request = RequestFactory().get("/")
        request.user = user
        # the active_context processor reads request.session, which
        # RequestFactory does not attach
        request.session = SessionStore()
        return render_to_string("core/base.html", {"user": user}, request=request)

    def test_renders_for_authenticated_user(self):
        html = self._render(self.user)
        self.assertIn('class="app"', html)
        self.assertIn("focus_desk.css", html)
        # every {% url %} in the shell resolved
        self.assertNotIn("{% url", html)

    def test_does_not_load_the_legacy_stylesheet(self):
        """The two design systems share class names; loading both would make
        the page render as a collision of the old and new UI."""
        html = self._render(self.user)
        self.assertNotIn("css/style.css", html)
        self.assertNotIn("css/colours.css", html)

    def test_renders_for_anonymous_user(self):
        from django.contrib.auth.models import AnonymousUser

        html = self._render(AnonymousUser())
        self.assertIn('class="app"', html)
        # nav and sheet are for signed-in users only
        self.assertNotIn('class="tabbar"', html)
        self.assertNotIn('id="moreSheet"', html)

    def test_nav_exposes_every_primary_destination(self):
        html = self._render(self.user)
        for label in ("Home", "Projects", "Timers", "Sessions", "Charts"):
            self.assertIn(">{}<".format(label), html)

    def test_backdrop_stays_inactive_without_a_photo(self):
        """bg-active drives the ::before/::after layers; it must not be set
        when the user has no backdrop configured."""
        html = self._render(self.user)
        self.assertNotIn("bg-active", html)
