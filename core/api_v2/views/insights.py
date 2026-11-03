from django.http import FileResponse, QueryDict
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from core.api_v2.exceptions import V2APIView
from core.api_v2.renderers import EventStreamRenderer
from core.api_v2.serializers import similarity_field
from core.templatetags.markdown_render import markdown as render_markdown
from llm_insights.attachments import (
    ACCEPTED_EXTENSIONS,
    MAX_FILES_PER_MESSAGE,
    AttachmentError,
    create_attachment,
)
from llm_insights.models import LLMAttachment, LLMChat
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


class InsightAttachmentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    kind = serializers.ChoiceField(choices=("image", "pdf", "text"))
    mime = serializers.CharField()
    size = serializers.IntegerField(help_text="Stored size in bytes.")
    url = serializers.CharField(help_text="Where the file itself is served to its owner.")


class InsightAttachmentUploadSerializer(serializers.Serializer):
    file = serializers.FileField(
        help_text=(
            "Up to 10 MB: an image, a PDF, a Word document (.docx) or a text file ("
            + ", ".join(ACCEPTED_EXTENSIONS)
            + ")."
        )
    )


def _attachment_data(attachment):
    return {
        "id": attachment.id,
        "name": attachment.name,
        "kind": attachment.kind,
        "mime": attachment.mime,
        "size": attachment.size,
        "url": reverse(
            "api_v2:insights-attachment-detail", kwargs={"attachment_id": attachment.id}
        ),
    }


class InsightMessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=("system", "user", "assistant"))
    content = serializers.CharField()
    html = serializers.CharField()
    created_at = serializers.DateTimeField()
    metadata = InsightMessageMetadataSerializer()
    attachments = InsightAttachmentSerializer(many=True)


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
    attachment_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        max_length=MAX_FILES_PER_MESSAGE,
        help_text="Files uploaded with POST /api/v2/insights/attachments/ to send with this message.",
    )
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
    for key in ("tags", "include_projects", "exclude_projects", "attachment_ids"):
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
                        "attachments": [
                            _attachment_data(attachment)
                            for attachment in message.attachments.all()
                        ],
                    }
                    for message in chat.messages.prefetch_related("attachments")
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
        attachment_ids = set(data.get("attachment_ids", []))
        if attachment_ids and LLMAttachment.objects.filter(
            user=request.user, id__in=attachment_ids, message__isnull=True
        ).count() != len(attachment_ids):
            raise ValidationError(
                {
                    "attachment_ids": [
                        "An attached file is no longer available. Remove it and attach it again."
                    ]
                }
            )
        post = _as_insights_post(data)
        post["prompt"] = data["message"]
        request._request._post = post
        response = stream_insights_response(
            request._request, chat_id, user_has_insights_access
        )
        request._related_outcome = getattr(request._request, "_related_outcome", None)
        return response


class InsightAttachmentsView(V2APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        operation_id="insights_attachments_create",
        request={"multipart/form-data": InsightAttachmentUploadSerializer},
        responses={201: InsightAttachmentSerializer},
    )
    def post(self, request):
        """Upload a file to send with the next Insights message. Unsent
        uploads are deleted after a day."""
        _require_access(request.user)
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": ["Choose a file to attach."]})
        try:
            attachment = create_attachment(request.user, upload)
        except AttachmentError as exc:
            raise ValidationError({"file": [str(exc)]}) from exc
        return Response(_attachment_data(attachment), status=status.HTTP_201_CREATED)


class InsightAttachmentDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    def _attachment(self, request, attachment_id):
        _require_access(request.user)
        attachment = LLMAttachment.objects.filter(
            user=request.user, pk=attachment_id
        ).first()
        if attachment is None:
            raise NotFound("Attachment not found.")
        return attachment

    @extend_schema(
        operation_id="insights_attachments_retrieve",
        responses={
            (200, "application/octet-stream"): OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="The file. Images are shown inline; other files download.",
            )
        },
    )
    def get(self, request, attachment_id):
        attachment = self._attachment(request, attachment_id)
        try:
            handle = attachment.file.open("rb")
        except Exception as exc:
            raise NotFound("This file is no longer available.") from exc
        response = FileResponse(
            handle,
            content_type=attachment.mime,
            as_attachment=attachment.kind != LLMAttachment.KIND_IMAGE,
            filename=attachment.name,
        )
        # A file never changes under its id.
        response["Cache-Control"] = "private, max-age=31536000, immutable"
        return response

    @extend_schema(
        operation_id="insights_attachments_destroy",
        request=None,
        responses={204: OpenApiResponse(description="Attachment removed.")},
    )
    def delete(self, request, attachment_id):
        """Remove a file that has not been sent yet. Sent files stay with
        their message and go when the chat is deleted."""
        attachment = self._attachment(request, attachment_id)
        if attachment.message_id is not None:
            raise ValidationError(
                {"detail": "This file was sent with a message. Delete the chat to remove it."}
            )
        attachment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
