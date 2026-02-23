from django.contrib import admin
from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Commitment, Context, Projects, Sessions, SubProjects, Tag


class AdminRegistrationTests(TestCase):
    def test_core_models_registered_in_admin(self):
        for model in (Projects, SubProjects, Sessions, Context, Tag, Commitment):
            self.assertIn(model, admin.site._registry)

    def test_user_admin_includes_aggregation_columns(self):
        user_admin = admin.site._registry[User]
        for column in ("project_count", "session_count", "commitment_count", "total_logged_minutes"):
            self.assertIn(column, user_admin.list_display)

    def test_user_admin_has_audit_action(self):
        user_admin = admin.site._registry[User]
        action_names = [getattr(action, "__name__", str(action)) for action in user_admin.actions]
        self.assertIn("run_audit_for_selected_users", action_names)
