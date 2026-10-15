"""Portable import/export endpoints for API v2."""

import json
import uuid

from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from django.http import StreamingHttpResponse

from core.api_v2.exceptions import V2APIView, _envelope, related_outcome
from core.api_v2.filters import SessionFilterSpec
from core.api_v2.renderers import EventStreamRenderer
from core.export2 import build_format2_export
from core.forms import ImportJSONForm
from core.importer import iter_import, run_import
from core.importer2 import Format2ConflictError, Format2ValidationError
from core.models import Context, Sessions
from core.temp_uploads import discard_upload, store_upload
from core.utils import build_project_json_from_sessions, json_compress, json_decompress


class ExportQuerySerializer(serializers.Serializer):
    project_name = serializers.CharField(required=False, allow_blank=True)
    project_ids = serializers.CharField(required=False)
    subproject_ids = serializers.CharField(required=False)
    context_ids = serializers.CharField(required=False)
    tag_ids = serializers.CharField(required=False)
    exclude_project_ids = serializers.CharField(required=False)
    exclude_subproject_ids = serializers.CharField(required=False)
    exclude_tag_ids = serializers.CharField(required=False)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    active = serializers.BooleanField(required=False)
    note_snippet = serializers.CharField(required=False)
    search = serializers.CharField(
        required=False,
        help_text="Search project names, assigned subproject names and session notes.",
    )
    related = serializers.BooleanField(
        required=False,
        help_text=(
            "With search, also include completed sessions that match it by meaning. "
            "Needs AI features and an OpenAI key on the account; otherwise ignored."
        ),
    )
    compress = serializers.BooleanField(required=False, default=False)
    # "format" collides with DRF's renderer-override query param.
    export_format = serializers.ChoiceField(required=False, choices=("1", "2"), default="2")
    # format-1 only: emit the Autumn-CLI-compatible variant of the heritage doc
    autumn_compatible = serializers.BooleanField(required=False, default=False)


class ImportUploadRequestSerializer(serializers.Serializer):
    file = serializers.FileField()
    autumn_import = serializers.BooleanField(required=False, default=False)
    force = serializers.BooleanField(required=False, default=False)
    merge = serializers.BooleanField(required=False, default=True)
    tolerance = serializers.FloatField(required=False, default=0.5)
    verbose = serializers.BooleanField(required=False, default=False)
    import_context = serializers.IntegerField(required=False, allow_null=True)
    import_context_new = serializers.CharField(required=False, allow_blank=True)


class ImportUploadResponseSerializer(serializers.Serializer):
    upload_id = serializers.UUIDField()


class ImportRequestSerializer(serializers.Serializer):
    data = serializers.JSONField(required=False)
    data_compressed = serializers.CharField(required=False)
    force = serializers.BooleanField(required=False, default=False)
    # Heritage format-1 options (rejected for format-2 payloads)
    merge = serializers.BooleanField(required=False, default=False)
    tolerance = serializers.IntegerField(required=False, default=2, min_value=0)
    autumn_import = serializers.BooleanField(required=False, default=False)
    context = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if ("data" in attrs) == ("data_compressed" in attrs):
            raise serializers.ValidationError(
                "Provide exactly one of 'data' or 'data_compressed'."
            )
        return attrs


class ImportSummarySerializer(serializers.Serializer):
    projects_created = serializers.IntegerField()
    projects_updated = serializers.IntegerField()
    sessions_imported = serializers.IntegerField()
    sessions_skipped = serializers.IntegerField()
    conflicts = serializers.ListField(child=serializers.CharField())


class Format2LinkSerializer(serializers.Serializer):
    subproject = serializers.CharField()
    allocation_bp = serializers.IntegerField(min_value=1, max_value=10000)


class Format2SessionSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(required=False, allow_null=True)
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    note = serializers.CharField(allow_blank=True, allow_null=True)
    links = Format2LinkSerializer(many=True)


