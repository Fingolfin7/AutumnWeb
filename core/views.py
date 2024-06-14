from django.db.models import QuerySet
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from datetime import datetime, timedelta
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from core.models import *
from core.models import Projects, SubProjects, Sessions
from core.serializers import ProjectSerializer, SubProjectSerializer, SessionSerializer


def home(request):
    return render(request, 'core/home.html')


class ProjectsListView(ListView):
    model = Projects
    template_name = 'core/projects_list.html'
    context_object_name = 'projects'
    ordering = ['name']


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Projects'

        return context

    def get_queryset(self):
        return Projects.objects.all()


class TimerListView(ListView):
    model = Sessions
    template_name = 'core/timers.html'
    context_object_name = 'timers'
    ordering = ['-start_time']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Timers'

        return context

    def get_queryset(self):
        return Sessions.objects.filter(is_active=True)



# api endpoints to create, list, and delete projects, subprojects, and sessions

def update_time_totals(session: Sessions, is_delete=False):
    """
    Update the total time for the project and subprojects associated with the given session
    :param session: a session object
    :param is_delete: a boolean indicating whether the session is being deleted (if so, the time will be subtracted)
    :return: True if the session duration was updated, False otherwise
    """
    if session.duration is None:
        return False

    update_value = session.duration

    if is_delete:
        update_value *= -1

    try:
        parent_project = session.project
        parent_project.total_time += update_value
        parent_project.save()

        for sub_project in session.subprojects.all():
            sub_project.total_time += update_value
            sub_project.save()

        return True
    except ...:
        return False


def in_window(data: QuerySet, start: datetime | str = None, end: datetime | str = None) -> list:
    """
    Return a list of items in the data set that fall within the given window

    :param data: a queryset of items
    :param start: the start of the window (%m-%d-%Y) or (%m-%d-%Y %H:%M:%S)
    :param end: the end of the window (%m-%d-%Y) or (%m-%d-%Y %H:%M:%S)

    :return: a list of items that fall within the window
    """

    def parse_date_or_datetime(date_str):
        try:
            return datetime.strptime(date_str, '%m-%d-%Y')
        except ValueError:
            return datetime.strptime(date_str, '%m-%d-%Y %H:%M:%S')

    if isinstance(start, str):
        start = parse_date_or_datetime(start)
    if isinstance(end, str):
        end = parse_date_or_datetime(end)

    # can't use the filter property of a QuerySet because it doesn't support the get_start and get_end properties
    try:
        if end:
            return [item for item in data if item.get_start >= start and item.get_end <= end]
        else:
            return [item for item in data if item.get_start >= start]
    except TypeError:
        start = timezone.make_aware(start)
        if end:
            end = timezone.make_aware(end)
            return [item for item in data if item.get_start >= start and item.get_end <= end]
        else:
            return [item for item in data if item.get_start >= start]


def filter_by_projects(data: QuerySet[Projects | SubProjects | Sessions], name: str = None,
                       names: list[str] = None) -> QuerySet:
    """
    filter a queryset of data and return a list of items that match the given name or names
    :param data: a queryset of data
    :param name: if you need to filter for 1 name
    :param names: if you need to filter for multiple names
    :return: list of items that match the given name or names
    """
    item = data[0]  # get the first item in the queryset to determine the type of data
    if name:
        if isinstance(item, Projects):
            return data.filter(name=name)
        elif isinstance(item, SubProjects):
            return data.filter(parent_project__name=name)
        elif isinstance(item, Sessions):
            return data.filter(project__name=name)
    elif names:
        if isinstance(item, Projects):
            return data.filter(name__in=names)
        elif isinstance(item, SubProjects):
            return data.filter(parent_project__name__in=names)
        elif isinstance(item, Sessions):
            return data.filter(project__name__in=names)
    else:
        return data


@api_view(['POST'])
def create_project(request):
    serializer = ProjectSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors)


