from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import View
from django.contrib import messages
from django.http import StreamingHttpResponse
from django.db import close_old_connections, transaction
from core.models import Sessions
from core.forms import SearchProjectForm
from core.templatetags.markdown_render import markdown as render_markdown
from core.utils import filter_sessions_by_params, filter_by_active_context, build_exclude_project_meta
from .llm_handlers import get_llm_handler
from .models import LLMChat, LLMMessage
import json
import uuid
import asyncio
import queue
import threading
from asgiref.sync import sync_to_async
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
import datetime
import os
from users.codex_auth import (
    CodexAuthError,
    access_token_expires_soon,
    deserialize_token_bundle,
    refresh_token_bundle,
    serialize_token_bundle,
)


SSE_HEARTBEAT_SECONDS = 15


def stream_event(event_name, payload):
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"


def stream_keepalive():
    return ": keep-alive\n\n"


def stream_queue_events(event_queue, stream_done, heartbeat_seconds=SSE_HEARTBEAT_SECONDS):
    while True:
        try:
            item = event_queue.get(timeout=heartbeat_seconds)
        except queue.Empty:
            yield stream_keepalive()
            continue
        if item is stream_done:
            break
        yield item


def user_has_ai_features(user):
    profile = getattr(user, "profile", None)
    return bool(profile and profile.ai_features_enabled)


def ai_features_disabled_response(request):
    messages.error(request, "AI features are disabled for this account.")
    return redirect("home")


def database_sync_to_async(func):
    def wrapped(*args, **kwargs):
        close_old_connections()
        try:
            return func(*args, **kwargs)
        finally:
            close_old_connections()

    return sync_to_async(wrapped)


async def save_llm_messages(chat_obj, messages_to_save):
    chat_id = getattr(chat_obj, "id", chat_obj)

    def create_messages():
        chat = LLMChat.objects.get(id=chat_id)
        with transaction.atomic():
            for msg in messages_to_save:
                LLMMessage.objects.create(
                    chat=chat,
                    role=msg["role"],
                    content=msg["content"],
                    metadata={
                        "sources": msg.get("sources", []),
                        "model": msg.get("model", ""),
                        "usage": msg.get("usage", {}),
                        "auth_source": msg.get("auth_source", ""),
                        "error": msg.get("error", False),
                        "error_message": msg.get("error_message", ""),
                    },
                )

    await database_sync_to_async(create_messages)()


async def save_partial_stream_messages(
    chat_obj,
    previous_history,
    llm_handler,
    user_prompt,
    assistant_content,
    model,
    error_message,
):
    current_history = llm_handler.get_conversation_history() if llm_handler else []
    pending_messages = (
        current_history[len(previous_history):]
        if len(current_history) >= len(previous_history)
        else []
    )

    if pending_messages:
        has_assistant = any(msg.get("role") == "assistant" for msg in pending_messages)
        if not has_assistant:
            pending_messages.append(
                {
                    "role": "assistant",
                    "content": assistant_content,
                    "model": model,
                    "usage": {"prompt": 0, "response": 0},
                    "error": True,
                    "error_message": error_message,
                }
            )
    elif user_prompt:
        pending_messages = [
            {"role": "user", "content": user_prompt},
            {
                "role": "assistant",
                "content": assistant_content,
                "model": model,
                "usage": {"prompt": 0, "response": 0},
                "error": True,
                "error_message": error_message,
            },
        ]

    if pending_messages:
        await save_llm_messages(chat_obj, pending_messages)


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


