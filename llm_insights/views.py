from django.shortcuts import render
from django.views.generic import View
from django.contrib.auth.mixins import LoginRequiredMixin
from datetime import datetime, timedelta
from django.contrib import messages
from core.models import Sessions
from core.forms import SearchProjectForm
from core.utils import filter_sessions_by_params
from .llm_handlers import get_llm_handler


IN_MEM_CACHE = {}


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

        # Retrieve conversation history from session
        conv_histories = request.session.get('conversation_history', {})
        if not isinstance(conv_histories, dict):
            conv_histories = {}

        # Load conversation history for the selected model
        selected_model = request.GET.get('model', "gemini-2.0-pro-exp-02-05")
        conversation_history = conv_histories.get(selected_model)

        # Set flag if the filter button was pressed
        sessions_updated = 'filter' in request.GET
        request.session["sessions_updated"] = sessions_updated
        if sessions_updated:
            messages.success(request, "Session selection updated.")

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
            'selected_model': selected_model
        }

        return render(request, 'llm_insights/insights.html', context)

    def post(self, request):
        sessions = Sessions.objects.filter(is_active=False, user=request.user)
        sessions = filter_sessions_by_params(request, sessions)
        sessions_updated = request.session.get("sessions_updated", False)

        conv_histories = request.session.get('conversation_history', {})
        if not isinstance(conv_histories, dict):
            conv_histories = {}

        # Retrieve selected model from form with default
        selected_model = request.POST.get("model", "gemini-2.0-pro-exp-02-05")
        handler_key = f"llm_handler_{request.user.id}_{selected_model}"
        conversation_history = conv_histories.get(selected_model)

        # Check if the handler is in memory and not expired
        handler = IN_MEM_CACHE.get(handler_key)

        if not handler:
            handler = get_llm_handler(model=selected_model)
            IN_MEM_CACHE[handler_key] = handler

        if 'reset_conversation' in request.POST:
            # Reset conversation for the selected model
            conversation_history = None
            conv_histories[selected_model] = None
            request.session['conversation_history'] = conv_histories
            request.session['sessions_updated'] = False
            IN_MEM_CACHE.pop(handler_key)
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
            conv_histories[selected_model] = conversation_history
            request.session['conversation_history'] = conv_histories
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
