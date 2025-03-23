from django.shortcuts import render
from django.contrib.auth.decorators import login_required
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


def perform_llm_analysis(sessions, user_prompt="", conversation_history=None, sessions_updated=False):
    # Get the appropriate LLM handler (configurable from settings in the future)
    llm_handler = get_llm_handler(provider="gemini")

    # Initialize conversation if it's first message
    if conversation_history is None or not conversation_history:
        # Prepare session data in a format suitable for LLM
        session_data = prep_session_data(sessions)
        print(f"Session data prepared: {session_data}")

        system_prompt = f"""
        You are an expert project and time tracking analyst. Your job is to analyze projects, sessions,
        and session logs to provide insights based on the data provided.

        The user's name is {sessions[0].user.username} and this application is known as "Autumn".

        If possible please quote the session notes and dates/times for any insights you provide.

        Sessions data:
        {session_data}
        """
        conversation_history = llm_handler.initialize_chat(system_prompt)
    else:
        # Load saved conversation
        llm_handler.load_conversation(conversation_history)

        # If sessions were updated, update the session data
        if sessions_updated:
            # Prepare session data in a format suitable for LLM
            session_data = prep_session_data(sessions)
            print(f"Session data prepared: {session_data}")

            llm_handler.update_session_data(session_data)
            conversation_history = llm_handler.get_conversation_history()

    # Send user message if provided
    if user_prompt:
        assistant_response = llm_handler.send_message(user_prompt)
        conversation_history = llm_handler.get_conversation_history()
        return assistant_response, conversation_history

    return None, conversation_history


@login_required
def insights_view(request):
    sessions = Sessions.objects.filter(is_active=False, user=request.user)
    sessions = filter_sessions_by_params(request, sessions)

    insights = None
    conversation_history = request.session.get('conversation_history', None)

    # Set flag if sessions were just filtered
    sessions_updated = bool(request.GET and any(request.GET.values()))
    if sessions_updated:
        messages.success(request, "Session selection updated. The AI has been informed about the new data.")

    if sessions and request.method == "POST":
        # User has submitted a message for the conversation
        user_prompt = request.POST.get('prompt', '')

        if 'reset_conversation' in request.POST:
            # User requested to reset the conversation
            conversation_history = None
            request.session['conversation_history'] = None
            sessions_updated = False
        else:
            # Continue the conversation
            insights, conversation_history = perform_llm_analysis(
                sessions,
                user_prompt,
                conversation_history,
                sessions_updated=sessions_updated
            )
            # Save conversation to session
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
        'insights': insights,
        'conversation_history': conversation_history,
        'sessions_updated': sessions_updated
    }

    return render(request, 'llm_insights/insights.html', context)