class Format2SubprojectSerializer(serializers.Serializer):
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)


class Format2ProjectSerializer(serializers.Serializer):
    name = serializers.CharField()
    status = serializers.ChoiceField(choices=("active", "paused", "complete", "archived"))
    description = serializers.CharField(allow_blank=True)
    context = serializers.CharField(allow_null=True)
    tags = serializers.ListField(child=serializers.CharField())
    start_date = serializers.DateTimeField()
    subprojects = Format2SubprojectSerializer(many=True)
    sessions = Format2SessionSerializer(many=True)


class Format2DocumentSerializer(serializers.Serializer):
    format = serializers.IntegerField(min_value=2, max_value=2)
    projects = Format2ProjectSerializer(many=True)


class ExportView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="export_retrieve",
        parameters=[ExportQuerySerializer],
        responses=Format2DocumentSerializer,
    )
    def get(self, request):
        query = ExportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        options = query.validated_data
        compress = options["compress"]
        spec = SessionFilterSpec.from_query_params(request.query_params, request.user)
        queryset = spec.apply(
            Sessions.objects.filter(user=request.user, end_time__isnull=False),
            user=request.user,
            outcome=related_outcome(request),
        )
        project_name = (options.get("project_name") or "").strip()
        if project_name:
            queryset = queryset.filter(project__name__icontains=project_name)
        if options["export_format"] == "1":
            document = build_project_json_from_sessions(
                queryset.order_by("-end_time", "id"),
                options["autumn_compatible"],
            )
        else:
            document = build_format2_export(queryset)
        return Response(json_compress(document) if compress else document)


