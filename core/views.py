import os
import pytz
from AutumnWeb import settings
from core.forms import *
from core.utils import *
from django.contrib import messages
from django.db import transaction
from django.http import StreamingHttpResponse, JsonResponse, HttpResponse
from django.utils import timezone
from datetime import datetime, timedelta, time
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404, render, redirect, reverse
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from core.models import Projects, SubProjects, Sessions, status_choices



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
            subprojects = SubProjects.objects.filter(name__in=subproject_names, parent_project=project,
                                                     user=request.user)
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

            session.full_clean()
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


def remove_ambiguous_time_error(time_value):
    try:
        return timezone.make_aware(datetime.strptime(time_value, "%Y-%m-%d %H:%M:%S"),
                                   timezone.get_current_timezone(),
                                   is_dst=True)
    except pytz.AmbiguousTimeError:
        return timezone.make_aware(datetime.strptime(time_value, "%Y-%m-%d %H:%M:%S"),
                                   timezone.get_current_timezone(),
                                   is_dst=False)


def fix_ambiguous_time(form, field_name, raw_time):
    for error in form.errors.get(field_name, []):
        if 'ambiguous' in error:
            return remove_ambiguous_time_error(raw_time)
    return None  # Return None if no changes were made

@login_required
@transaction.atomic
def update_session(request, session_id: int):
    """
    Allow user to change session details, including project, subprojects, start time, end time, and note.
    Deletes the existing session and creates a new one with the updated details.
    """
    current_session = get_object_or_404(Sessions, id=session_id, user=request.user)

    if request.method == "POST":
        form = UpdateSessionForm(request.POST, instance=current_session)
        valid = form.is_valid()

        if not valid: # correct ambiguous time errors that occur on daylights saving time changes
            # Extract start and end times from POST data
            start_time_raw = request.POST.get('start_time')
            end_time_raw = request.POST.get('end_time')

            request.POST = request.POST.copy()  # make the POST data mutable

            # Attempt to fix ambiguous times
            fixed_start_time = fix_ambiguous_time(form, 'start_time', start_time_raw)
            fixed_end_time = fix_ambiguous_time(form, 'end_time', end_time_raw)

            if fixed_start_time:
                request.POST['start_time'] = fixed_start_time
            if fixed_end_time:
                request.POST['end_time'] = fixed_end_time

            # recreate the form with the updated POST data and try again
            form = UpdateSessionForm(request.POST, instance=current_session)
            valid = form.is_valid()

        if valid:
            try:
                project_name = form.cleaned_data['project_name']
                subproject_names = request.POST.getlist('subprojects')

                project = get_object_or_404(Projects, name=project_name, user=request.user)

                subprojects = SubProjects.objects.filter(
                    name__in=subproject_names,
                    parent_project=project,
                    user=request.user
                )

                if not subprojects.exists() and subproject_names:
                    raise ValueError("No subprojects found for the selected project")

                # Create a new session
                new_session = Sessions.objects.create(
                    user=request.user,
                    project=project,
                    start_time=form.cleaned_data['start_time'],  # form.cleaned_data returns an aware datetime object
                    end_time=form.cleaned_data['end_time'],
                    note=form.cleaned_data['note'],
                    is_active=False
                )

                new_session.full_clean()
                new_session.subprojects.add(*subprojects)
                # no need to call save() since add() saves the m2m relationship, .set() works too but it replaces
                # the existing relationships with the new ones.

                # Delete the current session
                current_session.delete()

                messages.success(request, "Updated session")
                return redirect('update_session', session_id=new_session.id)

            except ValueError as ve:
                messages.error(request, str(ve))
            except Exception as e:
                messages.error(request, f"An error occurred while updating the session. Error: {e}")
        else:
            messages.error(request, "Invalid form data. Please check your inputs.")
    else:
        form = UpdateSessionForm(instance=current_session,
                                 initial={
                                     'project_name': current_session.project.name if current_session.project else ''
                                 })

    subprojects = SubProjects.objects.filter(parent_project=current_session.project)
    session_subs = current_session.subprojects.all()
    filtered_subs = [{'subproject': sp, 'is_selected': sp in session_subs} for sp in subprojects]

    context = {
        'title': 'Update Session',
        'filtered_subs': filtered_subs,
        'form': form
    }

    return render(request, 'core/update_session.html', context)


