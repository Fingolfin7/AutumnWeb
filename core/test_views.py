from django.test import TestCase, Client
from django.utils import timezone
from core.models import Projects, SubProjects, Sessions
from datetime import datetime, timedelta
import json


class CoreViewsTestCase(TestCase):
    def setUp(self):
        # Create any necessary objects or data for your tests
        pass

    def test_start_view(self):
        client = Client()
        project = Projects.objects.create(name='TestProject')
        subproject = SubProjects.objects.create(name='TestSubProject', parent_project=project)
        data = {
            'project_name': 'TestProject',
            'subproject_names': ['TestSubProject']
        }
        response = client.post('/start/', data=json.dumps(data), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'success'})

    def test_stop_view(self):
        client = Client()
        session = Sessions.objects.create(project=Projects.objects.create(name='TestProject'), start_time=timezone.now())
        data = {
            'session_id': session.id,
            'note': 'Test Note'
        }
        response = client.post('/stop/', data=json.dumps(data), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'success'})

    def test_status_view(self):
        client = Client()
        response = client.get('/status/')
        self.assertEqual(response.status_code, 200)
        # Add more assertions based on your expected response

    def test_create_project_view(self):
        client = Client()
        data = {
            'name': 'TestProject',
            # 'start_date': '2024-01-01',
            # 'last_updated': '2024-01-01',
            'total_time': 0.0,
            'status': 'active',
        }
        response = client.post('/create_project/', data=json.dumps(data), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'success'})

    def test_get_projects_view(self):
        client = Client()
        response = client.get('/get_projects/')
        self.assertEqual(response.status_code, 200)
        # Add more assertions based on your expected response

    def test_get_session_logs_view(self):
        client = Client()
        response = client.get('/get_session_logs/')
        self.assertEqual(response.status_code, 200)
        # Add more assertions based on your expected response

        # Test with query parameters
        start_date = (timezone.now() - timedelta(days=5)).strftime('%m-%d-%Y')
        end_date = timezone.now().strftime('%m-%d-%Y')
        response_with_params = client.get(f'/get_session_logs/?start_date={start_date}&end_date={end_date}')
        self.assertEqual(response_with_params.status_code, 200)
        # Add more assertions based on your expected response