@api_view(['GET'])
def list_projects(request):
    if 'start' in request.query_params and 'end' in request.query_params:
        start = request.query_params['start']
        end = request.query_params['end']
        projects = Projects.objects.all()
        projects = in_window(projects, start, end)
    elif 'start' in request.query_params:
        start = request.query_params['start']
        projects = Projects.objects.all()
        projects = in_window(projects, start)
    else:
        projects = Projects.objects.all()

    serializer = ProjectSerializer(projects, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def get_project(request, project_name):
    project = get_object_or_404(Projects, name=project_name)
    serializer = ProjectSerializer(project)
    return Response(serializer.data)


@api_view(['DELETE'])
def delete_project(request, project_name):
    project = get_object_or_404(Projects, name=project_name)
    project.delete()
    return Response(status=204)


@api_view(['POST'])
def create_subproject(request):
    # check if the parent project exists
    if not Projects.objects.filter(name=request.data['parent_project']).exists():
        return Response({'error': 'Parent project ' + request.data['parent_project'] + ' does not exist'})

    serializer = SubProjectSerializer(data=request.data)

    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)

    return Response(serializer.errors)


@api_view(['GET'])
def list_subprojects(request, project_name):
    subprojects = SubProjects.objects.filter(parent_project__name=project_name)
    serializer = SubProjectSerializer(subprojects, many=True)
    return Response(serializer.data)


@api_view(['DELETE'])
def delete_subproject(request, project_name, subproject_name):
    subproject = get_object_or_404(SubProjects, name=subproject_name, parent_project__name=project_name)
    subproject.delete()
    return Response(status=204)  # status 204 means no content, i.e. the subproject was deleted successfully


@api_view(['POST'])
def start_session(request):
    project = get_object_or_404(Projects, name=request.data['project'])
    subprojects = [get_object_or_404(SubProjects, name=subproject_name, parent_project=project)
                   for subproject_name in request.data['subprojects']]

    session = Sessions.objects.create(
        project=project,
        # subprojects=subprojects,
        start_time=timezone.now(),
        is_active=True
    )

    for subproject in subprojects:
        session.subprojects.add(subproject)

    session.save()

    return Response(status=201)


@api_view(['POST'])
def end_session(request):
    """
    End an active session and update the associated project and subproject time tallies
    :param request:
    :return:
    """
    session = get_object_or_404(Sessions, pk=request.data['session_id'])
    session.end_time = timezone.now()
    session.is_active = False

    if 'note' in request.data:
        session.note = request.data['note']

    session.save()

    update_time_totals(session)

    return Response(status=200)


@api_view(['POST'])
def log_session(request):
    project = get_object_or_404(Projects, name=request.data['project'])
    subprojects = [get_object_or_404(SubProjects, name=subproject_name, parent_project=project)
                   for subproject_name in request.data['subprojects']]

    session = Sessions.objects.create(
        project=project,
        start_time=timezone.make_aware(
            datetime.strptime(f"{request.data['date']} {request.data['start_time']}",
                              '%m-%d-%Y %H:%M:%S')
        ),
        end_time=timezone.make_aware(
            datetime.strptime(f"{request.data['date']} {request.data['end_time']}",
                              '%m-%d-%Y %H:%M:%S')
        ),
        is_active=False
    )

    for subproject in subprojects:
        session.subprojects.add(subproject)

    session.save()

    return Response(status=201)


@api_view(['DELETE'])
def delete_session(request, session_id):
    session = get_object_or_404(Sessions, pk=session_id)

    update_time_totals(session, is_delete=True)

    session.delete()
    return Response(status=204)


@api_view(['GET'])
def list_sessions(request):
    """
    List all the saved (i.e. not active) sessions
    :param request: takes in optional filter parameters 'start' and 'end' or 'project(s)'
    """
    sessions = Sessions.objects.filter(is_active=False)

    if 'start' in request.query_params and 'end' in request.query_params:
        start = request.query_params['start']
        end = request.query_params['end']
        sessions = in_window(sessions, start, end)
    if 'start' in request.query_params:
        start = request.query_params['start']
        sessions = in_window(sessions, start)

    if 'project' in request.query_params and 'subproject' not in request.query_params:
        project_name = request.query_params['project']
        sessions = filter_by_projects(sessions, project_name)
    elif 'projects' in request.query_params:
        project_names = request.query_params['projects'].split(',')
        sessions = filter_by_projects(sessions, names=project_names)


    serializer = SessionSerializer(sessions, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def list_active_sessions(request):
    """
    List all active sessions
    """
    sessions = Sessions.objects.filter(is_active=True)
    serializer = SessionSerializer(sessions, many=True)
    return Response(serializer.data)
