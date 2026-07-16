from datetime import timezone as datetime_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


class UTCDateTimeField(serializers.DateTimeField):
    """An ISO-8601 instant which treats a missing offset as UTC."""

    default_error_messages = {"invalid": "Enter a valid ISO-8601 timestamp."}

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "help_text",
            "ISO-8601 instant; a timestamp without an offset is interpreted as UTC.",
        )
        super().__init__(*args, **kwargs)

    def to_internal_value(self, value):
        if not isinstance(value, str):
            self.fail("invalid")
        try:
            instant = parse_datetime(value)
        except (TypeError, ValueError, OverflowError):
            instant = None
        if instant is None:
            self.fail("invalid")
        if timezone.is_naive(instant):
            instant = instant.replace(tzinfo=datetime_timezone.utc)
        return instant.astimezone(datetime_timezone.utc).replace(microsecond=0)

    def to_representation(self, value):
        if value is None:
            return None
        if timezone.is_naive(value):
            value = value.replace(tzinfo=datetime_timezone.utc)
        return value.astimezone(datetime_timezone.utc).isoformat()


class ProjectSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class SubprojectAllocationSerializer(serializers.Serializer):
    subproject_id = serializers.IntegerField()
    name = serializers.CharField()
    allocation_bp = serializers.IntegerField()


class SessionResourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    uuid = serializers.UUIDField(allow_null=True)
    version = serializers.IntegerField()
    project = ProjectSummarySerializer()
    allocation_mode = serializers.ChoiceField(
        choices=("legacy_full", "partitioned")
    )
    subproject_allocations = serializers.SerializerMethodField()
    start = UTCDateTimeField(source="start_time")
    end = UTCDateTimeField(source="end_time", allow_null=True)
    active = serializers.SerializerMethodField()
    auto_stop_at = UTCDateTimeField(allow_null=True)
    duration_minutes = serializers.SerializerMethodField()
    elapsed_minutes = serializers.SerializerMethodField()
    note = serializers.CharField(allow_null=True, required=False)

    @extend_schema_field(SubprojectAllocationSerializer(many=True))
    def get_subproject_allocations(self, session):
        links = session.subproject_links.select_related("subproject").order_by(
            "subproject_id"
        )
        return [
            {
                "subproject_id": link.subproject_id,
                "name": link.subproject.name,
                "allocation_bp": link.allocation_bp,
            }
            for link in links
        ]

    @extend_schema_field(serializers.BooleanField())
    def get_active(self, session):
        return session.end_time is None

    @extend_schema_field(serializers.FloatField(allow_null=True))
    def get_duration_minutes(self, session):
        if session.end_time is None:
            return None
        return round(
            (session.end_time - session.start_time).total_seconds() / 60.0,
            2,
        )

    @extend_schema_field(serializers.FloatField(allow_null=True))
    def get_elapsed_minutes(self, session):
        if session.end_time is not None:
            return None
        return round(
            (timezone.now() - session.start_time).total_seconds() / 60.0,
            2,
        )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.context.get("include_note", True):
            data.pop("note", None)
        return data


class TimerStartRequestSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1)
    subproject_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    stop_after_minutes = serializers.FloatField(
        required=False, min_value=0.000001, max_value=10080
    )
    start = UTCDateTimeField(required=False)
    uuid = serializers.UUIDField(required=False)


class TimerStopRequestSerializer(serializers.Serializer):
    end = UTCDateTimeField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class TimerRestartRequestSerializer(serializers.Serializer):
    start = UTCDateTimeField(required=False)


class SessionTrackRequestSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1)
    start = UTCDateTimeField()
    end = UTCDateTimeField()
    subproject_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    uuid = serializers.UUIDField(required=False)


class SessionPatchRequestSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(required=False, min_value=1)
    start = UTCDateTimeField(required=False)
    end = UTCDateTimeField(required=False, allow_null=False)
    subproject_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class TimerListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    timers = SessionResourceSerializer(many=True)


class SessionListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    total = serializers.IntegerField()
    sessions = SessionResourceSerializer(many=True)


class SessionListQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(required=False, default=100, min_value=1, max_value=500)
    offset = serializers.IntegerField(required=False, default=0, min_value=0)
    include = serializers.ChoiceField(required=False, choices=("note",))
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


class MeUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    timezone = serializers.CharField()


class MeSerializer(serializers.Serializer):
    api_version = serializers.IntegerField()
    capabilities = serializers.ListField(child=serializers.CharField())
    user = MeUserSerializer()
