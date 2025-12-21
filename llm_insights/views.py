from django.shortcuts import render
from django.views.generic import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from core.models import Sessions
from core.forms import SearchProjectForm
from core.utils import filter_sessions_by_params, filter_by_active_context
from .llm_handlers import get_llm_handler
import json


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
    def _provider_models(self, user):
        profile = getattr(user, 'profile', None)
        provider_models = {
            'gemini': [
                #('gemini-2.5-pro', 'Gemini 2.5 pro'),
                ('gemini-3-flash-preview', 'Gemini 3 Flash'),
                ('gemini-3-pro-preview', 'Gemini 3 Pro Preview'),
            ]
        }
        if profile and profile.openai_api_key_enc:
            provider_models['openai'] = [
                ('gpt-5-mini', 'GPT-5 Mini'),
                ('gpt-5', 'GPT-5'),
                ('gpt-5.1', 'GPT-5.1'),
                ('gpt-5.2', 'GPT-5.2'),
            ]
        if profile and profile.claude_api_key_enc:
            provider_models['claude'] = [
                ('claude-haiku-4.5', 'Claude Haiku 4.5'),
                ('claude-sonnet-4', 'Claude Sonnet 4'),
                ('claude-sonnet-4-reasoning', 'Claude Sonnet 4 Reasoning'),
            ]
        return provider_models

    def _build_api_keys(self, user):
        profile = getattr(user, 'profile', None)
        if not profile:
            return {}
        return {
            'gemini': profile.get_api_key('gemini'),
            'openai': profile.get_api_key('openai'),
            'claude': profile.get_api_key('claude'),
        }

    def _validate_selection(self, provider_models, provider, model):
        if provider not in provider_models:
            provider = next(iter(provider_models.keys()))
        valid_models = provider_models[provider]
        model_values = [m[0] for m in valid_models]
        if model not in model_values:
            model = valid_models[0][0]
        return provider, model

    def get(self, request):
        sessions = Sessions.objects.filter(is_active=False, user=request.user)
        # Allow ?context= to scope sessions for insights as well
        sessions = filter_by_active_context(sessions, request, override_context_id=request.GET.get('context'))
        sessions = filter_sessions_by_params(request, sessions)
        provider_models = self._provider_models(request.user)
        selected_provider = request.GET.get('provider', next(iter(provider_models.keys())))
        selected_model = request.GET.get('model')
        selected_provider, selected_model = self._validate_selection(provider_models, selected_provider, selected_model)
        handler_key = f"llm_handler_{request.user.id}_{selected_model}"
        handler = IN_MEM_CACHE.get(handler_key)
        conversation_history = handler.get_conversation_history() if handler else None
        usage_stats = handler.get_usage_stats() if handler else {"prompt": 0, "response": 0, "total": 0}
        sessions_updated = 'filter' in request.GET
        request.session["sessions_updated"] = sessions_updated
        if sessions_updated:
            messages.success(request, "Session selection updated.")
        provider_models_json = json.dumps({p: [{'value': v, 'label': l} for v, l in lst] for p, lst in provider_models.items()})
        providers = list(provider_models.keys())
        context = {
            'title': 'Session Analysis',
            'search_form': SearchProjectForm(
                initial={
                    'project_name': request.GET.get('project_name'),
                    'start_date': request.GET.get('start_date'),
                    'end_date': request.GET.get('end_date'),
                    'note_snippet': request.GET.get('note_snippet'),
                    'context': request.GET.get('context') or '',
                    'tags': request.GET.getlist('tags'),
                },
                user=request.user,
            ),
            'prompt': request.GET.get('prompt'),
            'sessions': sessions,
            'conversation_history': conversation_history,
            'sessions_updated': sessions_updated,
            'selected_model': selected_model,
            'selected_provider': selected_provider,
            'usage_stats': usage_stats,
            'provider_models_json': provider_models_json,
            'providers': providers,
        }
        return render(request, 'llm_insights/insights.html', context)

    def post(self, request):
        sessions = Sessions.objects.filter(is_active=False, user=request.user)
        sessions = filter_by_active_context(sessions, request, override_context_id=request.POST.get('context'))
        sessions = filter_sessions_by_params(request, sessions)
        sessions_updated = request.session.get("sessions_updated", False)
        provider_models = self._provider_models(request.user)
        selected_provider = request.POST.get("provider", next(iter(provider_models.keys())))
        selected_model = request.POST.get("model")
        selected_provider, selected_model = self._validate_selection(provider_models, selected_provider, selected_model)
        handler_key = f"llm_handler_{request.user.id}_{selected_model}"
        handler = IN_MEM_CACHE.get(handler_key)
        if not handler:
            api_keys = self._build_api_keys(request.user)
            handler = get_llm_handler(model=selected_model, api_keys=api_keys)
            IN_MEM_CACHE[handler_key] = handler
        handler = IN_MEM_CACHE.get(handler_key)
        conversation_history = handler.get_conversation_history() if handler else None
        if 'reset_conversation' in request.POST:
            request.session['sessions_updated'] = False
            IN_MEM_CACHE.pop(handler_key, None)
            conversation_history = None
        else:
            user_prompt = request.POST.get('prompt', '')
            insights, conversation_history = perform_llm_analysis(
                llm_handler=handler,
                sessions=sessions,
                user_prompt=user_prompt,
                username=request.user.username,
                conversation_history=conversation_history,
                sessions_updated=sessions_updated
            )
            sessions_updated = False
            request.session['sessions_updated'] = sessions_updated
        usage_stats = handler.get_usage_stats() if handler else {"prompt": 0, "response": 0, "total": 0}
        provider_models_json = json.dumps({p: [{'value': v, 'label': l} for v, l in lst] for p, lst in provider_models.items()})
        providers = list(provider_models.keys())
        context = {
            'title': 'Session Analysis',
            'search_form': SearchProjectForm(
                initial={
                    'project_name': request.GET.get('project_name'),
                    'start_date': request.GET.get('start_date'),
                    'end_date': request.GET.get('end_date'),
                    'note_snippet': request.GET.get('note_snippet'),
                    'context': request.GET.get('context') or '',
                    'tags': request.GET.getlist('tags'),
                },
                user=request.user,
            ),
            'sessions': sessions,
            'conversation_history': conversation_history,
            'sessions_updated': sessions_updated,
            'selected_model': selected_model,
            'selected_provider': selected_provider,
            'usage_stats': usage_stats,
            'provider_models_json': provider_models_json,
            'providers': providers,
        }

        return render(request, 'llm_insights/insights.html', context)