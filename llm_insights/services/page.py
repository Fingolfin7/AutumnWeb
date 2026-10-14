import json

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.db.models import Max, Min
from django.shortcuts import get_object_or_404

from core.forms import SearchProjectForm
from core.models import Sessions
from core.search import is_truthy
from core.services.semantic_search import RelatedOutcome, semantic_search_available
from core.utils import (
    build_exclude_project_meta,
    filter_by_active_context,
    filter_sessions_by_params,
    summarise_search_filters,
)
from llm_insights.llm_handlers import get_llm_handler
from llm_insights.models import LLMChat
from llm_insights.services.analysis import perform_llm_analysis
from llm_insights.services.chats import (
    fallback_chat_title,
    generate_and_save_chat_title,
    group_chats_by_recency,
    load_chat_history,
)
from llm_insights.services.context import (
    FILTER_KEYS,
    apply_default_date_filters,
    build_post_context,
    extract_filter_params,
)
from llm_insights.services.handlers import (
    get_chat_title_handler,
    openai_connection_source,
    openai_reasoning_efforts,
    provider_models,
    validate_reasoning_effort,
    validate_selection,
)


CHAT_LIST_PAGE_SIZE = 20


def build_insights_page_data(request, user, chat_id=None):
    chat_obj = None
    history = []
    current_filters = extract_filter_params(request)
    filter_keys = [*FILTER_KEYS, "filter"]
    has_explicit_filters = any(key in request.GET for key in filter_keys)
    using_stored_filters = False

    if chat_id:
        chat_obj = get_object_or_404(LLMChat, id=chat_id, user=user)
        history = load_chat_history(chat_obj, include_metadata=True)
        if not has_explicit_filters and chat_obj.filters:
            current_filters = chat_obj.filters
            using_stored_filters = True
    elif not has_explicit_filters:
        apply_default_date_filters(current_filters, user)

    try:
        requested_chat_limit = int(request.GET.get("chat_limit", CHAT_LIST_PAGE_SIZE))
    except (TypeError, ValueError):
        requested_chat_limit = CHAT_LIST_PAGE_SIZE
    requested_chat_limit = max(requested_chat_limit, CHAT_LIST_PAGE_SIZE)
    chat_queryset = LLMChat.objects.filter(user=user).only("id", "title", "updated_at")
    total_chat_count = chat_queryset.count()
    visible_chat_count = min(requested_chat_limit, total_chat_count)
    recent_chats = list(chat_queryset[:visible_chat_count])

    queryset = (
        Sessions.objects.filter(end_time__isnull=False, user=user)
        .select_related("project", "project__context")
        .prefetch_related("subprojects", "project__tags")
    )
    context_id = current_filters.get("context") or request.GET.get("context")
    queryset = filter_by_active_context(
        queryset, request, override_context_id=context_id
    )
    related = RelatedOutcome()
    queryset = filter_sessions_by_params(
        request,
        queryset,
        params_override=current_filters,
        user=user,
        outcome=related,
    )
    session_count = queryset.count()
    aggregate = queryset.aggregate(first=Min("start_time"), last=Max("end_time"))
    sessions = list(queryset)
    models = provider_models(user)
    semantic = semantic_search_available(user)
    search_form = SearchProjectForm(
        initial={
            "search": current_filters.get("search"),
            "related": is_truthy(current_filters.get("related")),
            "project_name": current_filters.get("project_name"),
            "start_date": current_filters.get("start_date"),
            "end_date": current_filters.get("end_date"),
            "note_snippet": current_filters.get("note_snippet"),
            "context": current_filters.get("context") or "",
            "tags": current_filters.get("tags", []),
            "include_projects": current_filters.get("include_projects", []),
            "exclude_projects": current_filters.get("exclude_projects", []),
        },
        user=user,
    )
    sessions_updated = "filter" in request.GET
    if sessions_updated:
        request.session["sessions_updated"] = True
        messages.success(request, "Session selection updated.")

    usage_stats = {"prompt": 0, "response": 0, "cached": 0, "total": 0}
    for item in history:
        usage = (item.get("metadata") or {}).get("usage") or {}
        usage_stats["prompt"] += usage.get("prompt", 0) or 0
        usage_stats["response"] += usage.get("response", 0) or 0
        usage_stats["cached"] += usage.get("cached", 0) or 0
    usage_stats["total"] = usage_stats["prompt"] + usage_stats["response"]

    return {
        "sessions": sessions,
        "session_count": session_count,
        "earliest_date": aggregate["first"],
        "latest_date": aggregate["last"],
        "provider_models": models,
        "search_form": search_form,
        "sessions_updated": sessions_updated,
        "username": user.username,
        "chat_obj": chat_obj,
        "conversation_history": history,
        "recent_chats": recent_chats,
        "recent_chat_groups": group_chats_by_recency(recent_chats),
        "chat_list_limit": requested_chat_limit,
        "has_older_chats": total_chat_count > visible_chat_count,
        "next_chat_list_limit": requested_chat_limit + CHAT_LIST_PAGE_SIZE,
        "usage_stats": usage_stats,
        "openai_connection_source": openai_connection_source(user),
        "exclude_project_meta_json": json.dumps(build_exclude_project_meta(user)),
        "active_filters": summarise_search_filters(
            request,
            user,
            related=semantic,
            related_unavailable=related.unavailable,
        ),
        "semantic_search_available": semantic,
    }