async def perform_llm_analysis_stream(
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
    elif sessions_updated:
        async for chunk in llm_handler.stream_update_session_data(
            sessions, user_prompt=user_prompt
        ):
            yield chunk
        conversation_history = llm_handler.get_conversation_history()
        if chat_obj:
            await save_llm_messages(chat_obj, conversation_history[-3:])
        return

    if user_prompt:
        async for chunk in llm_handler.stream_message(user_prompt):
            yield chunk
        conversation_history = llm_handler.get_conversation_history()
        if chat_obj:
            if len(conversation_history) <= 3:
                to_save = conversation_history
            else:
                to_save = conversation_history[-2:]
            await save_llm_messages(chat_obj, to_save)


@login_required
def delete_chat(request, chat_id):
    if not user_has_ai_features(request.user):
        return ai_features_disabled_response(request)
    chat = get_object_or_404(LLMChat, id=chat_id, user=request.user)
    chat.delete()
    messages.success(request, "Chat deleted.")
    return redirect("insights")


class InsightsView(View):
    OPENAI_REASONING_EFFORTS = ["minimal", "low", "medium", "high"]

    def _has_env_api_key(self, env_var):
        return bool(os.environ.get(env_var))

    def _provider_models(self, user):
        profile = getattr(user, "profile", None)
        provider_models = {
            "gemini": [
                ("gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite"),
                ("gemini-3.1-pro-preview", "Gemini 3.1 Pro Preview"),
            ]
        }
        if (
            (profile and profile.openai_api_key_enc)
            or (profile and profile.openai_chatgpt_token_enc)
            or self._has_env_api_key("OPENAI_API_KEY")
        ):
            provider_models["openai"] = [
                ("gpt-5.5", "GPT-5.5"),
                ("gpt-5.4", "GPT-5.4"),
                ("gpt-5.2", "GPT-5.2"),
                ("gpt-5", "GPT-5"),
                ("gpt-5-mini", "GPT-5 Mini"),
            ]
        if profile and profile.claude_api_key_enc:
            provider_models["claude"] = [
                ("claude-haiku-4.5", "Claude Haiku 4.5"),
                ("claude-sonnet-4.6", "Claude Sonnet 4.6"),
                ("claude-opus-4.6", "Claude Opus 4.6"),
            ]
        return provider_models

    def _openai_connection_source(self, user):
        profile = getattr(user, "profile", None)
        if profile and profile.openai_chatgpt_token_enc and profile.openai_api_key_enc:
            return "codex_with_api_fallback"
        if profile and profile.openai_chatgpt_token_enc:
            return "codex"
        if profile and profile.openai_api_key_enc:
            return "profile"
        if self._has_env_api_key("OPENAI_API_KEY"):
            return "server"
        return ""

    def _build_api_keys(self, user):
        profile = getattr(user, "profile", None)
        if not profile:
            return {}
        return {
            "gemini": profile.get_api_key("gemini"),
            "openai": profile.get_api_key("openai"),
            "openai_chatgpt": self._get_openai_chatgpt_access_token(profile),
            "claude": profile.get_api_key("claude"),
        }

    def _get_openai_chatgpt_access_token(self, profile):
        bundle = deserialize_token_bundle(profile.get_api_key("openai_chatgpt"))
        if not bundle:
            return None
        if not access_token_expires_soon(bundle):
            return bundle.get("access_token")
        try:
            refreshed = refresh_token_bundle(bundle)
        except CodexAuthError:
            return bundle.get("access_token")
        if refreshed != bundle:
            profile.set_api_key("openai_chatgpt", serialize_token_bundle(refreshed))
            profile.save(update_fields=["openai_chatgpt_token_enc"])
        return refreshed.get("access_token")

    def _validate_selection(self, provider_models, provider, model):
        if not provider or provider not in provider_models:
            provider = next(iter(provider_models.keys()))
        valid_models = provider_models[provider]
        model_values = [m[0] for m in valid_models]
        if not model or model not in model_values:
            model = valid_models[0][0]
        return provider, model

    def _validate_reasoning_effort(self, provider, effort):
        if provider != "openai":
            return ""
        if effort not in self.OPENAI_REASONING_EFFORTS:
            return "medium"
        return effort

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

        # Get lists (exclude_projects)
        exclude_projects = request.GET.getlist("exclude_projects") or request.POST.getlist("exclude_projects")
        if exclude_projects:
            params["exclude_projects"] = exclude_projects

        return params

    async def get(self, request, chat_id=None):
        user = await request.auser()
        if not user.is_authenticated:
            from django.conf import settings
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        if not await sync_to_async(user_has_ai_features)(user):
            return await sync_to_async(ai_features_disabled_response)(request)

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
                "exclude_projects",
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
                    "exclude_projects": current_filters.get("exclude_projects", []),
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
                "openai_connection_source": self._openai_connection_source(user),
                "exclude_project_meta_json": json.dumps(build_exclude_project_meta(user)),
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
        stored_reasoning_effort = (
            data["chat_obj"].filters.get("reasoning_effort")
            if data["chat_obj"] and data["chat_obj"].filters
            else None
        )
        selected_reasoning_effort = self._validate_reasoning_effort(
            selected_provider,
            request.GET.get("reasoning_effort") or stored_reasoning_effort,
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
            "selected_reasoning_effort": selected_reasoning_effort,
            "openai_reasoning_efforts": self.OPENAI_REASONING_EFFORTS,
            "provider_models_json": provider_models_json,
            "providers": list(provider_models.keys()),
            "chat_id": chat_id,
            "recent_chats": data["recent_chats"],
            "usage_stats": data["usage_stats"],
            "username": data["username"],
            "openai_connection_source": data["openai_connection_source"],
            "exclude_project_meta_json": data["exclude_project_meta_json"],
        }
        return await sync_to_async(render)(
            request, "llm_insights/insights.html", context
        )

    def _get_initial_post_data(self, request, user, chat_id=None):
        chat_obj = None
        if chat_id:
            chat_obj = get_object_or_404(LLMChat, id=chat_id, user=user)

        current_filters = self._extract_filter_params(request)

        is_filtering = "filter" in request.POST
        if not is_filtering and chat_obj and chat_obj.filters:
            current_filters = chat_obj.filters
        elif not chat_obj:
            filter_keys = [
                "project_name",
                "start_date",
                "end_date",
                "note_snippet",
                "context",
                "tags",
                "exclude_projects",
            ]
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
        qs = filter_sessions_by_params(request, qs, params_override=current_filters)

        sessions = list(qs)
        sessions_updated = request.session.get("sessions_updated", False)
        if is_filtering:
            sessions_updated = True

        return {
            "sessions": sessions,
            "sessions_updated": sessions_updated,
            "provider_models": self._provider_models(user),
            "api_keys": self._build_api_keys(user),
            "username": user.username,
            "chat_obj": chat_obj,
            "current_filters": current_filters,
            "is_filtering": is_filtering,
        }

    def stream(self, request, chat_id=None):
        user = request.user
        if not user.is_authenticated:
            return StreamingHttpResponse(
                iter([stream_event("error", {"message": "Authentication required."})]),
                content_type="text/event-stream",
                status=401,
            )
        if not user_has_ai_features(user):
            return StreamingHttpResponse(
                iter([stream_event("error", {"message": "AI features are disabled for this account."})]),
                content_type="text/event-stream",
                status=403,
            )

        try:
            post_data = request.POST.copy()
            data = self._get_initial_post_data(request, user, chat_id)

            provider_models = data["provider_models"]
            selected_provider = post_data.get("provider")
            selected_model = post_data.get("model")
            selected_provider, selected_model = self._validate_selection(
                provider_models, selected_provider, selected_model
            )
            selected_reasoning_effort = self._validate_reasoning_effort(
                selected_provider, post_data.get("reasoning_effort")
            )

            chat_obj = data["chat_obj"]
            current_filters = data["current_filters"]
            is_filtering = data["is_filtering"]
            reset_requested = "reset_conversation" in post_data
            user_prompt = (post_data.get("prompt") or "").strip()

            if not chat_obj:
                title = (
                    user_prompt[:40] + "..."
                    if len(user_prompt) > 40
                    else user_prompt
                )
                if not title:
                    title = "New Chat"
                chat_obj = LLMChat.objects.create(
                    user=user,
                    title=title,
                    model=f"{selected_provider}:{selected_model}",
                    filters={
                        **current_filters,
                        "reasoning_effort": selected_reasoning_effort,
                    },
                )
            elif is_filtering:
                chat_obj.filters = {
                    **current_filters,
                    "reasoning_effort": selected_reasoning_effort,
                }
                chat_obj.save()

            history = [
                {
                    "role": m.role,
                    "content": m.content,
                    "sources": m.metadata.get("sources", []),
                    "model": m.metadata.get("model", ""),
                    "usage": m.metadata.get("usage", {}),
                    "auth_source": m.metadata.get("auth_source", ""),
                }
                for m in chat_obj.messages.all()
            ]

            chat_url = reverse("insights_detail", kwargs={"chat_id": chat_obj.id})
            stream_url = reverse(
                "insights_detail_stream", kwargs={"chat_id": chat_obj.id}
            )
            stream_context = {
                "api_keys": data["api_keys"],
                "chat_id": chat_obj.id,
                "chat_url": chat_url,
                "current_filters": current_filters,
                "history": history,
                "model": selected_model,
                "provider": selected_provider,
                "reasoning_effort": selected_reasoning_effort,
                "reset_requested": reset_requested,
                "sessions": data["sessions"],
                "sessions_updated": data["sessions_updated"],
                "stream_url": stream_url,
                "user_prompt": user_prompt,
                "username": data["username"],
            }

            if data["sessions_updated"]:
                request.session["sessions_updated"] = False
                request.session.save()
        except Exception as exc:
            return StreamingHttpResponse(
                iter([stream_event("error", {"message": str(exc)})]),
                content_type="text/event-stream",
                status=500,
            )

        event_queue = queue.Queue()
        stream_done = object()

        async def stream_worker():
            handler = None
            streamed_chunks = []
            messages_persisted = False
            try:
                event_queue.put(stream_event(
                    "chat",
                    {
                        "chat_id": str(stream_context["chat_id"]),
                        "chat_url": stream_context["chat_url"],
                        "stream_url": stream_context["stream_url"],
                    },
                ))

                if stream_context["reset_requested"] or not stream_context["user_prompt"]:
                    event_queue.put(stream_event(
                        "done",
                        {
                            "chat_id": str(stream_context["chat_id"]),
                            "chat_url": stream_context["chat_url"],
                            "stream_url": stream_context["stream_url"],
                            "content": "",
                            "sources": [],
                            "usage": {"prompt": 0, "response": 0},
                        },
                    ))
                    return

                handler = get_llm_handler(
                    model=stream_context["model"],
                    api_keys=stream_context["api_keys"],
                    reasoning_effort=stream_context["reasoning_effort"],
                )
                history = stream_context["history"]
                handler.set_conversation_history(history)

                async for chunk in perform_llm_analysis_stream(
                    llm_handler=handler,
                    sessions=stream_context["sessions"],
                    user_prompt=stream_context["user_prompt"],
                    username=stream_context["username"],
                    conversation_history=history,
                    sessions_updated=stream_context["sessions_updated"],
                    chat_obj=stream_context["chat_id"],
                ):
                    if chunk:
                        streamed_chunks.append(chunk)
                        event_queue.put(stream_event("delta", {"content": chunk}))
                messages_persisted = True

                conversation_history = handler.get_conversation_history()
                latest_assistant = next(
                    (
                        msg
                        for msg in reversed(conversation_history)
                        if msg.get("role") == "assistant"
                    ),
                    {},
                )

                def finalize_stream_session():
                    chat_to_save = LLMChat.objects.get(id=stream_context["chat_id"])
                    chat_to_save.model = (
                        f"{stream_context['provider']}:{stream_context['model']}"
                    )
                    chat_to_save.filters = {
                        **(chat_to_save.filters or {}),
                        "reasoning_effort": stream_context["reasoning_effort"],
                    }
                    chat_to_save.save()

                await database_sync_to_async(finalize_stream_session)()

                event_queue.put(stream_event(
                    "done",
                    {
                        "chat_id": str(stream_context["chat_id"]),
                        "chat_url": stream_context["chat_url"],
                        "stream_url": stream_context["stream_url"],
                        "content": latest_assistant.get("content", ""),
                        "html": render_markdown(latest_assistant.get("content", "")),
                        "sources": latest_assistant.get("sources", []),
                        "usage": latest_assistant.get("usage", {}),
                        "model": latest_assistant.get("model", stream_context["model"]),
                    },
                ))
            except Exception as exc:
                error_message = str(exc)
                partial_content = "".join(streamed_chunks).strip()
                if partial_content:
                    assistant_content = (
                        f"{partial_content}\n\nStream error: {error_message}"
                    )
                else:
                    assistant_content = f"Stream error: {error_message}"

                if not messages_persisted and stream_context["user_prompt"]:
                    try:
                        await save_partial_stream_messages(
                            stream_context["chat_id"],
                            stream_context["history"],
                            handler,
                            stream_context["user_prompt"],
                            assistant_content,
                            stream_context["model"],
                            error_message,
                        )
                    except Exception as save_exc:
                        assistant_content = (
                            f"{assistant_content}\n\n"
                            f"Could not save partial chat history: {save_exc}"
                        )

                event_queue.put(stream_event(
                    "done",
                    {
                        "chat_id": str(stream_context["chat_id"]),
                        "chat_url": stream_context["chat_url"],
                        "stream_url": stream_context["stream_url"],
                        "content": assistant_content,
                        "html": render_markdown(assistant_content),
                        "sources": [],
                        "usage": {"prompt": 0, "response": 0},
                        "model": stream_context["model"],
                        "error": error_message,
                    },
                ))
            finally:
                close_old_connections()
                event_queue.put(stream_done)

        def run_stream_worker():
            try:
                asyncio.run(stream_worker())
            except Exception as exc:
                event_queue.put(stream_event("error", {"message": str(exc)}))
                event_queue.put(stream_done)

        def event_stream():
            worker = threading.Thread(target=run_stream_worker, daemon=True)
            worker.start()
            yield from stream_queue_events(event_queue, stream_done)

        response = StreamingHttpResponse(
            event_stream(), content_type="text/event-stream"
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        response["Connection"] = "keep-alive"
        return response

    async def post(self, request, chat_id=None):
        user = await request.auser()
        if not user.is_authenticated:
            from django.conf import settings
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        if not await sync_to_async(user_has_ai_features)(user):
            return await sync_to_async(ai_features_disabled_response)(request)

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
                    "exclude_projects",
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
        selected_reasoning_effort = self._validate_reasoning_effort(
            selected_provider, request.POST.get("reasoning_effort")
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
                filters={
                    **current_filters,
                    "reasoning_effort": selected_reasoning_effort,
                },
            )
            chat_id = chat_obj.id
        elif is_filtering:
            # Explicit filter update -> update pinned filters
            chat_obj.filters = {
                **current_filters,
                "reasoning_effort": selected_reasoning_effort,
            }
            await sync_to_async(chat_obj.save)()

        handler = get_llm_handler(
            model=selected_model,
            api_keys=data["api_keys"],
            reasoning_effort=selected_reasoning_effort,
        )

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
                chat_obj.filters = {
                    **(chat_obj.filters or {}),
                    "reasoning_effort": selected_reasoning_effort,
                }
                chat_obj.save()

            await sync_to_async(finalize_post_session)()

        return redirect(reverse("insights_detail", kwargs={"chat_id": chat_id}))


def stream_insights(request, chat_id=None):
    return InsightsView().stream(request, chat_id=chat_id)
