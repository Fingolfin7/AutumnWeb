import asyncio
import json
import queue
import threading

from django.db import close_old_connections
from django.http import StreamingHttpResponse
from django.urls import reverse

from core.templatetags.markdown_render import markdown as render_markdown
from llm_insights.llm_handlers import get_llm_handler
from llm_insights.models import LLMChat
from llm_insights.services.analysis import perform_llm_analysis_stream
from llm_insights.services.chats import (
    database_sync_to_async,
    fallback_chat_title,
    generate_and_save_chat_title,
    load_chat_history,
    save_partial_stream_messages,
)
from llm_insights.services.context import build_post_context
from llm_insights.services.handlers import (
    get_chat_title_handler,
    validate_reasoning_effort,
    validate_selection,
)


SSE_HEARTBEAT_SECONDS = 15


def stream_event(event_name, payload):
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"


def stream_keepalive():
    return ": keep-alive\n\n"


def configure_sse_response(response):
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


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


def _error_stream(message, status):
    return StreamingHttpResponse(
        iter([stream_event("error", {"message": message})]),
        content_type="text/event-stream",
        status=status,
    )


def _prepare_stream_context(request, user, chat_id):
    post_data = request.POST.copy()
    data = build_post_context(request, user, chat_id)
    selected_provider, selected_model = validate_selection(
        data["provider_models"], post_data.get("provider"), post_data.get("model")
    )
    selected_reasoning_effort = validate_reasoning_effort(
        selected_provider, post_data.get("reasoning_effort"), selected_model
    )

    chat_obj = data["chat_obj"]
    reset_requested = "reset_conversation" in post_data
    user_prompt = (post_data.get("prompt") or "").strip()
    if not chat_obj:
        chat_obj = LLMChat.objects.create(
            user=user,
            title=fallback_chat_title(user_prompt),
            model=f"{selected_provider}:{selected_model}",
            filters={
                **data["current_filters"],
                "reasoning_effort": selected_reasoning_effort,
            },
        )
    elif data["is_filtering"]:
        chat_obj.filters = {
            **data["current_filters"],
            "reasoning_effort": selected_reasoning_effort,
        }
        chat_obj.save()

    chat_url = reverse("insights_detail", kwargs={"chat_id": chat_obj.id})
    stream_url = reverse("insights_detail_stream", kwargs={"chat_id": chat_obj.id})
    context = {
        "api_keys": data["api_keys"],
        "chat_id": chat_obj.id,
        "chat_url": chat_url,
        "current_filters": data["current_filters"],
        "history": load_chat_history(chat_obj, include_auth_source=True),
        "model": selected_model,
        "provider": selected_provider,
        "reasoning_effort": selected_reasoning_effort,
        "reset_requested": reset_requested,
        "sessions": data["sessions"],
        "sessions_updated": data["sessions_updated"],
        "stream_url": stream_url,
        "user_prompt": user_prompt,
        "username": data["username"],
        "fallback_title": chat_obj.title,
    }
    if data["sessions_updated"]:
        request.session["sessions_updated"] = False
        request.session.save()
    return context


async def _run_stream_worker(stream_context, event_queue, stream_done):
    handler = None
    streamed_chunks = []
    messages_persisted = False
    try:
        event_queue.put(
            stream_event(
                "chat",
                {
                    "chat_id": str(stream_context["chat_id"]),
                    "chat_url": stream_context["chat_url"],
                    "stream_url": stream_context["stream_url"],
                },
            )
        )
        if stream_context["reset_requested"] or not stream_context["user_prompt"]:
            event_queue.put(
                stream_event(
                    "done",
                    {
                        "chat_id": str(stream_context["chat_id"]),
                        "chat_url": stream_context["chat_url"],
                        "stream_url": stream_context["stream_url"],
                        "content": "",
                        "sources": [],
                        "usage": {"prompt": 0, "response": 0},
                    },
                )
            )
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
                message
                for message in reversed(conversation_history)
                if message.get("role") == "assistant"
            ),
            {},
        )

        def finalize_stream_session():
            chat = LLMChat.objects.get(id=stream_context["chat_id"])
            chat.model = f"{stream_context['provider']}:{stream_context['model']}"
            chat.filters = {
                **(chat.filters or {}),
                "reasoning_effort": stream_context["reasoning_effort"],
            }
            chat.save()

        await database_sync_to_async(finalize_stream_session)()
        chat_title = await generate_and_save_chat_title(
            stream_context["chat_id"],
            get_chat_title_handler(handler, stream_context["api_keys"]),
            conversation_history,
            fallback_title=stream_context["fallback_title"],
        )
        event_queue.put(
            stream_event(
                "done",
                {
                    "chat_id": str(stream_context["chat_id"]),
                    "chat_url": stream_context["chat_url"],
                    "stream_url": stream_context["stream_url"],
                    "chat_title": chat_title,
                    "content": latest_assistant.get("content", ""),
                    "html": render_markdown(latest_assistant.get("content", "")),
                    "sources": latest_assistant.get("sources", []),
                    "usage": latest_assistant.get("usage", {}),
                    "model": latest_assistant.get("model", stream_context["model"]),
                },
            )
        )
    except Exception as exc:
        error_message = str(exc)
        partial_content = "".join(streamed_chunks).strip()
        assistant_content = (
            f"{partial_content}\n\nStream error: {error_message}"
            if partial_content
            else f"Stream error: {error_message}"
        )
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
                    f"{assistant_content}\n\nCould not save partial chat history: {save_exc}"
                )
        event_queue.put(
            stream_event(
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
            )
        )
    finally:
        close_old_connections()
        event_queue.put(stream_done)


def stream_insights_response(request, chat_id, access_check):
    user = request.user
    if not user.is_authenticated:
        return _error_stream("Authentication required.", 401)
    if not access_check(user):
        return _error_stream(
            "Insights requires an AI provider API key or Codex login in your profile.",
            403,
        )
    try:
        stream_context = _prepare_stream_context(request, user, chat_id)
    except Exception as exc:
        return _error_stream(str(exc), 500)

    event_queue = queue.Queue()
    stream_done = object()

    def run_stream_worker():
        try:
            asyncio.run(_run_stream_worker(stream_context, event_queue, stream_done))
        except Exception as exc:
            event_queue.put(stream_event("error", {"message": str(exc)}))
            event_queue.put(stream_done)

    def event_stream():
        worker = threading.Thread(target=run_stream_worker, daemon=True)
        worker.start()
        yield from stream_queue_events(event_queue, stream_done)

    return configure_sse_response(
        StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    )