class ImportView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="import_create",
        request=ImportRequestSerializer,
        responses={200: ImportSummarySerializer},
    )
    def post(self, request):
        serializer = ImportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        if "data_compressed" in validated:
            try:
                import_data = json_decompress(validated["data_compressed"])
            except Exception as exc:
                raise ValidationError(
                    {"data_compressed": ["Could not decompress payload."]}
                ) from exc
        else:
            import_data = validated["data"]

        is_format2 = isinstance(import_data, dict) and import_data.get("format") == 2
        legacy_args_sent = any(
            key in request.data for key in ("merge", "tolerance", "autumn_import", "context")
        )
        if is_format2 and legacy_args_sent:
            raise ValidationError(
                {
                    "non_field_errors": [
                        "merge/tolerance/autumn_import/context apply to "
                        "format-1 payloads only."
                    ]
                }
            )

        import_kwargs = {"force": validated["force"]}
        if not is_format2:
            # Heritage format-1 semantics, mirrored from the removed v1 endpoint.
            import_into_context = None
            context_name = (validated.get("context") or "").strip()
            if context_name:
                import_into_context = Context.objects.filter(
                    user=request.user, name__iexact=context_name
                ).first()
                if import_into_context is None:
                    import_into_context = Context.objects.create(
                        user=request.user, name=context_name
                    )
            import_kwargs.update(
                merge=validated["merge"],
                tolerance=validated["tolerance"],
                autumn_import=validated["autumn_import"],
                import_into_context=import_into_context,
            )

        try:
            summary = run_import(
                request.user,
                import_data,
                **import_kwargs,
            )
        except Format2ConflictError as exc:
            return Response(
                _envelope(
                    "conflict",
                    "One or more session UUIDs conflict with existing content.",
                    {"conflicting_uuids": exc.conflicts},
                ),
                status=status.HTTP_409_CONFLICT,
            )
        except Format2ValidationError as exc:
            return Response(
                _envelope(
                    "validation_error",
                    "Invalid input.",
                    {"errors": exc.errors},
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            raise ValidationError({"data": [str(exc)]}) from exc

        payload = {
            "projects_created": summary.get("projects_created", 0),
            "projects_updated": summary.get("projects_updated", 0),
            "sessions_imported": summary.get("sessions_imported", 0),
            "sessions_skipped": summary.get("sessions_skipped", 0),
            "conflicts": summary.get("conflicts", []),
        }
        # Heritage format-1 imports report skipped project names.
        if summary.get("skipped"):
            payload["skipped"] = summary["skipped"]
        return Response(payload)


def _stream_response(message):
    return f"data: {json.dumps({'message': message})}\n\n"


class ImportUploadView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="import_uploads_create",
        request=ImportUploadRequestSerializer,
        responses={201: ImportUploadResponseSerializer},
    )
    def post(self, request):
        serializer = ImportUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # Use the API serializer's explicit defaults. An omitted HTML checkbox
        # means false to Django forms, while the import page starts with merge
        # enabled and API clients should get that same default when omitting it.
        form_data = {
            key: value
            for key, value in data.items()
            if key != "file" and value is not None
        }
        form = ImportJSONForm(
            form_data,
            {"file": data["file"]},
            user=request.user,
        )
        if not form.is_valid():
            raise ValidationError(
                {
                    field: [str(message) for message in messages]
                    for field, messages in form.errors.items()
                }
            )
        upload_id = str(uuid.uuid4())
        path = store_upload(form.cleaned_data["file"])
        context = form.cleaned_data.get("import_context")
        uploads = dict(request.session.get("api_import_uploads") or {})
        uploads[upload_id] = {
            "file_path": path,
            "autumn_import": form.cleaned_data.get("autumn_import", False),
            "force": form.cleaned_data.get("force", False),
            "merge": form.cleaned_data.get("merge", True),
            "tolerance": form.cleaned_data.get("tolerance", 0.5),
            "verbose": form.cleaned_data.get("verbose", False),
            "import_context_id": context.pk if context else None,
            "import_context_new": form.cleaned_data.get("import_context_new", ""),
        }
        request.session["api_import_uploads"] = uploads
        request.session.modified = True
        return Response({"upload_id": upload_id}, status=status.HTTP_201_CREATED)


class ImportUploadStreamView(V2APIView):
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer, EventStreamRenderer]

    @extend_schema(
        operation_id="import_uploads_stream_retrieve",
        responses={
            (200, "text/event-stream"): OpenApiResponse(
                response=OpenApiTypes.STR,
                description=(
                    "Server-sent default message events. Each data payload is a JSON "
                    "object with a message string containing an import progress, "
                    "completion, skipped-project, or Error line from iter_import."
                ),
            )
        },
    )
    def get(self, request, upload_id):
        uploads = dict(request.session.get("api_import_uploads") or {})
        data = uploads.pop(str(upload_id), None)
        if data is None:
            from rest_framework.exceptions import NotFound

            raise NotFound("Import upload not found or already consumed.")
        request.session["api_import_uploads"] = uploads
        request.session.modified = True
        path = data["file_path"]

        def event_stream():
            try:
                context = None
                new_name = (data.get("import_context_new") or "").strip()
                if new_name:
                    context, _ = Context.objects.get_or_create(
                        user=request.user, name=new_name
                    )
                elif data.get("import_context_id"):
                    context = Context.objects.filter(
                        user=request.user, pk=data["import_context_id"]
                    ).first()
                with open(path, encoding="utf-8") as handle:
                    raw = handle.read()
                try:
                    document = json_decompress(raw)
                except RuntimeError:
                    try:
                        document = json.loads(raw)
                    except json.JSONDecodeError:
                        yield _stream_response("Error: Invalid JSON file")
                        return
                for message in iter_import(
                    request.user,
                    document,
                    force=data.get("force"),
                    merge=data.get("merge"),
                    tolerance=data.get("tolerance"),
                    verbose=data.get("verbose"),
                    autumn_import=data.get("autumn_import"),
                    import_into_context=context,
                ):
                    yield _stream_response(message)
            except Exception as exc:
                yield _stream_response(f"Error: {exc}")
            finally:
                discard_upload(path)

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
