from django.http import QueryDict
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from core.api_v2.exceptions import V2APIView
from core.api_v2.renderers import EventStreamRenderer
from core.api_v2.serializers import similarity_field
from core.templatetags.markdown_render import markdown as render_markdown
from llm_insights.models import LLMChat
from llm_insights.services.chats import group_chats_by_recency
from llm_insights.services.handlers import (
    openai_connection_source,
    openai_reasoning_efforts,
    provider_models,
)
from llm_insights.services.context import build_post_context
from llm_insights.services.streaming import stream_insights_response
from llm_insights.views import user_has_insights_access


def _require_access(user):
    if not user_has_insights_access(user):
        raise PermissionDenied(
            "Insights requires an AI provider API key or Codex login in your profile."
        )


class InsightChatSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    updated_at = serializers.DateTimeField()


class InsightChatGroupSerializer(serializers.Serializer):
    label = serializers.CharField()
    chats = InsightChatSummarySerializer(many=True)


class InsightChatListSerializer(serializers.Serializer):
    groups = InsightChatGroupSerializer(many=True)
    total = serializers.IntegerField(required=False)
    limit = serializers.IntegerField(required=False)
    offset = serializers.IntegerField(required=False)


class InsightChatListQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100)
    offset = serializers.IntegerField(required=False, min_value=0, default=0)


class InsightSourceSerializer(serializers.Serializer):
    link = serializers.URLField()
    title = serializers.CharField()


class InsightUsageSerializer(serializers.Serializer):
    prompt = serializers.IntegerField(required=False)
    response = serializers.IntegerField(required=False)
    cached = serializers.IntegerField(required=False)
    total = serializers.IntegerField(required=False)


class InsightMessageMetadataSerializer(serializers.Serializer):
    sources = InsightSourceSerializer(many=True, required=False)
    model = serializers.CharField(required=False, allow_blank=True)
    usage = InsightUsageSerializer(required=False)
    auth_source = serializers.CharField(required=False, allow_blank=True)
    error = serializers.BooleanField(required=False)
    error_message = serializers.CharField(required=False, allow_blank=True)
    refusal = serializers.BooleanField(required=False)


class InsightMessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=("system", "user", "assistant"))
    content = serializers.CharField()
    html = serializers.CharField()
    created_at = serializers.DateTimeField()
    metadata = InsightMessageMetadataSerializer()


@extend_schema_field(
    {
        "oneOf": [
            {"type": "integer", "minimum": 1},
            {"type": "string", "enum": ["all"]},
        ],
        "nullable": True,
        "description": "A context ID, or 'all' for all contexts.",
    }
)
class InsightContextField(serializers.Field):
    def to_internal_value(self, data):
        if data is None or str(data).strip().lower() == "all":
            return "all"
        try:
            value = int(data)
        except (TypeError, ValueError) as exc:
            raise serializers.ValidationError("Enter a positive context ID or 'all'.") from exc
        if value < 1:
            raise serializers.ValidationError("Enter a positive context ID or 'all'.")
        return value

    def to_representation(self, value):
        return value


class InsightFiltersSerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True)
    related = serializers.CharField(required=False, allow_blank=True)
    similarity = similarity_field()
    project_name = serializers.CharField(required=False, allow_blank=True)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    note_snippet = serializers.CharField(required=False, allow_blank=True)
    context = InsightContextField(required=False, allow_null=True)
    tags = serializers.ListField(child=serializers.IntegerField(), required=False)
    include_projects = serializers.ListField(child=serializers.IntegerField(), required=False)
    exclude_projects = serializers.ListField(child=serializers.IntegerField(), required=False)
    reasoning_effort = serializers.CharField(required=False, allow_blank=True)


class InsightChatDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    model = serializers.CharField()
    filters = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    messages = InsightMessageSerializer(many=True)

    @extend_schema_field(InsightFiltersSerializer)
    def get_filters(self, chat):
        return chat.get("filters", {}) if isinstance(chat, dict) else chat.filters


class InsightModelOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()
    reasoning_efforts = serializers.ListField(child=serializers.CharField())


class InsightProviderOptionSerializer(serializers.Serializer):
    provider = serializers.CharField()
    models = InsightModelOptionSerializer(many=True)


class InsightOptionsSerializer(serializers.Serializer):
    providers = InsightProviderOptionSerializer(many=True)
    default_start_date = serializers.DateField()
    default_end_date = serializers.DateField()
    openai_source = serializers.ChoiceField(
        choices=("server", "codex", "profile", "codex_with_api_fallback"),
        allow_null=True,
    )


class InsightStreamRequestSerializer(serializers.Serializer):
    chat_id = serializers.UUIDField(required=False)
    message = serializers.CharField(allow_blank=False)
    provider = serializers.CharField(required=False)
    model = serializers.CharField(required=False)
    reasoning_effort = serializers.CharField(required=False, allow_blank=True)
    search = serializers.CharField(required=False, allow_blank=True)
    related = serializers.BooleanField(required=False)
    similarity = similarity_field()
    project_name = serializers.CharField(required=False, allow_blank=True)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    note_snippet = serializers.CharField(required=False, allow_blank=True)
    context = InsightContextField(required=False, allow_null=True)
    tags = serializers.ListField(child=serializers.IntegerField(), required=False)
    include_projects = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )
    exclude_projects = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )


class InsightSelectionQuerySerializer(serializers.Serializer):
    chat_id = serializers.UUIDField(required=False)
    search = serializers.CharField(required=False, allow_blank=True)
    related = serializers.BooleanField(required=False)
    similarity = similarity_field()
    project_name = serializers.CharField(required=False, allow_blank=True)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    note_snippet = serializers.CharField(required=False, allow_blank=True)
    context = InsightContextField(required=False, allow_null=True)
    tags = serializers.ListField(child=serializers.IntegerField(), required=False)
    include_projects = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )
    exclude_projects = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )


class InsightSelectionSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    first_date = serializers.DateField(allow_null=True)
    last_date = serializers.DateField(allow_null=True)
    related = serializers.ChoiceField(
        choices=("included", "unavailable"), allow_null=True
    )


FILTER_FIELDS = (
    "search",
    "related",
    "similarity",
    "project_name",
    "start_date",
    "end_date",
    "note_snippet",
    "context",
    "tags",
    "include_projects",
    "exclude_projects",
)


def _as_insights_post(data):
    post = QueryDict(mutable=True)
    for key in (
        "provider",
        "model",
        "reasoning_effort",
        "search",
        "similarity",
        "project_name",
        "start_date",
        "end_date",
        "note_snippet",
        "context",
    ):
        if key in data:
            value = data[key]
            if key == "context" and value is None:
                value = "all"
            post[key] = value.isoformat() if hasattr(value, "isoformat") else str(value)
    if data.get("related"):
        post["related"] = "on"
    for key in ("tags", "include_projects", "exclude_projects"):
        if key in data:
            post.setlist(key, [str(value) for value in data[key]])
    if any(key in data for key in FILTER_FIELDS):
        post["filter"] = "1"
    return post


class InsightChatsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="insights_chats_list",
        parameters=[InsightChatListQuerySerializer],
        responses=InsightChatListSerializer,
    )
    def get(self, request):
        _require_access(request.user)
        query = InsightChatListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        options = query.validated_data
        queryset = LLMChat.objects.filter(user=request.user).only(
            "id", "title", "updated_at"
        )
        payload = {}
        if "limit" in options or "offset" in request.query_params:
            total = queryset.count()
            offset = options["offset"]
            limit = options.get("limit", 100)
            chats = list(queryset[offset : offset + limit])
            payload.update(total=total, limit=limit, offset=offset)
        else:
            chats = list(queryset)
        payload["groups"] = [
            {
                "label": label,
                "chats": InsightChatSummarySerializer(items, many=True).data,
            }
            for label, items in group_chats_by_recency(chats)
        ]
        return Response(payload)


class InsightChatDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    def _chat(self, request, chat_id):
        from rest_framework.exceptions import NotFound

        chat = LLMChat.objects.filter(user=request.user, pk=chat_id).first()
        if chat is None:
            raise NotFound("Chat not found.")
        return chat

    @extend_schema(operation_id="insights_chats_retrieve", responses=InsightChatDetailSerializer)
    def get(self, request, chat_id):
        _require_access(request.user)
        chat = self._chat(request, chat_id)
        return Response(
            {
                "id": chat.id,
                "title": chat.title,
                "model": chat.model,
                "filters": chat.filters,
                "created_at": chat.created_at,
                "updated_at": chat.updated_at,
                "messages": [
                    {
                        "role": message.role,
                        "content": message.content,
                        "html": render_markdown(message.content),
                        "created_at": message.created_at,
                        "metadata": message.metadata,
                    }
                    for message in chat.messages.all()
                ],
            }
        )

    @extend_schema(
        operation_id="insights_chats_destroy",
        request=None,
        responses={204: OpenApiResponse(description="Chat deleted.")},
    )
    def delete(self, request, chat_id):
        _require_access(request.user)
        self._chat(request, chat_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class InsightOptionsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="insights_options_retrieve", responses=InsightOptionsSerializer)
    def get(self, request):
        _require_access(request.user)
        options = []
        for provider, models in provider_models(request.user).items():
            options.append(
                {
                    "provider": provider,
                    "models": [
                        {
                            "value": value,
                            "label": label,
                            "reasoning_efforts": (
                                openai_reasoning_efforts(value)
                                if provider == "openai"
                                else []
                            ),
                        }
                        for value, label in models
                    ],
                }
            )
        start, end = request.user.profile.insights_default_filter_date_range()
        return Response(
            {
                "providers": options,
                "default_start_date": start,
                "default_end_date": end,
                "openai_source": openai_connection_source(request.user) or None,
            }
        )


class InsightSelectionView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="insights_selection_retrieve",
        parameters=[InsightSelectionQuerySerializer],
        responses=InsightSelectionSerializer,
    )
    def get(self, request):
        _require_access(request.user)
        serializer = InsightSelectionQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        chat_id = data.pop("chat_id", None)
        request._request._post = _as_insights_post(data)
        selection = build_post_context(request._request, request.user, chat_id)
        sessions = selection["sessions"]
        first_time = min((session.start_time for session in sessions), default=None)
        last_time = max((session.end_time for session in sessions), default=None)
        first = timezone.localdate(first_time) if first_time else None
        last = timezone.localdate(last_time) if last_time else None
        related_outcome = selection["related_outcome"]
        request._related_outcome = related_outcome
        related = None
        if related_outcome.requested:
            related = "unavailable" if related_outcome.unavailable else "included"
        return Response(
            {
                "count": len(sessions),
                "first_date": first,
                "last_date": last,
                "related": related,
            }
        )


class InsightStreamView(V2APIView):
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer, EventStreamRenderer]

    @extend_schema(
        operation_id="insights_stream_create",
        request=InsightStreamRequestSerializer,
        responses={
            (200, "text/event-stream"): OpenApiResponse(
                response=OpenApiTypes.STR,
                description=(
                    "Server-sent events. Emits chat (chat identifiers/URLs), delta "
                    "(content fragment), done (final content, rendered HTML, sources, "
                    "usage and model), error, plus keep-alive comment lines."
                ),
            )
        },
    )
    def post(self, request):
        _require_access(request.user)
        serializer = InsightStreamRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        chat_id = data.get("chat_id")
        if chat_id and not LLMChat.objects.filter(
            user=request.user, pk=chat_id
        ).exists():
            raise NotFound("Chat not found.")
        post = _as_insights_post(data)
        post["prompt"] = data["message"]
        request._request._post = post
        response = stream_insights_response(
            request._request, chat_id, user_has_insights_access
        )
        request._related_outcome = getattr(request._request, "_related_outcome", None)
        return response
