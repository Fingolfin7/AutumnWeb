from django.contrib import messages
from django.shortcuts import get_object_or_404, render, redirect, reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from datetime import datetime
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from core.forms import (CreateProjectForm, CreateSubProjectForm, UpdateProjectForm,
                        UpdateSubProjectForm, SearchProjectForm)
from core.utils import (parse_date_or_datetime, in_window, filter_by_projects,
                        tally_project_durations, filter_sessions_by_params)
from core.models import Projects, SubProjects, Sessions
from core.serializers import ProjectSerializer, SubProjectSerializer, SessionSerializer
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin


@login_required
def home(request):
    context = {
        'timers': Sessions.objects.filter(is_active=True)[:3]
    }
    return render(request, 'core/home.html', context)


@login_required
def start_timer(request):
    if request.method == "POST":
        try:
            project_name = request.POST.get('project')
            subproject_names = request.POST.getlist('subprojects')

            # Fetch the project
            project = Projects.objects.filter(name=project_name, user=request.user).first()
            if not project:
                raise ValueError("Project not found")

            # Fetch all subprojects related to the project and in the list of submitted subproject names
            subprojects = SubProjects.objects.filter(name__in=subproject_names, parent_project=project)
            if not subprojects.exists() and len(subproject_names) > 0:
                raise ValueError("No subprojects found for the selected project")

            # Create a new session
            session = Sessions.objects.create(
                user=request.user,
                project=project,
                start_time=timezone.make_aware(datetime.now()),
                is_active=True
            )

            # Add the subprojects to the session
            for subproject in subprojects:
                session.subprojects.add(subproject)

            session.save()
            messages.success(request, "Started timer")
            return redirect('timers')

        except ValueError as ve:
            messages.error(request, str(ve))
            return redirect('start_timer')

        except Exception as e:
            messages.error(request, f"An error occurred while starting the timer. Error: {e}")
            return redirect('start_timer')

    context = {
        'title': 'Start Timer'
    }

    return render(request, 'core/start_timer.html', context)


@login_required
def stop_timer(request, session_id: int):
    timer = Sessions.objects.get(id=session_id)

    if request.method == "POST":
        timer.is_active = False
        timer.end_time = timezone.now()

        if request.POST['session_note']:
            timer.note = request.POST['session_note']

        timer.save()
        messages.success(request, "Stopped timer")
        return redirect('timers')

    context = {
        'title': 'Stop Timer',
        'timer': timer
    }

    return render(request, 'core/stop_timer.html', context)


@login_required
def restart_timer(request, session_id: int):
    timer = Sessions.objects.get(id=session_id)

    timer.start_time = timezone.now()

    timer.save()
    messages.success(request, "Restarted timer")

    return redirect('timers')


@login_required
def remove_timer(request, session_id: int):
    timer = Sessions.objects.get(id=session_id)

    if request.method == "POST":
        timer.delete()
        messages.success(request, "Removed timer")
        return redirect('timers')

    context = {
        'title': 'Remove Timer',
        'timer': timer
    }

    return render(request, 'core/remove_timer.html', context)


@login_required
def ChartsView(request):
    search_form = SearchProjectForm(
        initial={
            'project_name': request.GET.get('project_name'),
            'start_date': request.GET.get('start_date'),
            'end_date': request.GET.get('end_date'),
            'chart_type': request.GET.get('chart_type'),
        }
    )

    context = {
        'title': 'Charts',
        'search_form': search_form
    }
    return render(request, 'core/charts.html', context)


class TimerListView(LoginRequiredMixin, ListView):
    model = Sessions
    template_name = 'core/timers.html'
    context_object_name = 'timers'
    ordering = ['-start_time']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Timers'

        return context

    def get_queryset(self):
        return Sessions.objects.filter(is_active=True, user=self.request.user)


