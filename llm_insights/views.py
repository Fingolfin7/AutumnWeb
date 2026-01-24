from django.shortcuts import render, redirect
from django.views.generic import View
from django.contrib import messages
from core.models import Sessions
from core.forms import SearchProjectForm
from core.utils import filter_sessions_by_params, filter_by_active_context
from .llm_handlers import get_llm_handler
import json
from asgiref.sync import sync_to_async


IN_MEM_CACHE = {}


async def perform_llm_analysis(
    llm_handler,
    sessions,
    user_prompt="",
    username="",
    conversation_history=None,
    sessions_updated=False,
):
    if conversation_history is None or not conversation_history:
        llm_handler.initialize_chat(username, sessions)
    else:
        # If sessions were updated, update the session data
        if sessions_updated:
            assistant_response = await llm_handler.update_session_data(
                sessions, user_prompt=user_prompt
            )
            conversation_history = llm_handler.get_conversation_history()
            return assistant_response, conversation_history

    # Send user message if provided
    if user_prompt:
        assistant_response = await llm_handler.send_message(user_prompt)
        conversation_history = llm_handler.get_conversation_history()
        return assistant_response, conversation_history

    return None, conversation_history


class InsightsView(View):
    def _provider_models(self, user):
        profile = getattr(user, "profile", None)
        provider_models = {
            "gemini": [
                # ('gemini-2.5-pro', 'Gemini 2.5 pro'),
                ("gemini-3-flash-preview", "Gemini 3 Flash"),
                ("gemini-3-pro-preview", "Gemini 3 Pro Preview"),
            ]
        }
        if profile and profile.openai_api_key_enc:
            provider_models["openai"] = [
                ("gpt-5-mini", "GPT-5 Mini"),
                ("gpt-5", "GPT-5"),
                ("gpt-5.1", "GPT-5.1"),
                ("gpt-5.2", "GPT-5.2"),
            ]
        if profile and profile.claude_api_key_enc:
            provider_models["claude"] = [
                ("claude-haiku-4.5", "Claude Haiku 4.5"),
                ("claude-sonnet-4", "Claude Sonnet 4"),
                ("claude-sonnet-4-reasoning", "Claude Sonnet 4 Reasoning"),
            ]
        return provider_models

    def _build_api_keys(self, user):
        profile = getattr(user, "profile", None)
        if not profile:
            return {}
        return {
            "gemini": profile.get_api_key("gemini"),
            "openai": profile.get_api_key("openai"),
            "claude": profile.get_api_key("claude"),
        }

    def _validate_selection(self, provider_models, provider, model):
        if provider not in provider_models:
            provider = next(iter(provider_models.keys()))
        valid_models = provider_models[provider]
        model_values = [m[0] for m in valid_models]
        if model not in model_values:
            model = valid_models[0][0]
        return provider, model

    async def get(self, request):
        # Django 5.x async user loading
        user = await request.auser()
        if not user.is_authenticated:
            from django.conf import settings
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)

        def get_all_sync_data():
            qs = (
                Sessions.objects.filter(is_active=False, user=user)
                .select_related("project", "project__context")
                .prefetch_related("subprojects", "project__tags")
            )
            qs = filter_by_active_context(
                qs, request, override_context_id=request.GET.get("context")
            )
            qs = filter_sessions_by_params(request, qs)

            # evaluate counts/dates
            session_count = qs.count()
            from django.db.models import Min, Max

            aggr = qs.aggregate(first=Min("start_time"), last=Max("end_time"))

            sessions = list(qs)
            provider_models = self._provider_models(user)

            search_form = SearchProjectForm(
                initial={
                    "project_name": request.GET.get("project_name"),
                    "start_date": request.GET.get("start_date"),
                    "end_date": request.GET.get("end_date"),
                    "note_snippet": request.GET.get("note_snippet"),
                    "context": request.GET.get("context") or "",
                    "tags": request.GET.getlist("tags"),
                },
                user=user,
            )

            sessions_updated = "filter" in request.GET
            if sessions_updated:
                request.session["sessions_updated"] = True
                messages.success(request, "Session selection updated.")

            return {
                "sessions": sessions,
                "session_count": session_count,
                "earliest_date": aggr["first"],
                "latest_date": aggr["last"],
                "provider_models": provider_models,
                "search_form": search_form,
                "sessions_updated": sessions_updated,
                "user_id": user.id,
                "username": user.username,
            }

        data = await sync_to_async(get_all_sync_data)()

        provider_models = data["provider_models"]
        selected_provider = request.GET.get("provider")
        selected_model = request.GET.get("model")

        if not selected_provider:
            selected_provider = next(iter(provider_models.keys()))

        selected_provider, selected_model = self._validate_selection(
            provider_models, selected_provider, selected_model
        )

        handler_key = f"llm_handler_{data['user_id']}_{selected_model}"
        handler = IN_MEM_CACHE.get(handler_key)
        conversation_history = handler.get_conversation_history() if handler else None
        usage_stats = (
            handler.get_usage_stats()
            if handler
            else {"prompt": 0, "response": 0, "total": 0}
        )

        provider_models_json = json.dumps(
            {
                p: [{"value": v, "label": l} for v, l in lst]
                for p, lst in provider_models.items()
            }
        )

        context = {
            "title": "Session Analysis",
            "search_form": data["search_form"],
            "prompt": request.GET.get("prompt"),
            "sessions": data["sessions"],
            "session_count": data["session_count"],
            "earliest_date": data["earliest_date"],
            "latest_date": data["latest_date"],
            "conversation_history": conversation_history,
            "sessions_updated": data["sessions_updated"],
            "selected_model": selected_model,
            "selected_provider": selected_provider,
            "usage_stats": usage_stats,
            "provider_models_json": provider_models_json,
            "providers": list(provider_models.keys()),
        }
        return await sync_to_async(render)(
            request, "llm_insights/insights.html", context
        )

    async def post(self, request):
        user = await request.auser()
        if not user.is_authenticated:
            from django.conf import settings
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)

        def get_initial_post_data():
            qs = (
                Sessions.objects.filter(is_active=False, user=user)
                .select_related("project", "project__context")
                .prefetch_related("subprojects", "project__tags")
            )
            qs = filter_by_active_context(
                qs, request, override_context_id=request.GET.get("context")
            )
            qs = filter_sessions_by_params(request, qs)

            session_count = qs.count()
            from django.db.models import Min, Max

            aggr = qs.aggregate(first=Min("start_time"), last=Max("end_time"))

            sessions = list(qs)
            sessions_updated = request.session.get("sessions_updated", False)
            provider_models = self._provider_models(user)
            api_keys = self._build_api_keys(user)

            return {
                "sessions": sessions,
                "session_count": session_count,
                "earliest_date": aggr["first"],
                "latest_date": aggr["last"],
                "sessions_updated": sessions_updated,
                "provider_models": provider_models,
                "api_keys": api_keys,
                "user_id": user.id,
                "username": user.username,
            }

        data = await sync_to_async(get_initial_post_data)()

        provider_models = data["provider_models"]
        selected_provider = request.POST.get("provider")
        selected_model = request.POST.get("model")

        if not selected_provider:
            selected_provider = next(iter(provider_models.keys()))

        selected_provider, selected_model = self._validate_selection(
            provider_models, selected_provider, selected_model
        )

        handler_key = f"llm_handler_{data['user_id']}_{selected_model}"
        handler = IN_MEM_CACHE.get(handler_key)

        if not handler:
            handler = get_llm_handler(model=selected_model, api_keys=data["api_keys"])
            IN_MEM_CACHE[handler_key] = handler

        handler = IN_MEM_CACHE.get(handler_key)
        conversation_history = handler.get_conversation_history() if handler else None

        if "reset_conversation" in request.POST:

            def reset_session_updated():
                request.session["sessions_updated"] = False

            await sync_to_async(reset_session_updated)()
            IN_MEM_CACHE.pop(handler_key, None)
            conversation_history = None
        else:
            user_prompt = request.POST.get("prompt", "")
            insights, conversation_history = await perform_llm_analysis(
                llm_handler=handler,
                sessions=data["sessions"],
                user_prompt=user_prompt,
                username=data["username"],
                conversation_history=conversation_history,
                sessions_updated=data["sessions_updated"],
            )

            def finalize_post_session():
                request.session["sessions_updated"] = False

            await sync_to_async(finalize_post_session)()

        usage_stats = (
            handler.get_usage_stats()
            if handler
            else {"prompt": 0, "response": 0, "total": 0}
        )
        provider_models_json = json.dumps(
            {
                p: [{"value": v, "label": l} for v, l in lst]
                for p, lst in provider_models.items()
            }
        )

        def get_final_form():
            return SearchProjectForm(
                initial={
                    "project_name": request.GET.get("project_name"),
                    "start_date": request.GET.get("start_date"),
                    "end_date": request.GET.get("end_date"),
                    "note_snippet": request.GET.get("note_snippet"),
                    "context": request.GET.get("context") or "",
                    "tags": request.GET.getlist("tags"),
                },
                user=user,
            )

        search_form = await sync_to_async(get_final_form)()

        context = {
            "title": "Session Analysis",
            "search_form": search_form,
            "sessions": data["sessions"],
            "session_count": data["session_count"],
            "earliest_date": data["earliest_date"],
            "latest_date": data["latest_date"],
            "conversation_history": conversation_history,
            "sessions_updated": False,
            "selected_model": selected_model,
            "selected_provider": selected_provider,
            "usage_stats": usage_stats,
            "provider_models_json": provider_models_json,
            "providers": list(provider_models.keys()),
        }

        return await sync_to_async(render)(
            request, "llm_insights/insights.html", context
        )
