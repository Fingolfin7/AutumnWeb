"""Portable import/export endpoints for API v2."""

from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from core.api_v2.exceptions import V2APIView, _envelope
from core.api_v2.filters import SessionFilterSpec
from core.export2 import build_format2_export
from core.importer import run_import
from core.importer2 import Format2ConflictError, Format2ValidationError
from core.models import Context, Sessions
from core.utils import build_project_json_from_sessions, json_compress, json_decompress


class ExportQuerySerializer(serializers.Serializer):
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
    compress = serializers.BooleanField(required=False, default=False)
    # "format" collides with DRF's renderer-override query param.
    export_format = serializers.ChoiceField(required=False, choices=("1", "2"), default="2")
    # format-1 only: emit the Autumn-CLI-compatible variant of the heritage doc
    autumn_compatible = serializers.BooleanField(required=False, default=False)


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
    allocation_mode = serializers.ChoiceField(choices=("legacy_full", "partitioned"))
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
        compress_field = serializers.BooleanField(required=False, default=False)
        try:
            compress = (
                False
                if "compress" not in request.query_params
                else compress_field.run_validation(request.query_params.get("compress"))
            )
        except serializers.ValidationError as exc:
            raise ValidationError({"compress": exc.detail}) from exc
        spec = SessionFilterSpec.from_query_params(request.query_params, request.user)
        queryset = spec.apply(
            Sessions.objects.filter(user=request.user, end_time__isnull=False)
        )
        if request.query_params.get("export_format") == "1":
            autumn_compatible = serializers.BooleanField(
                required=False, default=False
            ).run_validation(request.query_params.get("autumn_compatible", False))
            document = build_project_json_from_sessions(
                queryset.order_by("-end_time", "id"), autumn_compatible
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