@login_required
def stop_timer(request, session_id: int):
    timer = Sessions.objects.get(id=session_id)

    if request.method == "POST":
        timer.is_active = False
        timer.end_time = timezone.now()

        if 'session_note' in request.POST:
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


def stream_response(message):
    return f"data: {json.dumps({'message': message})}\n\n"


@login_required
def import_view(request):
    # clear session data
    request.session.delete('file_path')
    request.session.delete('import_data')

    if request.method == "POST":
        form = ImportJSONForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES.get('file')

            if uploaded_file:
                # Save to disk in media/temp
                file_path = os.path.join(settings.MEDIA_ROOT, 'temp', uploaded_file.name)

                if not os.path.exists(os.path.dirname(file_path)):
                    os.makedirs(os.path.dirname(file_path))

                with open(file_path, 'wb+') as destination:
                    for chunk in uploaded_file.chunks():
                        destination.write(chunk)

                # Store file path in session for later processing
                request.session['file_path'] = file_path

            # Exclude 'file' since it's already handled separately
            form_data = form.cleaned_data.copy()
            form_data.pop('file', None)  # Remove the file from cleaned_data

            request.session['import_data'] = form_data
            return JsonResponse({'message': 'Form submitted successfully.'}, status=200)
    else:
        form = ImportJSONForm()

    context = {
        'title': 'Import Data',
        'form': form,
    }

    return render(request, 'core/import.html', context)


