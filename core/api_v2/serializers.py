from datetime import timezone as datetime_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


def _local_date(value):
    if value is None:
        return None
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.date()


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


class NamedResourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class CleanedNameField(serializers.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 100)
        kwargs.setdefault("allow_blank", False)
        super().__init__(**kwargs)

    def to_internal_value(self, value):
        if not isinstance(value, str):
            raise serializers.ValidationError("'name' must be a string.")
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Missing 'name'.")
        if len(value) > 100:
            raise serializers.ValidationError(
                "'name' must be 100 characters or fewer."
            )
        return value


class ContextWriteRequestSerializer(serializers.Serializer):
    name = CleanedNameField(required=False)
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Provide at least one of 'name' or 'description'."
            )
        return attrs


class TagWriteRequestSerializer(serializers.Serializer):
    name = CleanedNameField(required=False)
    color = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=20
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Provide at least one of 'name' or 'color'."
            )
        return attrs


class ContextResourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField(allow_null=True)
    project_count = serializers.IntegerField()


class TagResourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    color = serializers.CharField(allow_null=True)
    project_count = serializers.IntegerField()


class ContextListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    contexts = ContextResourceSerializer(many=True)


class TagListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    tags = TagResourceSerializer(many=True)


class SubprojectResourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.SerializerMethodField()
    project_id = serializers.IntegerField(source="parent_project_id")
    last_activity = serializers.SerializerMethodField()
    total_minutes = serializers.SerializerMethodField()
    session_count = serializers.IntegerField(source="completed_session_count")

    @extend_schema_field(serializers.CharField())
    def get_description(self, subproject):
        return subproject.description or ""

    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_last_activity(self, subproject):
        return _local_date(subproject.derived_last_updated)

    @extend_schema_field(serializers.FloatField())
    def get_total_minutes(self, subproject):
        return round(subproject.derived_total_time, 2)


class ProjectResourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    status = serializers.ChoiceField(
        choices=("active", "paused", "complete", "archived")
    )
    description = serializers.SerializerMethodField()
    context = NamedResourceSerializer(allow_null=True)
    tags = serializers.SerializerMethodField()
    start_date = serializers.SerializerMethodField()
    last_activity = serializers.SerializerMethodField()
    total_minutes = serializers.SerializerMethodField()
    session_count = serializers.IntegerField(source="completed_session_count")

    @extend_schema_field(serializers.CharField())
    def get_description(self, project):
        return project.description or ""

    @extend_schema_field(NamedResourceSerializer(many=True))
    def get_tags(self, project):
        tags = getattr(project, "prefetched_tags", None)
        if tags is None:
            tags = project.tags.order_by("name", "id")
        return NamedResourceSerializer(tags, many=True).data

    @extend_schema_field(serializers.DateField())
    def get_start_date(self, project):
        return _local_date(project.start_date)

    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_last_activity(self, project):
        return _local_date(project.derived_last_updated)

    @extend_schema_field(serializers.FloatField())
    def get_total_minutes(self, project):
        return round(project.derived_total_time, 2)


class ProjectDetailResourceSerializer(ProjectResourceSerializer):
    subprojects = serializers.SerializerMethodField()

    @extend_schema_field(SubprojectResourceSerializer(many=True))
    def get_subprojects(self, project):
        subprojects = getattr(project, "prefetched_subprojects", None)
        if subprojects is None:
            subprojects = project.subprojects.order_by("name", "id")
        return SubprojectResourceSerializer(subprojects, many=True).data


class ProjectCreateRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, allow_blank=False)
    description = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(
        required=False,
        default="active",
        choices=("active", "paused", "complete", "archived"),
    )
    context_id = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )


class ProjectPatchRequestSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, max_length=255, allow_blank=False)
    description = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(
        required=False, choices=("active", "paused", "complete", "archived")
    )
    context_id = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    start_date = serializers.DateField(required=False)


class ProjectMergeRequestSerializer(serializers.Serializer):
    source_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=2, max_length=2
    )
    new_name = serializers.CharField(max_length=255, allow_blank=False)


class ProjectListQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        required=False, choices=("active", "paused", "complete", "archived")
    )
    search = serializers.CharField(required=False)
    context_ids = serializers.CharField(required=False)
    tag_ids = serializers.CharField(required=False)
    exclude_project_ids = serializers.CharField(required=False)
    limit = serializers.IntegerField(
        required=False, default=100, min_value=1, max_value=500
    )
    offset = serializers.IntegerField(required=False, default=0, min_value=0)
    ordering = serializers.ChoiceField(
        required=False, default="name", choices=("name", "id")
    )


class ProjectListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    total = serializers.IntegerField()
    projects = ProjectResourceSerializer(many=True)


class SubprojectCreateRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, allow_blank=False)
    description = serializers.CharField(required=False, allow_blank=True)


class SubprojectPatchRequestSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, max_length=255, allow_blank=False)
    description = serializers.CharField(required=False, allow_blank=True)


class SubprojectMergeRequestSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1)
    source_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=2, max_length=2
    )
    new_name = serializers.CharField(max_length=255, allow_blank=False)


class SubprojectListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    subprojects = SubprojectResourceSerializer(many=True)


class MeUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    timezone = serializers.CharField()


class MeSerializer(serializers.Serializer):
    api_version = serializers.IntegerField()
    capabilities = serializers.ListField(child=serializers.CharField())
    user = MeUserSerializer()


class ReportTotalsSerializer(serializers.Serializer):
    total_minutes = serializers.FloatField()
    session_count = serializers.IntegerField()


class ReportTallyEntrySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=("subproject", "residual"), required=False
    )
    project_id = serializers.IntegerField(required=False)
    id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField(allow_null=True)
    total_minutes = serializers.FloatField()
    session_count = serializers.IntegerField(required=False)
    legacy_overallocated = serializers.BooleanField(required=False)


class ReportTalliesSerializer(serializers.Serializer):
    by = serializers.ChoiceField(
        choices=("project", "subproject", "context", "status", "tag")
    )
    entries = ReportTallyEntrySerializer(many=True)


class ReportHierarchyChildSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=("subproject", "residual"))
    project_id = serializers.IntegerField(required=False)
    id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField(allow_null=True)
    total_minutes = serializers.FloatField()


class ReportHierarchyProjectSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    total_minutes = serializers.FloatField()
    children = ReportHierarchyChildSerializer(many=True)
    legacy_overallocated = serializers.BooleanField()


class ReportHierarchySerializer(serializers.Serializer):
    projects = ReportHierarchyProjectSerializer(many=True)


class ChartPayloadRowSerializer(serializers.Serializer):
    x = serializers.DateTimeField(required=False)
    y = serializers.FloatField(required=False)
    series = serializers.CharField(required=False)
    date = serializers.DateField(required=False)
    hours = serializers.FloatField(required=False)
    start_time = serializers.DateTimeField(required=False)
    end_time = serializers.DateTimeField(required=False)
    label = serializers.CharField(required=False)
    count = serializers.IntegerField(required=False)
    text = serializers.CharField(required=False)
    weight = serializers.IntegerField(required=False)
