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
from core.models import Sessions
from core.utils import json_compress


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


class ImportRequestSerializer(serializers.Serializer):
    data = serializers.JSONField()
    force = serializers.BooleanField(required=False, default=False)


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
        try:
            summary = run_import(
                request.user,
                serializer.validated_data["data"],
                force=serializer.validated_data["force"],
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

        return Response(
            {
                "projects_created": summary.get("projects_created", 0),
                "projects_updated": summary.get("projects_updated", 0),
                "sessions_imported": summary.get("sessions_imported", 0),
                "sessions_skipped": summary.get("sessions_skipped", 0),
                "conflicts": summary.get("conflicts", []),
            }
        )