class ProjectsListView(LoginRequiredMixin, ListView):
    model = Projects
    template_name = 'core/projects_list.html'
    context_object_name = 'projects'
    ordering = ['name']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Projects'

        return context

    def get_queryset(self):
        return Projects.objects.filter(user=self.request.user)


class CreateProjectView(LoginRequiredMixin, CreateView):
    model = Projects
    context_object_name = 'project'
    form_class = CreateProjectForm
    template_name = 'core/create_project.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Project'

        return context

    def form_valid(self, form):
        form.instance.user = self.request.user  # set the user field of the project to the current user
        form.save()
        messages.success(self.request, "Project created successfully")
        return redirect('projects')


class CreateSubProjectView(LoginRequiredMixin, CreateView):
    model = SubProjects
    form_class = CreateSubProjectForm
    template_name = 'core/create_subproject.html'

    def get_initial(self):
        initial = super().get_initial()
        if 'pk' in self.kwargs:
            initial['parent_project'] = Projects.objects.get(pk=self.kwargs.get('pk'), user=self.request.user)
        elif 'project_name' in self.kwargs:
            initial['parent_project'] = Projects.objects.get(name=self.kwargs.get('project_name'), user=self.request.user)
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Subproject'
        return context

    def form_valid(self, form):
        form.instance.user = self.request.user
        form.save()
        messages.success(self.request, "Subproject created successfully")
        return redirect('projects')

    def form_invalid(self, form):
        messages.error(self.request, "An error occurred while creating the subproject")
        return redirect('create_subproject')


class UpdateProjectView(LoginRequiredMixin, UpdateView):
    model = Projects
    form_class = UpdateProjectForm
    template_name = 'core/update_project.html'
    context_object_name = 'project'

    def get_object(self, queryset=None):
        project = get_object_or_404(Projects, name=self.kwargs['project_name'], user=self.request.user)
        # project.audit_total_time()
        return project

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Update Project'
        context['subprojects'] = self.object.subprojects.all()  # get all subprojects related to the project
        context['session_count'] = self.object.sessions.count()  # get the number of sessions related to the project
        context['average_session_duration'] = self.object.total_time / context['session_count'] \
            if context['session_count'] > 0 else 0
        return context

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Project updated successfully")
        return redirect('update_project', project_name=self.kwargs['project_name'])


class UpdateSubProjectView(LoginRequiredMixin, UpdateView):
    model = SubProjects
    form_class = UpdateSubProjectForm
    template_name = 'core/update_subproject.html'
    context_object_name = 'subproject'

    def get_object(self, queryset=None):
        subproject = super().get_object(queryset)
        # subproject.audit_total_time()
        return subproject

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Update Subproject'
        context['session_count'] = self.object.sessions.count()  # get the number of sessions related to the project
        context['average_session_duration'] = self.object.total_time / context['session_count'] \
            if context['session_count'] > 0 else 0
        return context

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Subproject updated successfully")
        return redirect('update_subproject', pk=self.kwargs['pk'])


