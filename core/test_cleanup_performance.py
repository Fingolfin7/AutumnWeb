from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import Commitment, Context, Projects, Sessions, SubProjects, Tag


class ListQueryCountTests(TestCase):
    """The v2 sessions and projects lists issue the same queries for 2 rows or 8."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="query-cleanup")
        self.context = Context.objects.create(user=self.user, name="Work")
        self.tag = Tag.objects.create(user=self.user, name="focused")
        self.client.force_login(self.user)

    def _add(self, count):
        for index in range(count):
            project = Projects.objects.create(
                user=self.user, name=f"Project {len(Projects.objects.all())}", context=self.context
            )
            project.tags.add(self.tag)
            subproject = SubProjects.objects.create(
                user=self.user, parent_project=project, name="Sub"
            )
            end = timezone.now() - timedelta(minutes=index)
            session = Sessions.objects.create(
                user=self.user,
                project=project,
                start_time=end - timedelta(minutes=30),
                end_time=end,
            )
            session.subprojects.add(subproject)
        Commitment.objects.create(
            user=self.user,
            project=project,
            commitment_type="sessions",
            period="weekly",
            target=2,
        )

    def _queries(self, path):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return len(queries)

    def test_lists_do_not_query_per_row(self):
        for path in ("/api/v2/sessions/", "/api/v2/projects/"):
            Sessions.objects.all().delete()
            Projects.objects.all().delete()
            self._add(2)
            few = self._queries(path)
            self._add(6)
            many = self._queries(path)
            self.assertEqual(few, many, path)
