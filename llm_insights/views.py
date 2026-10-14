from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import View

from llm_insights.models import LLMChat
from llm_insights.services.analysis import (
    perform_llm_analysis,
    perform_llm_analysis_stream,
)
from llm_insights.services.chats import (
    clean_generated_chat_title,
    fallback_chat_title,
    generate_and_save_chat_title,
    group_chats_by_recency,
    save_llm_messages,
    save_partial_stream_messages,
)
from llm_insights.services.context import (
    apply_default_date_filters,
    build_post_context,
    extract_filter_params,
)
from llm_insights.services.handlers import (
    OPENAI_REASONING_EFFORTS,
    build_api_keys,
    openai_connection_source,
    openai_reasoning_efforts,
    provider_models,
    validate_reasoning_effort,
    validate_selection,
)
from llm_insights.services.page import (
    build_insights_page_data,
    build_template_context,
    submit_insights_form,
)
from llm_insights.services.streaming import (
    configure_sse_response,
    stream_insights_response,
    stream_keepalive,
    stream_queue_events,
)


def user_has_insights_access(user):
    profile = getattr(user, "profile", None)
    return bool(profile and profile.insights_access_enabled)


def insights_access_disabled_response(request):
    profile = getattr(request.user, "profile", None)
    if profile and not profile.ai_features_enabled:
        messages.error(request, "AI features are disabled for this account.")
    else:
        messages.error(
            request,
            "Add an AI provider API key or connect Codex in your Profile first.",
        )
    return redirect("home")


@login_required
@require_POST
def delete_chat(request, chat_id):
    if not user_has_insights_access(request.user):
        return insights_access_disabled_response(request)
    chat = get_object_or_404(LLMChat, id=chat_id, user=request.user)
    chat.delete()
    messages.success(request, "Chat deleted.")
    return redirect("insights")


class InsightsView(View):
    """HTTP adapter for the Insights page; application logic lives in services."""

    OPENAI_REASONING_EFFORTS = OPENAI_REASONING_EFFORTS

    def _provider_models(self, user):
        return provider_models(user)

    def _openai_connection_source(self, user):
        return openai_connection_source(user)

    def _build_api_keys(self, user):
        return build_api_keys(user)

    def _validate_selection(self, models, provider, model):
        return validate_selection(models, provider, model)

    def _openai_reasoning_efforts(self, model):
        return openai_reasoning_efforts(model)

    def _validate_reasoning_effort(self, provider, effort, model=None):
        return validate_reasoning_effort(provider, effort, model)

    def _extract_filter_params(self, request):
        return extract_filter_params(request)

    def _apply_default_date_filters(self, current_filters, user):
        return apply_default_date_filters(current_filters, user)

    def _get_initial_post_data(self, request, user, chat_id=None):
        return build_post_context(request, user, chat_id)

    async def get(self, request, chat_id=None):
        user = await request.auser()
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        if not await sync_to_async(user_has_insights_access)(user):
            return await sync_to_async(insights_access_disabled_response)(request)

        data = await sync_to_async(build_insights_page_data)(request, user, chat_id)
        context = build_template_context(request, data, chat_id)
        return await sync_to_async(render)(
            request, "llm_insights/insights.html", context
        )

    def stream(self, request, chat_id=None):
        return stream_insights_response(request, chat_id, user_has_insights_access)

    async def post(self, request, chat_id=None):
        user = await request.auser()
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        if not await sync_to_async(user_has_insights_access)(user):
            return await sync_to_async(insights_access_disabled_response)(request)

        result_chat_id = await submit_insights_form(request, user, chat_id)
        if result_chat_id is None:
            return redirect("insights")
        return redirect(reverse("insights_detail", kwargs={"chat_id": result_chat_id}))


def stream_insights(request, chat_id=None):
    return InsightsView().stream(request, chat_id=chat_id)