class DeleteProjectView(LoginRequiredMixin, DeleteView):
    model = Projects
    template_name = 'core/delete_project.html'
    context_object_name = 'project'

    def get_object(self, queryset=None):
        return get_object_or_404(Projects, name=self.kwargs['project_name'], user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Delete Project'
        return context

    def get_success_url(self):
        messages.success(self.request, "Project deleted successfully")
        return reverse('projects')


class DeleteSubProjectView(LoginRequiredMixin, DeleteView):
    model = SubProjects
    template_name = 'core/delete_subproject.html'
    context_object_name = 'subproject'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Delete Subproject'
        return context

    def get_success_url(self):
        messages.success(self.request, "Subproject deleted successfully")
        return reverse('projects')


class SessionsListView(LoginRequiredMixin, ListView):
    model = Sessions
    template_name = 'core/list_sessions.html'
    context_object_name = 'sessions'
    ordering = ['-end_time']
    paginate_by = 7

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Sessions'
        context['search_form'] = SearchProjectForm(
            initial={
                'project_name': self.request.GET.get('project_name'),
                'start_date': self.request.GET.get('start_date'),
                'end_date': self.request.GET.get('end_date'),
                'note_snippet': self.request.GET.get('note_snippet')
            }
        )

        paginated_sessions = context['object_list']

        # Group by session_date
        grouped_sessions = {}
        for session in paginated_sessions:
            if session.end_time.tzinfo != timezone.get_default_timezone():  # convert utc to local timezone
                session_date = session.end_time.astimezone(timezone.get_default_timezone()).strftime('%m-%d-%Y')
            else:
                session_date = timezone.make_aware(session.end_time).strftime('%m-%d-%Y')

            if session_date not in grouped_sessions:
                grouped_sessions[session_date] = {'sessions': [session], 'total_duration': session.duration}
            else:
                grouped_sessions[session_date]['sessions'].append(session)
                grouped_sessions[session_date]['total_duration'] += session.duration

        context['grouped_sessions'] = grouped_sessions

        year_start = timezone.now().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0).strftime(
            "%Y-%m-%d")

        # Check if any search-related query parameters are present. we only want to display the message on a search
        if (self.request.GET.get('project_name') or (self.request.GET.get('start_date') != year_start)
                or self.request.GET.get('end_date') or self.request.GET.get('note_snippet')):
            messages.success(self.request, f"Found {len(self.get_queryset())} results")

        return context

    def get_queryset(self):
        sessions = Sessions.objects.filter(is_active=False, user=self.request.user)
        # if start and end dates are empty set the start date to the beginning of the year
        start_date = self.request.GET.get('start_date')
        if not start_date:
            start_date = timezone.now().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            # update the request object with the start date
            self.request.GET = self.request.GET.copy()
            self.request.GET['start_date'] = start_date.strftime("%Y-%m-%d")

        return filter_sessions_by_params(self.request, sessions)


# api endpoints to create, list, and delete projects, subprojects, and sessions



@login_required
@api_view(['POST'])
def create_project(request):
    serializer = ProjectSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors)


@login_required
@api_view(['GET'])
def list_projects(request):
    if 'start_date' in request.query_params and 'end_date' in request.query_params:
        start = request.query_params['start_date']
        end = request.query_params['end_date']
        projects = Projects.objects.filter(user=request.user)
        projects = in_window(projects, start, end)
    elif 'start_date' in request.query_params:
        start = request.query_params['start_date']
        projects = Projects.objects.filter(user=request.user)
        projects = in_window(projects, start)
    else:
        projects = Projects.objects.filter(user=request.user)

    serializer = ProjectSerializer(projects, many=True)
    return Response(serializer.data)


@login_required
@api_view(['GET'])
def tally_by_sessions(request):
    sessions = Sessions.objects.filter(is_active=False, user=request.user)
    sessions = filter_sessions_by_params(request, sessions)
    project_durations = tally_project_durations(sessions)
    return Response(project_durations)


@login_required
@api_view(['GET'])
def search_projects(request):
    search_term = request.query_params['search_term']
    if 'status' in request.query_params:
        status = request.query_params['status']
        projects = Projects.objects.filter(name__icontains=search_term, status=status, user=request.user)
    else:
        projects = Projects.objects.filter(name__icontains=search_term, user=request.user)
    serializer = ProjectSerializer(projects, many=True)
    return Response(serializer.data)


@login_required
@api_view(['GET'])
def get_project(request, project_name):
    project = get_object_or_404(Projects, name=project_name, user=request.user)
    serializer = ProjectSerializer(project)
    return Response(serializer.data)


@login_required
@api_view(['DELETE'])
def delete_project(request, project_name):
    project = get_object_or_404(Projects, name=project_name, user=request.user)
    project.delete()
    return Response(status=204)