@csrf_exempt
def import_stream(request):

    def event_stream():
        # get data from session
        file_path = request.session.get('file_path')
        autumn_import = request.session.get('import_data').get('autumn_import')
        force = request.session.get('import_data').get('force')
        merge = request.session.get('import_data').get('merge')
        tolerance = request.session.get('import_data').get('tolerance')
        verbose = request.session.get('import_data').get('verbose')

        user = request.user
        skipped = []

        # clear session data
        request.session.delete('file_path')
        request.session.delete('import_data')

        try:
            with open(file_path) as f:
                try:
                    data = json_decompress(f.read())
                except RuntimeError:
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError:
                        os.remove(file_path)
                        yield stream_response("Error: Invalid JSON file")
                        return

            os.remove(file_path)

            total_projects = len(data.items())
            for idx, (project_name, project_data) in enumerate(data.items(), 1):
                yield stream_response(f"Processing project {idx}/{total_projects}: {project_name}")

                project = Projects.objects.filter(name=project_name, user=user).first()

                if project:
                    if force:
                        yield stream_response(
                            f"Force option enabled - deleting existing project '{project_name}'")
                        Projects.objects.filter(name=project_name).delete()
                        project = None
                    elif merge:
                        if verbose:
                            yield stream_response(
                                f"Merging new sessions and subprojects into '{project_name}'...")
                    else:
                        skipped.append(project_name)
                        yield stream_response(f"Skipping existing project: {project_name}")
                        continue

                if not project:
                    project = Projects.objects.create(
                        user=user,
                        name=project_name,
                        start_date=timezone.make_aware(
                            datetime.strptime(project_data['Start Date'], '%m-%d-%Y')),
                        last_updated=timezone.make_aware(
                            datetime.strptime(project_data['Last Updated'], '%m-%d-%Y')),
                        total_time=0.0,
                        description=project_data['Description'] if 'Description' in project_data else '',
                    )

                    if 'Status' in project_data:  # handle old versions from before the status field was added
                        # Find the status tuple that matches the project_data['Status']
                        status_tuple = next(
                            (status for status in status_choices if status[0] == project_data['Status']), None)

                        if status_tuple:
                            project.status = status_tuple[0]
                        else:
                            raise ValueError(f"Invalid status: {project_data['Status']}")
                    project.save()

                # Process subprojects
                total_subprojects = len(project_data['Sub Projects'])

                if verbose and total_subprojects > 0:
                    yield stream_response(f"Processing {total_subprojects} subprojects for {project_name}")

                for subproject_name, subproject_time in project_data['Sub Projects'].items():
                    subproject_name_lower = subproject_name.lower()
                    if autumn_import:
                        subproject, created = SubProjects.objects.get_or_create(
                            user=user,
                            name=subproject_name_lower,
                            parent_project=project,
                            defaults={ # these values aren't used in the search. But they are added to new instances
                                'start_date': project.start_date,
                                'last_updated': project.last_updated,
                                'total_time': 0.0,
                                'description': '',
                            }
                        )
                    else:
                        subproject, created = SubProjects.objects.get_or_create(
                            user=user,
                            name=subproject_name_lower,
                            parent_project=project,
                            defaults={  # these values aren't used in the search. But they are added to new instances
                                "start_date": timezone.make_aware(
                                    datetime.strptime(project_data['Sub Projects'][subproject_name]['Start Date'], '%m-%d-%Y')),
                                "last_updated": timezone.make_aware(
                                    datetime.strptime(project_data['Sub Projects'][subproject_name]['Last Updated'], '%m-%d-%Y')),
                                "description": project_data['Sub Projects'][subproject_name]['Description']
                                if 'Description' in project_data['Sub Projects'][subproject_name] else '',
                            }
                        )

                    if created and verbose:
                        yield stream_response(
                            f"Created new subproject '{subproject_name}' under project '{project_name}'")

                # Process sessions
                total_sessions = len(project_data['Session History'])
                yield stream_response(f"Processing {total_sessions} sessions for {project_name}")

                for session_idx, session_data in enumerate(project_data['Session History'], 1):

                    start_time = timezone.make_aware(
                        datetime.strptime(f"{session_data['Date']} {session_data['Start Time']}",
                                          '%m-%d-%Y %H:%M:%S')
                    )
                    end_time = timezone.make_aware(
                        datetime.strptime(f"{session_data['Date']} {session_data['End Time']}",
                                          '%m-%d-%Y %H:%M:%S')
                    )

                    subproject_names = [name.lower() for name in session_data['Sub-Projects']]
                    note = session_data['Note']

                    if end_time < start_time:
                        start_time -= timedelta(days=1)

                    if session_exists(user, project, start_time, end_time, subproject_names,
                                      time_tolerance=timedelta(minutes=tolerance)):
                        continue

                    if verbose:
                        yield stream_response(
                            f"Importing session on {session_data['Date']} from {session_data['Start Time']} to "
                            f"{session_data['End Time']}...")

                    session = Sessions.objects.create(
                        user=user,
                        project=project,
                        start_time=start_time,
                        end_time=end_time,
                        is_active=False,
                        note=note,
                    )

                    for subproject_name in subproject_names:
                        try:
                            subproject = SubProjects.objects.get(user=user, name=subproject_name,
                                                                 parent_project=project)
                            session.subprojects.add(subproject)
                        except SubProjects.DoesNotExist:
                            yield stream_response(f"Warning: Subproject not found: {subproject_name}. Subproject "
                                                  f"will not be added to session.")
                            continue

                    session.full_clean()       
                    session.save()

                yield stream_response(f"\n\n")

                project.audit_total_time()
                for subproject in project.subprojects.all():
                    subproject.audit_total_time()

                sessions = Sessions.objects.filter(project=project, user=user)
                earliest_start, latest_end = sessions_get_earliest_latest(sessions)

                if merge and earliest_start and latest_end:
                    project.start_date = earliest_start
                    project.last_updated = latest_end
                    project.save()

                    for subproject in project.subprojects.all():
                        earliest_start, latest_end = sessions_get_earliest_latest(subproject.sessions.all())
                        subproject.start_date = earliest_start if earliest_start else project.start_date
                        subproject.last_updated = latest_end if latest_end else project.last_updated
                        subproject.save()

                if not merge:
                    mismatch = abs(project.total_time - project_data['Total Time'])
                    if mismatch > tolerance:
                        tally = project.total_time
                        project.delete()
                        yield stream_response(f"Error: Total time mismatch for project '{project_name}': "
                                              f"expected {project_data['Total Time']}, got {tally}. "
                                              f"Mismatch: {mismatch}")
                        return

            if len(skipped) > 0:
                yield stream_response(f"Import completed with skipped projects: {', '.join(skipped)}")
            else:
                yield stream_response("Import completed successfully!")

        except Exception as e:
            yield stream_response(f"Error: {str(e)}")

    response = StreamingHttpResponse(
        event_stream(),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


def export_view(request):
    if request.method == "POST":
        form = ExportJSONForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Invalid form data. Please check your inputs.")
            return render(request, 'core/export.html', {'title': 'Export Data', 'form': form})

        # pull form data
        project_name      = form.cleaned_data['project_name']
        output_file       = form.cleaned_data['output_file']
        compress          = form.cleaned_data['compress']
        autumn_compatible = form.cleaned_data['autumn_compatible']
        start_date        = form.cleaned_data['start_date']
        end_date          = form.cleaned_data['end_date']

        # default filename
        if not output_file:
            output_file = f"{project_name or 'projects'}.json"
        if not output_file.endswith('.json'):
            output_file += '.json'

        # prepare date‐filters
        if start_date:
            # include all times on start_date
            start_dt = datetime.combine(start_date, time.min)
            start_dt = timezone.make_aware(start_dt)
        if end_date:
            # include up through end of the day
            end_dt = datetime.combine(end_date, time.max)
            end_dt = timezone.make_aware(end_dt)

        # Flat query for every session in the window (and optionally a single project)
        qs = Sessions.objects.filter(is_active=False, user=request.user)
        if project_name:
            qs = qs.filter(project__name__icontains=project_name)
        if start_date:
            qs = qs.filter(end_time__gte=start_dt)
        if end_date:
            qs = qs.filter(end_time__lte=end_dt)

        # Avoid N+1 when later reading .project and .subprojects
        qs = qs.select_related('project').prefetch_related('subprojects')

        # build export dict
        export_dict = build_project_json_from_sessions(qs, autumn_compatible)

        # finally serialize
        contents = (
            json.dumps(json_compress(export_dict))
            if compress
            else json.dumps(export_dict, indent=4)
        )
        response = HttpResponse(contents, content_type='application/json')
        response['Content-Disposition'] = f'attachment; filename="{output_file}"'
        return response

    # GET
    form = ExportJSONForm()
    return render(request, 'core/export.html', {'title': 'Export Data', 'form': form})


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
    ordering = ['-last_updated']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Autumn'

        context['search_form'] = SearchProjectForm(
            initial={
                'project_name': self.request.GET.get('project_name'),
                'start_date': self.request.GET.get('start_date'),
                'end_date': self.request.GET.get('end_date'),
            }
        )

        ungrouped_projects = context['object_list']

        # group by project status (active, paused, complete) from the status_choices tuple
        grouped_projects = []
        for status, displayName in status_choices:  # db_Status is how the status is stored in the database
            grouped_projects.append({'status': displayName,
                                     'projects': ungrouped_projects.filter(status=status).order_by('-last_updated')})

        context['grouped_projects'] = grouped_projects

        return context

    def get_queryset(self):
        projects = Projects.objects.filter(user=self.request.user)
        search_name = self.request.GET.get('project_name')
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')

        if search_name:
            projects = filter_by_projects(projects, name=search_name)

        if start_date:
            start = timezone.make_aware(parse_date_or_datetime(start_date))
            if end_date:
                end = timezone.make_aware(parse_date_or_datetime(end_date) + timedelta(days=1))
                projects = projects.filter(start_date__range=[start, end])
            else:
                projects = projects.filter(start_date__gte=start)

        return projects


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
        if Projects.objects.filter(user=self.request.user, name=form.instance.name).exists():
            form.add_error('name', 'You already have a project with this name.')
            return self.form_invalid(form)
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
            initial['parent_project'] = Projects.objects.get(name=self.kwargs.get('project_name'),
                                                             user=self.request.user)
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Subproject'
        return context

    def form_valid(self, form):
        form.instance.user = self.request.user  # set the user field of the subproject to the current user
        form.save()
        messages.success(self.request, "Subproject created successfully")
        return redirect('projects')

    def form_invalid(self, form):
        # add an error for the name field if the user already has a subproject with the same name under the same project
        if SubProjects.objects.filter(
                user=self.request.user,
                name=form.instance.name,
                parent_project=form.instance.parent_project
        ).exists():
            form.add_error('name', 'You already have a subproject with this name under the selected project.')
        return super().form_invalid(form)


class UpdateProjectView(LoginRequiredMixin, UpdateView):
    model = Projects
    form_class = UpdateProjectForm
    template_name = 'core/update_project.html'
    context_object_name = 'project'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Update Project'
        context['subprojects'] = self.object.subprojects.all()  # get all subprojects related to the project
        context['session_count'] = self.object.sessions.count()  # get the number of sessions related to the project
        context['average_session_duration'] = self.object.total_time / context['session_count'] \
            if context['session_count'] > 0 else 0
        return context

    def form_valid(self, form):
        if Projects.objects.filter(user=self.request.user, name=form.instance.name).exclude(pk=self.object.pk).exists():
            form.add_error('name', 'You already have a project with this name.')
            return self.form_invalid(form)
        form.save()
        messages.success(self.request, "Project updated successfully")
        return redirect('update_project', pk=self.kwargs['pk'])


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
        if SubProjects.objects.filter(
                user=self.request.user,
                name=form.instance.name,
                parent_project=form.instance.parent_project
        ).exclude(pk=self.object.pk).exists():
            form.add_error('name', 'You already have a subproject with this name under the selected project.')
            return self.form_invalid(form)
        form.save()
        messages.success(self.request, "Subproject updated successfully")
        return redirect('update_subproject', pk=self.kwargs['pk'])


class DeleteProjectView(LoginRequiredMixin, DeleteView):
    model = Projects
    template_name = 'core/delete_project.html'
    context_object_name = 'project'

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

        # Check if any search-related query parameters are present. we only want to display the message on a search
        if (self.request.GET.get('project_name') or self.request.GET.get('start_date')
                or self.request.GET.get('end_date') or self.request.GET.get('note_snippet')):
            messages.success(self.request, f"Found {len(self.get_queryset())} results")

        return context

    def get_queryset(self):
        sessions = Sessions.objects.filter(is_active=False, user=self.request.user)
        return filter_sessions_by_params(self.request, sessions)


class DeleteSessionView(LoginRequiredMixin, DeleteView):
    model = Sessions
    template_name = 'core/delete_session.html'
    context_object_name = 'session'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Delete Session'
        return context

    def get_object(self, queryset=None):
        return get_object_or_404(Sessions, pk=self.kwargs['session_id'], user=self.request.user)

    def get_success_url(self):
        messages.success(self.request, "Session deleted successfully")
        return reverse('sessions')  # redirect to the sessions page


@login_required
@transaction.atomic
def merge_projects(request):
    """
    View to merge two projects into one new project.
    Moves all sessions and subprojects from both projects to the new merged project.
    """
    if request.method == "POST":
        form = MergeProjectsForm(request.POST)
        if form.is_valid():
            try:
                project1_name = form.cleaned_data['project1']
                project2_name = form.cleaned_data['project2']
                new_project_name = form.cleaned_data['new_project_name']
                
                # Get the projects to merge
                project1 = get_object_or_404(Projects, name=project1_name, user=request.user)
                project2 = get_object_or_404(Projects, name=project2_name, user=request.user)
                
                # Check if new project name already exists
                if Projects.objects.filter(user=request.user, name=new_project_name).exists():
                    form.add_error('new_project_name', 'You already have a project with this name.')
                    return render(request, 'core/merge_projects.html', {
                        'title': 'Merge Projects',
                        'form': form
                    })
                
                # Create merged description
                merged_description = f"Merged from '{project1.name}' and '{project2.name}'\n\n"
                
                if project1.description:
                    merged_description += f"--- {project1.name} Description ---\n{project1.description}\n\n"
                
                if project2.description:
                    merged_description += f"--- {project2.name} Description ---\n{project2.description}\n\n"
                
                # Remove trailing newlines
                merged_description = merged_description.strip()
                
                # Create the new merged project
                merged_project = Projects.objects.create(
        user=request.user,
                    name=new_project_name,
                    start_date=min(project1.start_date, project2.start_date),
                    last_updated=max(project1.last_updated, project2.last_updated),
                    total_time=0.0,  # Will be calculated by audit function
                    status='active',  # Default to active
                    description=merged_description
                )
                
                # Move all sessions from both projects to the merged project
                project1_sessions = project1.sessions.all()
                project2_sessions = project2.sessions.all()
                
                for session in project1_sessions:
                    session.project = merged_project
                    session.save()

                for session in project2_sessions:
                    session.project = merged_project
                    session.save()
                
                # Move all subprojects from both projects to the merged project
                # Handle potential name conflicts by renaming duplicates
                project1_subprojects = list(project1.subprojects.all())
                project2_subprojects = list(project2.subprojects.all())
                
                # Get existing subproject names in the merged project
                existing_subproject_names = set()
                
                # First, move all subprojects from project1
                for subproject in project1_subprojects:
                    original_name = subproject.name
                    new_name = original_name
                    
                    # If name conflict exists, append project name to make it unique
                    if new_name in existing_subproject_names:
                        new_name = f"{original_name} ({project1.name})"
                        counter = 1
                        while new_name in existing_subproject_names:
                            new_name = f"{original_name} ({project1.name}) {counter}"
                            counter += 1
                    
                    subproject.name = new_name
                    subproject.parent_project = merged_project
                    subproject.save()
                    existing_subproject_names.add(new_name)
                
                # Then, move all subprojects from project2
                for subproject in project2_subprojects:
                    original_name = subproject.name
                    new_name = original_name
                    
                    # If name conflict exists, append project name to make it unique
                    if new_name in existing_subproject_names:
                        new_name = f"{original_name} ({project2.name})"
                        counter = 1
                        while new_name in existing_subproject_names:
                            new_name = f"{original_name} ({project2.name}) {counter}"
                            counter += 1
                    
                    subproject.name = new_name
                    subproject.parent_project = merged_project
                    subproject.save()
                    existing_subproject_names.add(new_name)
                
                # Audit total time for the merged project and all its subprojects
                merged_project.audit_total_time(log=False)
                for subproject in merged_project.subprojects.all():
                    subproject.audit_total_time(log=False)
                
                # Delete the original projects
                project1.delete()
                project2.delete()
                
                # Check if any subprojects were renamed
                renamed_count = 0
                for sp in project1_subprojects + project2_subprojects:
                    if ' (' in sp.name and sp.name.endswith(')'):
                        renamed_count += 1
                
                if renamed_count > 0:
                    messages.success(request, f"Successfully merged '{project1_name}' and '{project2_name}' into '{new_project_name}'. {renamed_count} subprojects were renamed to avoid conflicts.")
                else:
                    messages.success(request, f"Successfully merged '{project1_name}' and '{project2_name}' into '{new_project_name}'")
                return redirect('projects')
                
            except Exception as e:
                messages.error(request, f"An error occurred while merging projects: {e}")
        else:
            messages.error(request, "Invalid form data. Please check your inputs.")
    else:
        form = MergeProjectsForm()
    
    context = {
        'title': 'Merge Projects',
        'form': form
    }
    
    return render(request, 'core/merge_projects.html', context)
