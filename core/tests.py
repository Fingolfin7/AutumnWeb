from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from core.models import Projects, SubProjects, Sessions
from django.contrib.auth.models import User
from datetime import timedelta



class UpdateSessionTests(TestCase):
    def setUp(self):
        # Create a user
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.login(username='testuser', password='password')

        # Create a project
        self.project = Projects.objects.create(user=self.user, name='Test Project')

        # Create subprojects
        self.subproject1 = SubProjects.objects.create(
            user=self.user, name='Subproject 1', parent_project=self.project
        )
        self.subproject2 = SubProjects.objects.create(
            user=self.user, name='Subproject 2', parent_project=self.project
        )

        # Create an initial session
        self.session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            is_active=False
        )
        self.session.subprojects.add(self.subproject1)

    def test_update_session_updates_total_time(self):
        # Verify initial total times
        self.project.refresh_from_db()
        self.subproject1.refresh_from_db()
        self.subproject2.refresh_from_db()
        self.assertAlmostEqual(self.project.total_time, 60.0, places=2)  # 1 hour, with 2 decimal precision
        self.assertAlmostEqual(self.subproject1.total_time, 60.0, places=2)
        self.assertAlmostEqual(self.subproject2.total_time, 0.0, places=2)

        # Prepare data for updating the session
        new_start_time = timezone.now() - timedelta(hours=3)
        new_end_time = timezone.now() - timedelta(hours=2)
        update_data = {
            'project_name': self.project.name,
            'start_time': new_start_time.strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': new_end_time.strftime('%Y-%m-%d %H:%M:%S'),
            'note': 'Updated session',
            'subprojects': [self.subproject2.name],  # Change subproject
        }

        # Call the update_session view
        response = self.client.post(
            reverse('update_session', args=[self.session.id]),
            data=update_data
        )

        self.assertEqual(response.status_code, 302)  # Redirect after successful update

        self.project.refresh_from_db()
        self.subproject1.refresh_from_db()
        self.subproject2.refresh_from_db()

        # Verify updated total times
        self.assertAlmostEqual(self.project.total_time, 60.0, places=2)  # Still 1 hour, but reassigned
        self.assertAlmostEqual(self.subproject1.total_time, 0.0, places=2)
        self.assertAlmostEqual(self.subproject2.total_time, 60.0, places=2)


class StopTimerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.login(username='testuser', password='password')
        self.project = Projects.objects.create(user=self.user, name='Test Project')
        self.subproject = SubProjects.objects.create(user=self.user, name='Subproject', parent_project=self.project)

        # Create an active session (with no end time and is_active=True)
        self.session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=timezone.now() - timedelta(hours=1),
            is_active = True
        )
        self.session.subprojects.add(self.subproject)

    def test_stop_timer(self):
        response = self.client.post(reverse('stop_timer', args=[self.session.id]))
        self.assertEqual(response.status_code, 302)  # Expecting a redirect

        # Refresh session and project from DB
        self.session.refresh_from_db()
        self.project.refresh_from_db()
        self.subproject.refresh_from_db()

        # Verify session is stopped: is_active should be False and end_time not None
        self.assertFalse(self.session.is_active)
        self.assertIsNotNone(self.session.end_time)

        # Check that audit has updated total time; assume the duration is computed correctly.
        expected_duration = self.session.duration
        self.assertAlmostEqual(self.project.total_time, expected_duration, places=2)
        self.assertAlmostEqual(self.subproject.total_time, expected_duration, places=2)



class DeleteSessionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.login(username='testuser', password='password')
        self.project = Projects.objects.create(user=self.user, name='Test Project')

        self.subproject1 = SubProjects.objects.create(
            user=self.user, name='Subproject 1', parent_project=self.project
        )
        self.subproject2 = SubProjects.objects.create(
            user=self.user, name='Subproject 2', parent_project=self.project
        )

        self.session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            is_active=False
        )

        self.session.subprojects.add(self.subproject1, self.subproject2)

    def test_delete_session(self):

        self.project.refresh_from_db()
        self.subproject1.refresh_from_db()
        self.subproject2.refresh_from_db()

        # Verify initial total times
        self.assertAlmostEqual(self.project.total_time, 60.0, places=2)  # 1 hour, with 2 decimal precision
        self.assertAlmostEqual(self.subproject1.total_time, 60.0, places=2)
        self.assertAlmostEqual(self.subproject2.total_time, 60.0, places=2)

        response = self.client.post(reverse('delete_session', args=[self.session.id]))
        self.assertEqual(response.status_code, 302)  # Expecting a redirect

        # Verify the session no longer exists
        session_exists = Sessions.objects.filter(id=self.session.id).exists()
        self.assertFalse(session_exists)

        self.project.refresh_from_db()
        self.subproject1.refresh_from_db()
        self.subproject2.refresh_from_db()

        # Verify the project's and subprojects' total time is updated after deletion
        self.assertAlmostEqual(self.project.total_time, 0.0, places=2)
        self.assertAlmostEqual(self.subproject1.total_time, 0.0, places=2)
        self.assertAlmostEqual(self.subproject2.total_time, 0.0, places=2)


