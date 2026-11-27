"""Account backup and restore endpoints for API v2.

One ZIP of everything in an account (not the CLI-format import/export).
Restore is two requests on the same file: preview reports what it would add
and what conflicts, with a signed token; restore applies exactly that preview
in one transaction, or nothing.
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.http import FileResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from core.api_v2.exceptions import V2APIView, _envelope
from core.services.account_backup import (
    RestoreConflict,
    attachment_summary,
    build_backup,
    preview_backup,
    restore_backup,
    validate_backup,
)
from core.services.backup_archive import archive_digest, read_archive
from core.services.backup_records import BackupError, SECTIONS
from core.utils import ACTIVE_CONTEXT_SESSION_KEY
from users.models import Profile


class ZipRenderer(JSONRenderer):
    """Negotiate a ZIP download while errors still render as JSON."""

    media_type = "application/zip"
    format = "zip"


@extend_schema_field(OpenApiTypes.BINARY)
class BackupFileField(serializers.FileField):
    pass


class BackupSummarySerializer(serializers.Serializer):
    attachment_count = serializers.IntegerField(help_text="Insights files sent in chats.")
    attachment_bytes = serializers.IntegerField(help_text="Their total size in bytes.")


class BackupQuerySerializer(serializers.Serializer):
    include_insights = serializers.BooleanField(
        required=False, default=False, help_text="Include Insights chats and their messages."
    )
    include_attachments = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Include the files attached to Insights chats (needs include_insights).",
    )

    def validate(self, attrs):
        if attrs["include_attachments"] and not attrs["include_insights"]:
            raise serializers.ValidationError(
                {"include_attachments": ["Files belong to chats: include Insights chats to back them up."]}
            )
        return attrs


class BackupUploadSerializer(serializers.Serializer):
    file = BackupFileField(help_text="An Autumn account backup ZIP.")


class BackupRestoreRequestSerializer(BackupUploadSerializer):
    preview_token = serializers.CharField(
        help_text="The preview_token from previewing this same file in this account."
    )


class BackupSectionCountsSerializer(serializers.Serializer):
    add = serializers.IntegerField()
    identical = serializers.IntegerField()
    conflict = serializers.IntegerField()


class BackupConflictSerializer(serializers.Serializer):
    section = serializers.ChoiceField(choices=list(SECTIONS))
    id = serializers.UUIDField(help_text="The record's ID in the backup.")
    label = serializers.CharField()


class BackupReportSerializer(serializers.Serializer):
    version = serializers.IntegerField()
    source_account = serializers.CharField(help_text="Username of the account the backup was made from.")
    destination_account = serializers.CharField(help_text="Username of this account.")
    same_account = serializers.BooleanField()
    can_restore = serializers.BooleanField(help_text="False while any conflict remains.")
    includes_insights = serializers.BooleanField()
    includes_attachments = serializers.BooleanField()
    counts = serializers.DictField(
        child=BackupSectionCountsSerializer(),
        help_text="Per section, in restore order: records to add, already here, and in conflict.",
    )
    conflicts = BackupConflictSerializer(
        many=True, help_text="Records in both with different contents (at most 100 listed)."
    )


class BackupPreviewSerializer(BackupReportSerializer):
    preview_token = serializers.CharField(
        help_text="Send with the same file to restore. Valid for an hour, for this account and file only."
    )


class BackupRestoreResultSerializer(BackupReportSerializer):
    restored = serializers.IntegerField(help_text="Records added. 0 when everything was already here.")


def _file_error(exc):
    return ValidationError({"file": [str(exc)]})


def _upload(request, serializer_class):
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _local_date(user):
    try:
        zone = ZoneInfo(user.profile.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        zone = timezone.get_current_timezone()
    return timezone.now().astimezone(zone).date()


class BackupSummaryView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="backup_summary_retrieve", responses=BackupSummarySerializer)
    def get(self, request):
        """What the optional attachments choice would add to a backup."""
        return Response(attachment_summary(request.user))


class BackupView(V2APIView):
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer, ZipRenderer]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if isinstance(response, Response) and response.status_code >= 400:
            response.accepted_renderer = JSONRenderer()
            response.accepted_media_type = "application/json"
        return response

    @extend_schema(
        operation_id="backup_retrieve",
        parameters=[BackupQuerySerializer],
        responses={
            (200, "application/zip"): OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description=(
                    "The account backup ZIP: contexts, tags, projects, completed sessions, "
                    "commitments and their history, planned reminders, settings and profile "
                    "images, and optionally Insights chats and files. Never passwords, API "
                    "keys, connected apps or running timers."
                ),
            ),
        },
    )
    def get(self, request):
        query = BackupQuerySerializer(data=request.query_params.dict())
        query.is_valid(raise_exception=True)
        try:
            archive = build_backup(
                request.user,
                include_insights=query.validated_data["include_insights"],
                include_attachments=query.validated_data["include_attachments"],
            )
        except BackupError as exc:
            raise ValidationError([str(exc)]) from exc
        response = FileResponse(
            archive,
            as_attachment=True,
            filename=f"autumn-backup-{_local_date(request.user).isoformat()}.zip",
            content_type="application/zip",
        )
        response["Cache-Control"] = "no-store"
        return response


class BackupPreviewView(V2APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        operation_id="backup_preview_create",
        request={"multipart/form-data": BackupUploadSerializer},
        responses={200: BackupPreviewSerializer},
    )
    def post(self, request):
        """Check a backup and compare it with this account. Changes nothing."""
        upload = _upload(request, BackupUploadSerializer)["file"]
        try:
            digest = archive_digest(upload)
            with read_archive(upload) as reader:
                manifest = validate_backup(reader)
            return Response(preview_backup(request.user, manifest, digest))
        except BackupError as exc:
            raise _file_error(exc) from exc


class BackupRestoreView(V2APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        operation_id="backup_restore_create",
        request={"multipart/form-data": BackupRestoreRequestSerializer},
        responses={
            200: BackupRestoreResultSerializer,
            409: OpenApiResponse(
                description=(
                    "Nothing was restored: the preview token is expired or for another file "
                    "or account, the account changed since the preview, or the backup has "
                    "conflicts. Preview again."
                ),
            ),
        },
    )
    def post(self, request):
        """Add what the preview showed, in one transaction. Records already
        here are left as they are; nothing in this account is replaced or
        removed."""
        data = _upload(request, BackupRestoreRequestSerializer)
        upload = data["file"]
        try:
            digest = archive_digest(upload)
            with read_archive(upload) as reader:
                manifest = validate_backup(reader)
                result = restore_backup(
                    request.user, manifest, reader, digest=digest, token=data["preview_token"]
                )
        except BackupError as exc:
            raise _file_error(exc) from exc
        except RestoreConflict as exc:
            details = {"preview_token": [str(exc)]}
            if exc.report is not None:
                details["preview"] = exc.report
            return Response(
                _envelope("stale_preview", str(exc), details),
                status=status.HTTP_409_CONFLICT,
            )
        if result["counts"]["profile"]["add"]:
            active_context = Profile.objects.values_list("active_context_id", flat=True).get(user=request.user)
            if hasattr(request, "session"):
                request.session[ACTIVE_CONTEXT_SESSION_KEY] = str(active_context) if active_context else "all"
        return Response(result)
