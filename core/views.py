from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from datetime import datetime, timedelta
from core.models import *
from core.serializers import ProjectSerializer, SubProjectSerializer, SessionSerializer


@api_view(['POST'])
def start(request):
    project_name = request.data['project_name']
    subproject_names = request.data.get('subproject_names', [])

    project = get_object_or_404(Projects, name=project_name)
    subprojects = SubProjects.objects.filter(name__in=subproject_names)

    session = Sessions(
        project=project,
        start_time=timezone.now(),
        end_time=None,
        note='',
    )
    session.save()
    session.subprojects.set(subprojects)

    return Response({'status': 'success'})


@api_view(['POST'])
def stop(request):
    session_id = request.data['session_id']
    end_time = timezone.now()
    note = request.data.get('note', '')

    session = get_object_or_404(Sessions, id=session_id, is_active=True)
    session.end_time = end_time
    session.is_active = False
    session.note = note
    session.save()

    return Response({'status': 'success'})


@api_view(['GET'])
def status(request):
    sessions = Sessions.objects.filter(is_active=True)
    serializer = SessionSerializer(sessions, many=True)
    return Response(serializer.data)


@api_view(['POST'])
def create_project(request):
    name = request.data['name']
    start_date = request.data.get('start_date', timezone.now().date())
    last_updated = request.data.get('last_updated', timezone.now().date())
    total_time = request.data.get('total_time', 0.0)
    _status = request.data.get('status', 'active')

    project = Projects(
        name=name,
        start_date=start_date,
        last_updated=last_updated,
        total_time=total_time,
        status=_status,
    )
    project.save()

    return Response({'status': 'success'})


@api_view(['GET'])
def get_projects(request):
    _status = request.query_params.get('status', None)

    if _status is None:
        projects = Projects.objects.all()
    else:
        projects = Projects.objects.filter(status=_status)

    serializer = ProjectSerializer(projects, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def get_session_logs(request):
    if 'start_date' in request.query_params and 'end_date' in request.query_params:
        start_date = timezone.make_aware(
            datetime.strptime(request.query_params['start_date'], '%m-%d-%Y')
        )
        end_date = timezone.make_aware(
            datetime.strptime(request.query_params['end_date'], '%m-%d-%Y')
        )
    elif 'start_date' in request.query_params:
        start_date = timezone.make_aware(
            datetime.strptime(request.query_params['start_date'], '%m-%d-%Y')
        )
        end_date = timezone.now()
    else:
        start_date = timezone.now() - timedelta(days=120)
        end_date = timezone.now()

    sessions = Sessions.objects.filter(is_active=False, end_time__range=[start_date, end_date])

    serializer = SessionSerializer(sessions, many=True)
    return Response(serializer.data)

