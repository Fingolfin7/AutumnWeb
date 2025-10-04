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


class MergeProjectsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.login(username='testuser', password='password')
        
        # Create two projects to merge
        self.project1 = Projects.objects.create(
            user=self.user, 
            name='Project A',
            description='Description for Project A',
            total_time=120.0  # 2 hours
        )
        self.project2 = Projects.objects.create(
            user=self.user, 
            name='Project B',
            description='Description for Project B',
            total_time=180.0  # 3 hours
        )
        
        # Create subprojects for each project
        self.subproject1a = SubProjects.objects.create(
            user=self.user, 
            name='Design',
            parent_project=self.project1,
            total_time=60.0
        )
        self.subproject1b = SubProjects.objects.create(
            user=self.user, 
            name='Development',
            parent_project=self.project1,
            total_time=60.0
        )
        self.subproject2a = SubProjects.objects.create(
            user=self.user, 
            name='Design',  # Same name as project1's subproject
            parent_project=self.project2,
            total_time=90.0
        )
        self.subproject2b = SubProjects.objects.create(
            user=self.user, 
            name='Testing',
            parent_project=self.project2,
            total_time=90.0
        )
        
        # Create sessions for each project
        self.session1 = Sessions.objects.create(
            user=self.user,
            project=self.project1,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            is_active=False
        )
        self.session1.subprojects.add(self.subproject1a)
        
        self.session2 = Sessions.objects.create(
            user=self.user,
            project=self.project2,
            start_time=timezone.now() - timedelta(hours=3),
            end_time=timezone.now() - timedelta(hours=2),
            is_active=False
        )
        self.session2.subprojects.add(self.subproject2a)

    def test_merge_projects_success(self):
        """Test successful project merge"""
        response = self.client.post(reverse('merge_projects'), {
            'project1': 'Project A',
            'project2': 'Project B',
            'new_project_name': 'Merged Project'
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect after success
        
        # Check that original projects are deleted
        self.assertFalse(Projects.objects.filter(name='Project A').exists())
        self.assertFalse(Projects.objects.filter(name='Project B').exists())
        
        # Check that merged project exists
        merged_project = Projects.objects.get(name='Merged Project')
        self.assertEqual(merged_project.user, self.user)
        self.assertIn('Merged from \'Project A\' and \'Project B\'', merged_project.description)
        self.assertIn('--- Project A Description ---', merged_project.description)
        self.assertIn('--- Project B Description ---', merged_project.description)
        
        # Check that sessions were moved
        self.assertEqual(merged_project.sessions.count(), 2)
        self.assertIn(self.session1, merged_project.sessions.all())
        self.assertIn(self.session2, merged_project.sessions.all())
        
        # Check that subprojects were moved (with conflict resolution)
        subproject_names = [sp.name for sp in merged_project.subprojects.all()]
        self.assertIn('Design', subproject_names)  # From project1
        self.assertIn('Design (Project B)', subproject_names)  # Renamed from project2
        self.assertIn('Development', subproject_names)
        self.assertIn('Testing', subproject_names)
        
        # Check total time was recalculated (based on actual session durations)
        # Each session is 1 hour (60 minutes), so 2 sessions = 120 minutes
        self.assertAlmostEqual(merged_project.total_time, 120.0, places=2)

    def test_merge_projects_duplicate_name(self):
        """Test merge fails when new project name already exists"""
        # Create a project with the target name
        Projects.objects.create(user=self.user, name='Merged Project')
        
        response = self.client.post(reverse('merge_projects'), {
            'project1': 'Project A',
            'project2': 'Project B',
            'new_project_name': 'Merged Project'
        })
        
        self.assertEqual(response.status_code, 200)  # Form with errors
        self.assertContains(response, 'You already have a project with this name')
        
        # Check that original projects still exist
        self.assertTrue(Projects.objects.filter(name='Project A').exists())
        self.assertTrue(Projects.objects.filter(name='Project B').exists())

    def test_merge_projects_same_project(self):
        """Test merge fails when trying to merge a project with itself"""
        response = self.client.post(reverse('merge_projects'), {
            'project1': 'Project A',
            'project2': 'Project A',
            'new_project_name': 'Merged Project'
        })
        
        self.assertEqual(response.status_code, 200)  # Form with errors
        self.assertContains(response, 'Cannot merge a project with itself')

    def test_merge_projects_invalid_form(self):
        """Test merge fails with invalid form data"""
        response = self.client.post(reverse('merge_projects'), {
            'project1': 'Project A',
            # Missing project2 and new_project_name
        })
        
        self.assertEqual(response.status_code, 200)  # Form with errors
        self.assertContains(response, 'Invalid form data')


class MergeSubProjectsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.login(username='testuser', password='password')
        
        # Create a parent project
        self.parent_project = Projects.objects.create(
            user=self.user, 
            name='Parent Project',
            total_time=240.0  # 4 hours
        )
        
        # Create two subprojects to merge
        self.subproject1 = SubProjects.objects.create(
            user=self.user, 
            name='Design',
            parent_project=self.parent_project,
            description='Design subproject description',
            total_time=120.0  # 2 hours
        )
        self.subproject2 = SubProjects.objects.create(
            user=self.user, 
            name='UI',
            parent_project=self.parent_project,
            description='UI subproject description',
            total_time=120.0  # 2 hours
        )
        
        # Create sessions for each subproject
        self.session1 = Sessions.objects.create(
            user=self.user,
            project=self.parent_project,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            is_active=False
        )
        self.session1.subprojects.add(self.subproject1)
        
        self.session2 = Sessions.objects.create(
            user=self.user,
            project=self.parent_project,
            start_time=timezone.now() - timedelta(hours=3),
            end_time=timezone.now() - timedelta(hours=2),
            is_active=False
        )
        self.session2.subprojects.add(self.subproject2)

    def test_merge_subprojects_success(self):
        """Test successful subproject merge"""
        response = self.client.post(reverse('merge_subprojects', args=[self.parent_project.id]), {
            'subproject1': 'Design',
            'subproject2': 'UI',
            'new_subproject_name': 'Design & UI'
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect after success
        
        # Check that original subprojects are deleted
        self.assertFalse(SubProjects.objects.filter(name='Design').exists())
        self.assertFalse(SubProjects.objects.filter(name='UI').exists())
        
        # Check that merged subproject exists
        merged_subproject = SubProjects.objects.get(name='Design & UI')
        self.assertEqual(merged_subproject.user, self.user)
        self.assertEqual(merged_subproject.parent_project, self.parent_project)
        self.assertIn('Merged from \'Design\' and \'UI\'', merged_subproject.description)
        self.assertIn('--- Design Description ---', merged_subproject.description)
        self.assertIn('--- UI Description ---', merged_subproject.description)
        
        # Check that sessions were moved
        self.assertEqual(merged_subproject.sessions.count(), 2)
        self.assertIn(self.session1, merged_subproject.sessions.all())
        self.assertIn(self.session2, merged_subproject.sessions.all())
        
        # Check total time was recalculated (based on actual session durations)
        # Each session is 1 hour (60 minutes), so 2 sessions = 120 minutes
        self.assertAlmostEqual(merged_subproject.total_time, 120.0, places=2)

    def test_merge_subprojects_duplicate_name(self):
        """Test merge fails when new subproject name already exists"""
        # Create a subproject with the target name
        SubProjects.objects.create(
            user=self.user, 
            name='Design & UI',
            parent_project=self.parent_project
        )
        
        response = self.client.post(reverse('merge_subprojects', args=[self.parent_project.id]), {
            'subproject1': 'Design',
            'subproject2': 'UI',
            'new_subproject_name': 'Design & UI'
        })
        
        self.assertEqual(response.status_code, 200)  # Form with errors
        self.assertContains(response, 'You already have a subproject with this name in this project')
        
        # Check that original subprojects still exist
        self.assertTrue(SubProjects.objects.filter(name='Design').exists())
        self.assertTrue(SubProjects.objects.filter(name='UI').exists())

    def test_merge_subprojects_same_subproject(self):
        """Test merge fails when trying to merge a subproject with itself"""
        response = self.client.post(reverse('merge_subprojects', args=[self.parent_project.id]), {
            'subproject1': 'Design',
            'subproject2': 'Design',
            'new_subproject_name': 'Merged Subproject'
        })
        
        self.assertEqual(response.status_code, 200)  # Form with errors
        self.assertContains(response, 'Cannot merge a subproject with itself')

    def test_merge_subprojects_invalid_form(self):
        """Test merge fails with invalid form data"""
        response = self.client.post(reverse('merge_subprojects', args=[self.parent_project.id]), {
            'subproject1': 'Design',
            # Missing subproject2 and new_subproject_name
        })
        
        self.assertEqual(response.status_code, 200)  # Form with errors
        self.assertContains(response, 'Invalid form data')


class MergeProjectsAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.login(username='testuser', password='password')
        
        # Create two projects to merge
        self.project1 = Projects.objects.create(
            user=self.user, 
            name='Project A',
            description='Description for Project A',
            total_time=120.0
        )
        self.project2 = Projects.objects.create(
            user=self.user, 
            name='Project B',
            description='Description for Project B',
            total_time=180.0
        )

    def test_merge_projects_api_success(self):
        """Test successful project merge via API"""
        response = self.client.post('/api/merge_projects/', {
            'project1': 'Project A',
            'project2': 'Project B',
            'new_project_name': 'Merged Project'
        }, content_type='application/json')
        
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn('Successfully merged', data['message'])
        self.assertEqual(data['project']['name'], 'Merged Project')
        
        # Check that original projects are deleted
        self.assertFalse(Projects.objects.filter(name='Project A').exists())
        self.assertFalse(Projects.objects.filter(name='Project B').exists())

    def test_merge_projects_api_missing_parameters(self):
        """Test API fails with missing parameters"""
        response = self.client.post('/api/merge_projects/', {
            'project1': 'Project A',
            # Missing project2 and new_project_name
        }, content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('required', data['error'])

    def test_merge_projects_api_duplicate_name(self):
        """Test API fails when new project name already exists"""
        Projects.objects.create(user=self.user, name='Merged Project')
        
        response = self.client.post('/api/merge_projects/', {
            'project1': 'Project A',
            'project2': 'Project B',
            'new_project_name': 'Merged Project'
        }, content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('already exists', data['error'])


class MergeSubProjectsAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.login(username='testuser', password='password')
        
        # Create a parent project
        self.parent_project = Projects.objects.create(
            user=self.user, 
            name='Parent Project'
        )
        
        # Create two subprojects to merge
        self.subproject1 = SubProjects.objects.create(
            user=self.user, 
            name='Design',
            parent_project=self.parent_project,
            total_time=120.0
        )
        self.subproject2 = SubProjects.objects.create(
            user=self.user, 
            name='UI',
            parent_project=self.parent_project,
            total_time=120.0
        )

    def test_merge_subprojects_api_success(self):
        """Test successful subproject merge via API"""
        response = self.client.post('/api/merge_subprojects/', {
            'subproject1': 'Design',
            'subproject2': 'UI',
            'new_subproject_name': 'Design & UI',
            'project_id': self.parent_project.id
        }, content_type='application/json')
        
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn('Successfully merged', data['message'])
        self.assertEqual(data['subproject']['name'], 'Design & UI')
        
        # Check that original subprojects are deleted
        self.assertFalse(SubProjects.objects.filter(name='Design').exists())
        self.assertFalse(SubProjects.objects.filter(name='UI').exists())

    def test_merge_subprojects_api_missing_parameters(self):
        """Test API fails with missing parameters"""
        response = self.client.post('/api/merge_subprojects/', {
            'subproject1': 'Design',
            # Missing other parameters
        }, content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('required', data['error'])

    def test_merge_subprojects_api_duplicate_name(self):
        """Test API fails when new subproject name already exists"""
        SubProjects.objects.create(
            user=self.user, 
            name='Design & UI',
            parent_project=self.parent_project
        )
        
        response = self.client.post('/api/merge_subprojects/', {
            'subproject1': 'Design',
            'subproject2': 'UI',
            'new_subproject_name': 'Design & UI',
            'project_id': self.parent_project.id
        }, content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('already exists', data['error'])


