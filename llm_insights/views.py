from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import View
from django.contrib import messages
from core.models import Sessions
from core.forms import SearchProjectForm
from core.utils import filter_sessions_by_params, filter_by_active_context
from .llm_handlers import get_llm_handler
from .models import LLMChat, LLMMessage
import json
import uuid
from asgiref.sync import sync_to_async
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
import datetime


async def perform_llm_analysis(
    llm_handler,
    sessions,
    user_prompt="",
    username="",
    conversation_history=None,
    sessions_updated=False,
    chat_obj=None,
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

            # Save to DB if chat_obj exists
            if chat_obj:
                latest = conversation_history[-3:]
                for msg in latest:
                    await sync_to_async(LLMMessage.objects.create)(
                        chat=chat_obj,
                        role=msg["role"],
                        content=msg["content"],
                        metadata={
                            "sources": msg.get("sources", []),
                            "model": msg.get("model", ""),
                            "usage": msg.get("usage", {}),
                        },
                    )

            return assistant_response, conversation_history

    # Send user message if provided
    if user_prompt:
        assistant_response = await llm_handler.send_message(user_prompt)
        conversation_history = llm_handler.get_conversation_history()

        # Save to DB if chat_obj exists
        if chat_obj:
            if len(conversation_history) <= 3:
                to_save = conversation_history
            else:
                to_save = conversation_history[-2:]

            for msg in to_save:
                await sync_to_async(LLMMessage.objects.create)(
                    chat=chat_obj,
                    role=msg["role"],
                    content=msg["content"],
                    metadata={
                        "sources": msg.get("sources", []),
                        "model": msg.get("model", ""),
                        "usage": msg.get("usage", {}),
                    },
                )

        return assistant_response, conversation_history

    return None, conversation_history


@login_required
def delete_chat(request, chat_id):
    chat = get_object_or_404(LLMChat, id=chat_id, user=request.user)
    chat.delete()
    messages.success(request, "Chat deleted.")
    return redirect("insights")


class InsightsView(View):
    def _provider_models(self, user):
        profile = getattr(user, "profile", None)
        provider_models = {
            "gemini": [
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
                ("claude-sonnet-4.5", "Claude Sonnet 4.5"),
                ("claude-opus-4.5", "Claude Opus 4.5"),
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
        if not provider or provider not in provider_models:
            provider = next(iter(provider_models.keys()))
        valid_models = provider_models[provider]
        model_values = [m[0] for m in valid_models]
        if not model or model not in model_values:
            model = valid_models[0][0]
        return provider, model

    def _extract_filter_params(self, request):
        """Extract relevant filter params from request.GET or request.POST"""
        params = {}
        keys = ["project_name", "start_date", "end_date", "note_snippet", "context"]
        # Get scalar values
        for key in keys:
            val = request.GET.get(key) or request.POST.get(key)
            if val:
                params[key] = val

        # Get lists (tags)
        tags = request.GET.getlist("tags") or request.POST.getlist("tags")
        if tags:
            params["tags"] = tags

        return params

    async def get(self, request, chat_id=None):
        user = await request.auser()
        if not user.is_authenticated:
            from django.conf import settings
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)

        def get_all_sync_data():
            # Get current chat if any
            chat_obj = None
            history = []

            # Determine filters to use
            # If explicit filters in URL, use them.
            # If not, and we have a chat, use chat.filters
            current_filters = self._extract_filter_params(request)
            using_stored_filters = False

            filter_keys = [
                "project_name",
                "start_date",
                "end_date",
                "note_snippet",
                "context",
                "tags",
                "filter",
            ]
            has_explicit_filters = any(k in request.GET for k in filter_keys)

            if chat_id:
                chat_obj = get_object_or_404(LLMChat, id=chat_id, user=user)
                history = [
                    {
                        "role": m.role,
                        "content": m.content,
                        "sources": m.metadata.get("sources", []),
                        "model": m.metadata.get("model", ""),
                        "metadata": m.metadata,
                    }
                    for m in chat_obj.messages.all()
                ]

                # If no explicit filters in URL (checking 'filter' param is a good proxy,
                # or just checking if params are empty), try to use stored filters.
                if not has_explicit_filters and chat_obj.filters:
                    current_filters = chat_obj.filters
                    using_stored_filters = True

            # If New Chat (no chat_id) and no filters provided, set default dates
            # to match the frontend JS behavior (Current Month)
            elif not has_explicit_filters:
                now = timezone.now()
                # Start of current month
                start_date = now.replace(day=1).date().isoformat()
                # Today
                end_date = now.date().isoformat()

                current_filters["start_date"] = start_date
                current_filters["end_date"] = end_date

            # Get user's chat list
            recent_chats = LLMChat.objects.filter(user=user).only(
                "id", "title", "updated_at"
            )[:20]

            qs = (
                Sessions.objects.filter(is_active=False, user=user)
                .select_related("project", "project__context")
                .prefetch_related("subprojects", "project__tags")
            )

            # Handle context filter
            ctx_id = current_filters.get("context") or request.GET.get("context")
            qs = filter_by_active_context(qs, request, override_context_id=ctx_id)

            # Use our enhanced filter function with overrides if needed
            # For new chats (chat_id is None), we ALWAYS use current_filters (from URL)
            # For existing chats, we use stored filters unless explicit override in URL
            if using_stored_filters or not chat_id:
                qs = filter_sessions_by_params(
                    request, qs, params_override=current_filters
                )
            else:
                # Fallback to standard request.GET processing if we have explicit filters
                # (which match current_filters anyway, but logic flows better)
                qs = filter_sessions_by_params(
                    request, qs, params_override=current_filters
                )

            session_count = qs.count()
            from django.db.models import Min, Max

            aggr = qs.aggregate(first=Min("start_time"), last=Max("end_time"))
            sessions = list(qs)
            provider_models = self._provider_models(user)

            # Build form initial data from current_filters
            search_form = SearchProjectForm(
                initial={
                    "project_name": current_filters.get("project_name"),
                    "start_date": current_filters.get("start_date"),
                    "end_date": current_filters.get("end_date"),
                    "note_snippet": current_filters.get("note_snippet"),
                    "context": current_filters.get("context") or "",
                    "tags": current_filters.get("tags", []),
                },
                user=user,
            )

            sessions_updated = "filter" in request.GET
            if sessions_updated:
                request.session["sessions_updated"] = True
                messages.success(request, "Session selection updated.")

            # Calculate usage stats from messages
            usage_stats = {"prompt": 0, "response": 0, "total": 0}
            for m in history:
                meta = m.get("metadata") or {}
                usage = meta.get("usage") or {}
                usage_stats["prompt"] += usage.get("prompt", 0) or 0
                usage_stats["response"] += usage.get("response", 0) or 0
            usage_stats["total"] = usage_stats["prompt"] + usage_stats["response"]

            return {
                "sessions": sessions,
                "session_count": session_count,
                "earliest_date": aggr["first"],
                "latest_date": aggr["last"],
                "provider_models": provider_models,
                "search_form": search_form,
                "sessions_updated": sessions_updated,
                "username": user.username,
                "chat_obj": chat_obj,
                "conversation_history": history,
                "recent_chats": list(recent_chats),
                "usage_stats": usage_stats,
            }

        data = await sync_to_async(get_all_sync_data)()

        provider_models = data["provider_models"]
        # Use model from chat_obj if available
        initial_provider = (
            data["chat_obj"].model.split(":")[0] if data["chat_obj"] else None
        )
        initial_model = (
            data["chat_obj"].model.split(":")[1]
            if data["chat_obj"] and ":" in data["chat_obj"].model
            else (data["chat_obj"].model if data["chat_obj"] else None)
        )

        selected_provider = request.GET.get("provider") or initial_provider
        selected_model = request.GET.get("model") or initial_model

        selected_provider, selected_model = self._validate_selection(
            provider_models, selected_provider, selected_model
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
            "sessions": data["sessions"],
            "session_count": data["session_count"],
            "earliest_date": data["earliest_date"],
            "latest_date": data["latest_date"],
            "conversation_history": data["conversation_history"],
            "sessions_updated": data["sessions_updated"],
            "selected_model": selected_model,
            "selected_provider": selected_provider,
            "provider_models_json": provider_models_json,
            "providers": list(provider_models.keys()),
            "chat_id": chat_id,
            "recent_chats": data["recent_chats"],
            "usage_stats": data["usage_stats"],
            "username": data["username"],
        }
        return await sync_to_async(render)(
            request, "llm_insights/insights.html", context
        )

    async def post(self, request, chat_id=None):
        user = await request.auser()
        if not user.is_authenticated:
            from django.conf import settings
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)

        def get_initial_post_data():
            chat_obj = None
            if chat_id:
                chat_obj = get_object_or_404(LLMChat, id=chat_id, user=user)

            # Determine filters: if 'filter' button used, use POST params.
            # Else if just sending message, try to use stored filters.
            current_filters = self._extract_filter_params(request)
            using_stored_filters = False

            is_filtering = "filter" in request.POST
            if not is_filtering and chat_obj and chat_obj.filters:
                # If we are NOT explicitly filtering, we should stick to the pinned filters
                # unless we are creating a NEW chat (no chat_obj yet), in which case we use current_filters
                current_filters = chat_obj.filters
                using_stored_filters = True

            # Apply defaults for New Chat if no filters provided (same logic as GET)
            elif not chat_obj:
                filter_keys = [
                    "project_name",
                    "start_date",
                    "end_date",
                    "note_snippet",
                    "context",
                    "tags",
                ]
                # Check if current_filters has any meaningful values
                has_values = any(current_filters.get(k) for k in filter_keys)
                if not has_values:
                    now = timezone.now()
                    current_filters["start_date"] = (
                        now.replace(day=1).date().isoformat()
                    )
                    current_filters["end_date"] = now.date().isoformat()

            qs = (
                Sessions.objects.filter(is_active=False, user=user)
                .select_related("project", "project__context")
                .prefetch_related("subprojects", "project__tags")
            )

            ctx_id = current_filters.get("context")
            qs = filter_by_active_context(qs, request, override_context_id=ctx_id)

            if using_stored_filters:
                qs = filter_sessions_by_params(
                    request, qs, params_override=current_filters
                )
            else:
                qs = filter_sessions_by_params(
                    request, qs, params_override=current_filters
                )  # Use POST params

            session_count = qs.count()
            from django.db.models import Min, Max

            aggr = qs.aggregate(first=Min("start_time"), last=Max("end_time"))
            sessions = list(qs)

            # sessions_updated logic:
            # TRUE if user clicked 'filter' OR if we just created a new chat with filters.
            # FALSE if we are just chatting in an existing context.
            sessions_updated = request.session.get("sessions_updated", False)
            if is_filtering:
                sessions_updated = True

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
                "username": user.username,
                "chat_obj": chat_obj,
                "current_filters": current_filters,
                "is_filtering": is_filtering,
            }

        data = await sync_to_async(get_initial_post_data)()

        provider_models = data["provider_models"]
        selected_provider = request.POST.get("provider")
        selected_model = request.POST.get("model")

        selected_provider, selected_model = self._validate_selection(
            provider_models, selected_provider, selected_model
        )

        chat_obj = data["chat_obj"]
        current_filters = data["current_filters"]
        is_filtering = data["is_filtering"]

        if not chat_obj:
            user_prompt = request.POST.get("prompt", "")
            title = user_prompt[:40] + "..." if len(user_prompt) > 40 else user_prompt
            if not title:
                title = "New Chat"

            chat_obj = await sync_to_async(LLMChat.objects.create)(
                user=user,
                title=title,
                model=f"{selected_provider}:{selected_model}",
                filters=current_filters,
            )
            chat_id = chat_obj.id
        elif is_filtering:
            # Explicit filter update -> update pinned filters
            chat_obj.filters = current_filters
            await sync_to_async(chat_obj.save)()

        handler = get_llm_handler(model=selected_model, api_keys=data["api_keys"])

        def load_history_sync():
            return [
                {
                    "role": m.role,
                    "content": m.content,
                    "sources": m.metadata.get("sources", []),
                    "model": m.metadata.get("model", ""),
                    "usage": m.metadata.get("usage", {}),
                }
                for m in chat_obj.messages.all()
            ]

        history = await sync_to_async(load_history_sync)()
        handler.set_conversation_history(history)

        if "reset_conversation" in request.POST:
            return redirect("insights")
        else:
            user_prompt = request.POST.get("prompt", "")
            insights, conversation_history = await perform_llm_analysis(
                llm_handler=handler,
                sessions=data["sessions"],
                user_prompt=user_prompt,
                username=data["username"],
                conversation_history=history,
                sessions_updated=data["sessions_updated"],
                chat_obj=chat_obj,
            )

            def finalize_post_session():
                request.session["sessions_updated"] = False
                chat_obj.model = f"{selected_provider}:{selected_model}"
                chat_obj.save()

            await sync_to_async(finalize_post_session)()

        return redirect(reverse("insights_detail", kwargs={"chat_id": chat_id}))