@login_required
@api_view(['POST'])
def create_subproject(request):
    # check if the parent project exists
    if not Projects.objects.filter(name=request.data['parent_project'], user=request.user).exists():
        return Response({'error': 'Parent project ' + request.data['parent_project'] + ' does not exist'})

    serializer = SubProjectSerializer(data=request.data)

    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)

    return Response(serializer.errors)


@login_required
@api_view(['GET'])
def list_subprojects(request, **kwargs):
    project_name = request.query_params['project_name'] if 'project_name' in request.query_params else kwargs[
        'project_name']
    subprojects = SubProjects.objects.filter(parent_project__name=project_name, user=request.user)
    serializer = SubProjectSerializer(subprojects, many=True)
    return Response(serializer.data)


@login_required
@api_view(['GET'])
def search_subprojects(request):
    parent_project = request.query_params['project_name']
    search_term = request.query_params['search_term']
    subprojects = SubProjects.objects.filter(parent_project__name=parent_project, name__icontains=search_term,
                                             user=request.user)
    if not subprojects.exists():
        subprojects = SubProjects.objects.filter(parent_project__name=parent_project, user=request.user)
    serializer = SubProjectSerializer(subprojects, many=True)
    return Response(serializer.data)


@login_required
@api_view(['DELETE'])
def delete_subproject(request, project_name, subproject_name):
    subproject = get_object_or_404(SubProjects, name=subproject_name, parent_project__name=project_name, user=request.user)
    subproject.delete()
    return Response(status=204)  # status 204 means no content, i.e. the subproject was deleted successfully


@login_required
@api_view(['POST'])
def start_session(request):
    project = Projects.objects.filter(name=request.data['project'], user=request.user).first()
    all_subprojects = SubProjects.objects.filter(parent_project__name=project)
    subprojects = [all_subprojects.filter(name=subproject_name, parent_project=project).first()
                   for subproject_name in request.data.getlist('subprojects[]')]

    session = Sessions.objects.create(
        user=request.user,
        project=project,
        # subprojects=subprojects,
        start_time=timezone.make_aware(datetime.now()),
        is_active=True
    )

    for subproject in subprojects:
        session.subprojects.add(subproject)

    session.save()

    return Response(status=201)


@login_required
@api_view(['POST'])
def restart_session(request):
    session = get_object_or_404(Sessions, pk=request.data['session_id'], user=request.user)
    session.start_time = timezone.now()
    session.is_active = True

    session.save()
    return Response(status=200)


@login_required
@api_view(['POST'])
def end_session(request):
    """
    End an active session and update the associated project and subproject time tallies
    :param request:
    :return:
    """
    session = get_object_or_404(Sessions, pk=request.data['session_id'], user=request.user)
    session.end_time = timezone.now()
    session.is_active = False

    if 'note' in request.data:
        session.note = request.data['note']

    session.save()

    return Response(status=200)


@login_required
@api_view(['POST'])
def log_session(request):
    project = get_object_or_404(Projects, name=request.data['project'], user=request.user)
    subprojects = [get_object_or_404(SubProjects, name=subproject_name, parent_project=project)
                   for subproject_name in request.data['subprojects']]

    session = Sessions.objects.create(
        user=request.user,
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


@login_required
@api_view(['DELETE'])
def delete_session(request, session_id):
    session = get_object_or_404(Sessions, pk=session_id)
    session.delete()
    return Response(status=204)


@login_required
@api_view(['GET'])
def list_sessions(request):
    """
    List all the saved (i.e. not active) sessions
    :param request: takes in optional filter parameters 'start' and 'end' or 'project(s)'
    """
    sessions = Sessions.objects.filter(is_active=False, user=request.user)
    sessions = filter_sessions_by_params(request, sessions)
    serializer = SessionSerializer(sessions, many=True)
    return Response(serializer.data)


@login_required
@api_view(['GET'])
def list_active_sessions(request):
    """
    List all active sessions
    """
    sessions = Sessions.objects.filter(is_active=True, user=request.user)
    serializer = SessionSerializer(sessions, many=True)
    return Response(serializer.data)
