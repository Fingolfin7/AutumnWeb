from .base import *
def _named_count_payload(target):
    payload = {
        "id": target.id,
        "name": target.name,
        "project_count": target.project_count,
        "session_count": target.session_count,
        "total_minutes": round(target.total_minutes, 2),
        "avg_session_minutes": round(
            target.total_minutes / target.session_count, 2
        )
        if target.session_count
        else 0.0,
    }
    if isinstance(target, Context):
        payload["description"] = target.description
    else:
        payload["color"] = target.color
    return payload


def _apply_named_write(target, validated, *, extra_field):
    """Set name and the model-specific extra field from validated data."""
    update_fields = []
    if "name" in validated:
        target.name = validated["name"]
        update_fields.append("name")
    if extra_field in validated:
        setattr(target, extra_field, validated[extra_field])
        update_fields.append(extra_field)
    target.save(update_fields=update_fields)


def _named_count_queryset(model, user):
    completed_sessions = Q(
        projects__sessions__user=user,
        projects__sessions__end_time__isnull=False,
    )
    return (
        model.objects.filter(user=user)
        .annotate(
            project_count=Count(
                "projects",
                filter=Q(projects__user=user),
                distinct=True,
            ),
            session_count=Count(
                "projects__sessions",
                filter=completed_sessions,
                distinct=True,
            ),
            total_minutes=Coalesce(
                Sum(
                    rounded_session_minutes(
                        "projects__sessions__end_time",
                        "projects__sessions__start_time",
                    ),
                    filter=completed_sessions,
                ),
                Value(0.0),
                output_field=FloatField(),
            )
        )
        .order_by("name", "id")
    )


def _get_named_count_target(model, user, object_id, label):
    try:
        return _named_count_queryset(model, user).get(pk=object_id)
    except model.DoesNotExist as exc:
        raise NotFound(f"{label} {object_id} not found.") from exc


class ContextsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="contexts_list",
        responses=ContextListResponseSerializer,
    )
    def get(self, request):
        contexts = list(_named_count_queryset(Context, request.user))
        return Response(
            {
                "count": len(contexts),
                "contexts": ContextResourceSerializer(contexts, many=True).data,
            }
        )

    @extend_schema(
        operation_id="contexts_create",
        request=ContextWriteRequestSerializer,
        responses={201: ContextResourceSerializer},
    )
    def post(self, request):
        serializer = ContextWriteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data.get("name")
        if not name:
            raise ValidationError({"name": ["This field is required."]})
        if Context.objects.filter(user=request.user, name__iexact=name).exists():
            return _conflict(
                DestructiveOperationError(
                    "You already have a context with this name."
                )
            )
        context = Context.objects.create(
            user=request.user,
            name=name,
            description=serializer.validated_data.get("description"),
        )
        return Response(
            {
                "id": context.id,
                "name": context.name,
                "description": context.description,
                "project_count": 0,
                "session_count": 0,
                "total_minutes": 0.0,
                "avg_session_minutes": 0.0,
            },
            status=status.HTTP_201_CREATED,
        )


class ContextDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="contexts_partial_update",
        request=ContextWriteRequestSerializer,
        responses={200: ContextResourceSerializer},
    )
    def patch(self, request, context_id):
        context = _get_named_count_target(
            Context, request.user, context_id, "Context"
        )
        serializer = ContextWriteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data.get("name")
        if name and (
            Context.objects.filter(user=request.user, name__iexact=name)
            .exclude(pk=context.pk)
            .exists()
        ):
            return _conflict(
                DestructiveOperationError(
                    "You already have a context with this name."
                )
            )
        _apply_named_write(
            context, serializer.validated_data, extra_field="description"
        )
        return Response(_named_count_payload(context))

    @extend_schema(
        operation_id="contexts_destroy",
        request=None,
        responses={204: OpenApiResponse(description="Context deleted.")},
    )
    def delete(self, request, context_id):
        context = _delete_target_or_none(
            Context, request.user, context_id, "Context"
        )
        if context is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        try:
            DestructiveMutationService.delete_context(
                user=request.user, context_name=context.name
            )
        except DestructiveOperationError as exc:
            return _conflict(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TagsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="tags_list",
        responses=TagListResponseSerializer,
    )
    def get(self, request):
        tags = list(_named_count_queryset(Tag, request.user))
        return Response(
            {
                "count": len(tags),
                "tags": TagResourceSerializer(tags, many=True).data,
            }
        )

    @extend_schema(
        operation_id="tags_create",
        request=TagWriteRequestSerializer,
        responses={201: TagResourceSerializer},
    )
    def post(self, request):
        serializer = TagWriteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data.get("name")
        if not name:
            raise ValidationError({"name": ["This field is required."]})
        if Tag.objects.filter(user=request.user, name__iexact=name).exists():
            return _conflict(
                DestructiveOperationError("You already have a tag with this name.")
            )
        tag = Tag.objects.create(
            user=request.user,
            name=name,
            color=serializer.validated_data.get("color"),
        )
        return Response(
            {
                "id": tag.id,
                "name": tag.name,
                "color": tag.color,
                "project_count": 0,
                "session_count": 0,
                "total_minutes": 0.0,
                "avg_session_minutes": 0.0,
            },
            status=status.HTTP_201_CREATED,
        )


class TagDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="tags_partial_update",
        request=TagWriteRequestSerializer,
        responses={200: TagResourceSerializer},
    )
    def patch(self, request, tag_id):
        tag = _get_named_count_target(Tag, request.user, tag_id, "Tag")
        serializer = TagWriteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data.get("name")
        if name and (
            Tag.objects.filter(user=request.user, name__iexact=name)
            .exclude(pk=tag.pk)
            .exists()
        ):
            return _conflict(
                DestructiveOperationError("You already have a tag with this name.")
            )
        _apply_named_write(tag, serializer.validated_data, extra_field="color")
        return Response(_named_count_payload(tag))

    @extend_schema(
        operation_id="tags_destroy",
        request=None,
        responses={204: OpenApiResponse(description="Tag deleted.")},
    )
    def delete(self, request, tag_id):
        tag = _delete_target_or_none(Tag, request.user, tag_id, "Tag")
        if tag is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        try:
            DestructiveMutationService.delete_tag(
                user=request.user, tag_name=tag.name
            )
        except DestructiveOperationError as exc:
            return _conflict(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


