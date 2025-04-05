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


def perform_llm_analysis(llm_handler, sessions, user_prompt="", username="", conversation_history=None, sessions_updated=False):
    if conversation_history is None or not conversation_history:
        llm_handler.initialize_chat(username, sessions)
    else:
        # If sessions were updated, update the session data
        if sessions_updated:
            assistant_response = llm_handler.update_session_data(sessions, user_prompt=user_prompt)
            conversation_history = llm_handler.get_conversation_history()
            return assistant_response, conversation_history

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
        request.session["sessions_updated"] = sessions_updated
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
            'sessions_updated': sessions_updated,
            'selected_model': request.GET.get('model', "gemini-2.0-flash")
        }

        return render(request, 'llm_insights/insights.html', context)

    def post(self, request):
        sessions = Sessions.objects.filter(is_active=False, user=request.user)
        sessions = filter_sessions_by_params(request, sessions)
        sessions_updated = request.session.get("sessions_updated", False)
        conversation_history = request.session.get('conversation_history', None)

        # Retrieve selected model from form with default
        selected_model = request.POST.get("model", "gemini-2.0-flash")
        handler_key = f"llm_handler_{request.user.id}_{selected_model}"
        handler = cache.get(handler_key)

        if not handler:
            handler = get_llm_handler(model=selected_model)
            cache.set(handler_key, handler, 3600)  # Cache for 1 hour

        if 'reset_conversation' in request.POST:
            # Reset conversation
            conversation_history = None
            request.session['conversation_history'] = None
            request.session['sessions_updated'] = False
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
            sessions_updated = False
            cache.set(handler_key, handler, 3600)
            request.session['conversation_history'] = conversation_history
            request.session['sessions_updated'] = sessions_updated

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
            'sessions_updated': sessions_updated,
            'selected_model': selected_model,
        }

        return render(request, 'llm_insights/insights.html', context)