def build_template_context(request, data, chat_id=None):
    models = data["provider_models"]
    chat_obj = data["chat_obj"]
    initial_provider = chat_obj.model.split(":")[0] if chat_obj else None
    initial_model = (
        chat_obj.model.split(":")[1]
        if chat_obj and ":" in chat_obj.model
        else (chat_obj.model if chat_obj else None)
    )
    selected_provider, selected_model = validate_selection(
        models,
        request.GET.get("provider") or initial_provider,
        request.GET.get("model") or initial_model,
    )
    stored_effort = (
        chat_obj.filters.get("reasoning_effort")
        if chat_obj and chat_obj.filters
        else None
    )
    selected_effort = validate_reasoning_effort(
        selected_provider,
        request.GET.get("reasoning_effort") or stored_effort,
        selected_model,
    )
    config = {
        "providerModels": {
            provider: [{"value": value, "label": label} for value, label in items]
            for provider, items in models.items()
        },
        "username": data["username"],
        "selectedProvider": selected_provider,
        "selectedModel": selected_model,
        "openaiReasoningEffortsByModel": {
            model: openai_reasoning_efforts(model)
            for model, _label in models.get("openai", [])
        },
    }
    return {
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
        "selected_reasoning_effort": selected_effort,
        "openai_reasoning_efforts": openai_reasoning_efforts(selected_model),
        "insights_config": config,
        "providers": list(models.keys()),
        "chat_id": chat_id,
        "recent_chats": data["recent_chats"],
        "recent_chat_groups": data["recent_chat_groups"],
        "chat_list_limit": data["chat_list_limit"],
        "has_older_chats": data["has_older_chats"],
        "next_chat_list_limit": data["next_chat_list_limit"],
        "usage_stats": data["usage_stats"],
        "username": data["username"],
        "openai_connection_source": data["openai_connection_source"],
        "exclude_project_meta_json": data["exclude_project_meta_json"],
        "active_filters": data["active_filters"],
        "semantic_search_available": data["semantic_search_available"],
    }


async def submit_insights_form(request, user, chat_id=None):
    data = await sync_to_async(build_post_context)(request, user, chat_id)
    selected_provider, selected_model = validate_selection(
        data["provider_models"],
        request.POST.get("provider"),
        request.POST.get("model"),
    )
    selected_effort = validate_reasoning_effort(
        selected_provider,
        request.POST.get("reasoning_effort"),
        selected_model,
    )
    chat_obj = data["chat_obj"]
    if not chat_obj:
        user_prompt = request.POST.get("prompt", "")
        chat_obj = await sync_to_async(LLMChat.objects.create)(
            user=user,
            title=fallback_chat_title(user_prompt),
            model=f"{selected_provider}:{selected_model}",
            filters={**data["current_filters"], "reasoning_effort": selected_effort},
        )
        chat_id = chat_obj.id
    elif data["is_filtering"]:
        chat_obj.filters = {
            **data["current_filters"],
            "reasoning_effort": selected_effort,
        }
        await sync_to_async(chat_obj.save)()

    handler = get_llm_handler(
        model=selected_model,
        api_keys=data["api_keys"],
        reasoning_effort=selected_effort,
    )
    history = await sync_to_async(load_chat_history)(chat_obj)
    handler.set_conversation_history(history)
    if "reset_conversation" in request.POST:
        return None

    _insights, conversation_history = await perform_llm_analysis(
        llm_handler=handler,
        sessions=data["sessions"],
        user_prompt=request.POST.get("prompt", ""),
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
            "reasoning_effort": selected_effort,
        }
        chat_obj.save()

    await sync_to_async(finalize_post_session)()
    await generate_and_save_chat_title(
        chat_obj,
        get_chat_title_handler(handler, data["api_keys"]),
        conversation_history,
        fallback_title=chat_obj.title,
    )
    return chat_id
