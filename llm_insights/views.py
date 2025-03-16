from datetime import datetime, timedelta

from django.contrib.admin.templatetags.admin_list import search_form
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from core.models import Sessions, Projects, SubProjects
from core.forms import SearchProjectForm
from core.utils import filter_by_projects, in_window, parse_date_or_datetime, filter_sessions_by_params
import json
from google import genai
from AutumnWeb import settings


def perform_llm_analysis(sessions, user_prompt=""):
    # Prepare session data in a format suitable for LLM
    session_data = []
    for session in sessions:
        session_data.append({
            'project': session.project.name,
            'subprojects': [sp.name for sp in session.subprojects.all()],
            'date': session.end_time.strftime('%Y-%m-%d'),
            'start_time': session.start_time.strftime('%H:%M:%S'),
            'end_time': session.end_time.strftime('%H:%M:%S'),
            'duration_minutes': session.duration,
            'note': session.note or ""
        })

    # Basic prompt with user's custom prompt
    base_prompt = f"""
    You are an expert project and time tracking analyst. Your job is to analyze projects, sessions, 
    and session logs to provide insights based on the data provided.
    
    The user's name is {sessions[0].user.username} and this application is known as "Autumn".
    
    If possible please quote the session notes and dates/times for any insights you provide.
    
    User Prompt: {user_prompt}

    Sessions data:
    {json.dumps(session_data, indent=2)}
    """

    # call gemini API
    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=base_prompt)

        return response.text
    except Exception as e:
        return f"Error performing analysis: {str(e)}"

@login_required
def insights_view(request):
    sessions = Sessions.objects.filter(is_active=False, user=request.user)
    sessions = filter_sessions_by_params(request, sessions)

    insights = None

    if sessions and request.method == "POST":
        # User has submitted sessions for analysis
        insights = perform_llm_analysis(sessions, request.POST.get('prompt', ''))

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
        'insights': insights
    }

    return render(request, 'llm_insights/insights.html', context)
