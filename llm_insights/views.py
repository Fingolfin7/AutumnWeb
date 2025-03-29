from django.shortcuts import render
from django.views.generic import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.contrib import messages
from core.models import Sessions
from core.forms import SearchProjectForm
from core.utils import filter_sessions_by_params
import json
from .llm_handlers import get_llm_handler


def prep_session_data(sessions):
    projects_data = {}


    for session in sessions:
        project_name = session.project.name

        # Initialize project entry if it doesn't exist
        if project_name not in projects_data:
            projects_data[project_name] = {
                "Total Time": 0,

                "Status": session.project.status if hasattr(session.project, 'status') else "",
                "Description": session.project.description if hasattr(session.project, 'description') else "",
                "Sub Projects": {},
                "Session History": []
            }

        # Add session duration to total
        projects_data[project_name]["Total Time"] += session.duration

        # Track subprojects
        subprojects = [sp.name for sp in session.subprojects.all()]
        for subproject in subprojects:
            if subproject not in projects_data[project_name]["Sub Projects"]:
                projects_data[project_name]["Sub Projects"][subproject] = 0
            projects_data[project_name]["Sub Projects"][subproject] += session.duration

        # Add session to history
        session_entry = {
            "Date": session.end_time.strftime('%m-%d-%Y'),
            "Start Time": session.start_time.strftime('%H:%M:%S'),
            "End Time": session.end_time.strftime('%H:%M:%S'),
            "Sub-Projects": subprojects,
            "Duration": session.duration,
            "Note": session.note or ""
        }
        projects_data[project_name]["Session History"].append(session_entry)

    return json.dumps(projects_data, indent=2)


def perform_llm_analysis(llm_handler, sessions, user_prompt="", username="", conversation_history=None, sessions_updated=False):
    if conversation_history is None or not conversation_history:
        session_data = prep_session_data(sessions)
        _, conversation_history = llm_handler.initialize_chat(username, session_data)
    else:
        # If sessions were updated, update the session data
        if sessions_updated:
            session_data = prep_session_data(sessions)
            llm_handler.update_session_data(session_data)
            conversation_history = llm_handler.get_conversation_history()

    # Send user message if provided
    if user_prompt:
        assistant_response = llm_handler.send_message(user_prompt)
        conversation_history = llm_handler.get_conversation_history()
        return assistant_response, conversation_history

    return None, conversation_history


class InsightsView(LoginRequiredMixin, View):
    def get(self, request):
        sessions = Sessions.objects.filter(is_active=False, user=request.user)
        sessions = filter_sessions_by_params(request, sessions)

        # Set flag if sessions were just filtered
        sessions_updated = bool(request.GET and any(request.GET.values()))
        if sessions_updated:
            messages.success(request, "Session selection updated. The AI has been informed about the new data.")

        context = {
            'title': 'Session Analysis',
            'search_form': SearchProjectForm(
                initial={
                    'project_name': request.GET.get('project_name'),
                    'start_date': request.GET.get('start_date'),
                    'end_date': request.GET.get('end_date'),
                    'note_snippet': request.GET.get('note_snippet'),
                }
            ),
            'sessions': sessions,
            'conversation_history': request.session.get('conversation_history', None),
            'sessions_updated': sessions_updated
        }

        return render(request, 'llm_insights/insights.html', context)

    def post(self, request):
        sessions = Sessions.objects.filter(is_active=False, user=request.user)
        sessions = filter_sessions_by_params(request, sessions)
        sessions_updated = False
        conversation_history = request.session.get('conversation_history', None)

        # Get cached handler or create new one
        handler_key = f"llm_handler_{request.user.id}"
        handler = cache.get(handler_key)

        if not handler:
            handler = get_llm_handler(provider="gemini")
            cache.set(handler_key, handler, 3600)  # Cache for 1 hour

        print(handler.chat.get_history())

        if 'reset_conversation' in request.POST:
            # Reset conversation
            conversation_history = None
            request.session['conversation_history'] = None
            cache.delete(handler_key)  # Clear the cached handler
        else:
            user_prompt = request.POST.get('prompt', '')

            # Process the conversation
            insights, conversation_history = perform_llm_analysis(
                llm_handler=handler,
                sessions=sessions,
                user_prompt=user_prompt,
                username=request.user.username,
                conversation_history=conversation_history,
                sessions_updated=sessions_updated
            )

            # Update cache and session
            cache.set(handler_key, handler, 3600)
            request.session['conversation_history'] = conversation_history

        context = {
            'title': 'Session Analysis',
            'search_form': SearchProjectForm(
                initial={
                    'project_name': request.GET.get('project_name'),
                    'start_date': request.GET.get('start_date'),
                    'end_date': request.GET.get('end_date'),
                    'note_snippet': request.GET.get('note_snippet'),
                }
            ),
            'sessions': sessions,
            'conversation_history': conversation_history,
            'sessions_updated': sessions_updated
        }

        return render(request, 'llm_insights/insights.html', context)
