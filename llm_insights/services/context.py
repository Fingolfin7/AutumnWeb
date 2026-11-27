from core.models import Sessions
from core.utils import filter_sessions_by_params, get_active_context
from django.shortcuts import get_object_or_404

from llm_insights.models import LLMChat
from llm_insights.services.handlers import build_api_keys, provider_models
from core.services.semantic_search import RelatedOutcome


FILTER_KEYS = [
    "search",
    "similarity",
    "project_name",
    "start_date",
    "end_date",
    "note_snippet",
    "context",
    "tags",
    "include_projects",
    "exclude_projects",
]


def extract_filter_params(request):
    params = {}
    for key in (
        "search",
        "related",
        "similarity",
        "project_name",
        "start_date",
        "end_date",
        "note_snippet",
        "context",
    ):
        value = request.GET.get(key) or request.POST.get(key)
        if value:
            params[key] = value

    tags = request.GET.getlist("tags") or request.POST.getlist("tags")
    if tags:
        params["tags"] = tags
    for key in ("include_projects", "exclude_projects"):
        projects = request.GET.getlist(key) or request.POST.getlist(key)
        if projects:
            params[key] = projects
    return params


def apply_default_date_filters(current_filters, user):
    start_date, end_date = user.profile.insights_default_filter_date_range()
    current_filters["start_date"] = start_date.isoformat()
    current_filters["end_date"] = end_date.isoformat()


def filter_insights_sessions(request, user, current_filters, *, outcome=None):
    """Apply the one session-selection pipeline used by Insights streaming."""
    queryset = (
        Sessions.objects.filter(end_time__isnull=False, user=user)
        .select_related("project", "project__context")
        .prefetch_related("subprojects", "project__tags")
        .order_by("-end_time", "-pk")
    )
    context_filter = (current_filters["context"] or "all") if "context" in current_filters else None
    try:
        context_id = int(context_filter)
    except (TypeError, ValueError):
        context_id = None
    if context_id is not None:
        # Numeric filters are saved IDs. A deleted ID cannot match a name.
        queryset = queryset.filter(project__context_id=context_id, project__context__user=user)
    else:
        context, _ = get_active_context(request, override_context_id=context_filter)
        if context is not None:
            queryset = queryset.filter(project__context=context)
        elif context_filter and str(context_filter).lower() != "all":
            return queryset.none()
    return filter_sessions_by_params(
        request,
        queryset,
        params_override=current_filters,
        user=user,
        outcome=outcome,
    )


def build_post_context(request, user, chat_id=None):
    chat_obj = None
    if chat_id:
        chat_obj = get_object_or_404(LLMChat, id=chat_id, user=user)

    current_filters = extract_filter_params(request)
    is_filtering = "filter" in request.POST
    if not is_filtering and chat_obj:
        current_filters = dict(chat_obj.filters or {})
    elif not chat_obj and not any(current_filters.get(key) for key in FILTER_KEYS):
        apply_default_date_filters(current_filters, user)

    needs_context_confirmation = bool(chat_obj and not is_filtering and "context" not in current_filters)
    if "context" not in current_filters and not needs_context_confirmation:
        context, _ = get_active_context(request)
        current_filters["context"] = str(context.pk) if context else "all"

    related_outcome = RelatedOutcome()
    request._related_outcome = related_outcome
    sessions = [] if needs_context_confirmation else list(
        filter_insights_sessions(request, user, current_filters, outcome=related_outcome)
    )

    sessions_updated = request.session.get("sessions_updated", False)
    if is_filtering:
        sessions_updated = True

    return {
        "sessions": sessions,
        "needs_context_confirmation": needs_context_confirmation,
        "sessions_updated": sessions_updated,
        "provider_models": provider_models(user),
        "api_keys": build_api_keys(user),
        "username": user.username,
        "chat_obj": chat_obj,
        "current_filters": current_filters,
        "is_filtering": is_filtering,
        "related_outcome": related_outcome,
    }
