from datetime import timezone as datetime_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.templatetags.markdown_render import markdown as render_markdown


SEARCH_HELP = (
    "Search project names, assigned subproject names and session notes. Every word "
    "must appear (in any of them, in any order); put a phrase in double quotes to "
    'match it as written. Common words such as "it" and "the" are ignored.'
)
SIMILARITY_HELP = (
    "How close a meaning-based match must be to count as related, from 0.25 "
    "(loose) to 0.60 (strict). Defaults to the account's setting (0.45 unless "
    "changed in Profile). Only used with search and related=true; the cutoff "
    "applied is echoed in the X-Autumn-Related-Similarity header."
)


def similarity_field(**kwargs):
    """The related-match cutoff parameter (core.services.semantic_search bounds)."""
    kwargs.setdefault("help_text", SIMILARITY_HELP)
    return serializers.FloatField(
        required=False,
        min_value=0.25,
        max_value=0.60,
        **kwargs,
    )


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


class OffsetDateTimeField(serializers.DateTimeField):
    default_error_messages = {
        "invalid": "Enter a valid ISO-8601 timestamp with an offset."
    }

    def to_internal_value(self, value):
        if not isinstance(value, str):
            self.fail("invalid")
        try:
            instant = parse_datetime(value)
        except (TypeError, ValueError, OverflowError):
            instant = None
        if instant is None or timezone.is_naive(instant):
            self.fail("invalid")
        return instant


class ProjectSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class SubprojectAllocationSerializer(serializers.Serializer):
    subproject_id = serializers.IntegerField()
    name = serializers.CharField()
    allocation_bp = serializers.IntegerField()


class SubprojectAllocationWriteSerializer(serializers.Serializer):
    subproject_id = serializers.IntegerField(min_value=1)
    allocation_bp = serializers.IntegerField(min_value=1, max_value=10000)


class CelebrationSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=("progress", "completion"))
    message = serializers.CharField()


class TimerReminderCreateSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=("after", "interval", "at"))
    amount = serializers.FloatField(required=False)
    unit = serializers.ChoiceField(choices=("minutes", "hours"), required=False)
    at = OffsetDateTimeField(required=False)
    message = serializers.CharField(required=False, allow_blank=True, max_length=240)

class TimerReminderSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    session_id = serializers.IntegerField()
    mode = serializers.ChoiceField(choices=("after", "at", "interval"))
    next_fire_at = UTCDateTimeField()
    interval_seconds = serializers.IntegerField(allow_null=True)
    message = serializers.CharField(allow_blank=True)
    last_fired_at = UTCDateTimeField(allow_null=True)
    created_at = UTCDateTimeField()


class TimerReminderListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    reminders = TimerReminderSerializer(many=True)


class SessionResourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    uuid = serializers.UUIDField(allow_null=True)
    version = serializers.IntegerField()
    project = ProjectSummarySerializer()
    subproject_allocations = serializers.SerializerMethodField()
    start = UTCDateTimeField(source="start_time")
    end = UTCDateTimeField(source="end_time", allow_null=True)
    active = serializers.SerializerMethodField()
    auto_stop_at = UTCDateTimeField(allow_null=True)
    notify_on_auto_stop = serializers.BooleanField()
    duration_minutes = serializers.SerializerMethodField()
    elapsed_minutes = serializers.SerializerMethodField()
    note = serializers.CharField(allow_null=True, required=False)
    note_html = serializers.SerializerMethodField(required=False)
    commitment_history_unaffected = serializers.BooleanField(required=False)
    active_reminders = serializers.SerializerMethodField(required=False)
    celebration = serializers.SerializerMethodField(required=False)

    @extend_schema_field(SubprojectAllocationSerializer(many=True))
    def get_subproject_allocations(self, session):
        # Sort in Python so a list-level prefetch_related is not defeated by
        # a fresh queryset (order_by would re-query per session).
        links = sorted(
            session.subproject_links.all(), key=lambda link: link.subproject_id
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

    @extend_schema_field(serializers.CharField())
    def get_note_html(self, session):
        # Dropped in to_representation unless asked for; skip the rendering.
        if not self.context.get("include_note_html", False):
            return None
        return render_markdown(session.note or "")

    @extend_schema_field(TimerReminderSerializer(many=True))
    def get_active_reminders(self, session):
        # Dropped in to_representation unless asked for; without this guard
        # every listed session would run its own reminders query.
        if not self.context.get("include_reminders", False):
            return []
        reminders = getattr(session, "active_reminders", None)
        if reminders is None:
            reminders = session.reminders.filter(active=True).order_by("next_fire_at", "id")
        return TimerReminderSerializer(reminders, many=True).data

    @extend_schema_field(CelebrationSerializer(allow_null=True))
    def get_celebration(self, session):
        return getattr(session, "celebration", None)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.context.get("include_note", True):
            data.pop("note", None)
        if not self.context.get("include_note_html", False):
            data.pop("note_html", None)
        if not self.context.get("include_reminders", False):
            data.pop("active_reminders", None)
        if not hasattr(instance, "celebration"):
            data.pop("celebration", None)
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
    notify_on_auto_stop = serializers.BooleanField(required=False, default=False)
    reminder = TimerReminderCreateSerializer(required=False)


class TimerStopRequestSerializer(serializers.Serializer):
    end = UTCDateTimeField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    subproject_allocations = SubprojectAllocationWriteSerializer(
        many=True, required=False
    )


class TimerNoteRequestSerializer(serializers.Serializer):
    note = serializers.CharField(allow_blank=True, allow_null=True)


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
    subproject_allocations = SubprojectAllocationWriteSerializer(
        many=True, required=False
    )


class SessionPatchRequestSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(required=False, min_value=1)
    start = UTCDateTimeField(required=False)
    end = UTCDateTimeField(required=False, allow_null=False)
    subproject_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    subproject_allocations = SubprojectAllocationWriteSerializer(
        many=True, required=False
    )


class TimerListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    timers = SessionResourceSerializer(many=True)


def _parse_resource_include(value):
    values = [item.strip() for item in value.split(",")]
    if any(not item for item in values) or len(values) != len(set(values)):
        raise serializers.ValidationError(
            "Enter a comma-separated list without blanks or duplicates."
        )
    unknown = sorted(set(values) - {"note", "note_html", "reminders"})
    if unknown:
        raise serializers.ValidationError(
            f"Unsupported include value: {', '.join(unknown)}."
        )
    return values


class ResourceIncludeQuerySerializer(serializers.Serializer):
    include = serializers.CharField(required=False, allow_blank=False)
    context = serializers.CharField(required=False, allow_blank=False)

    def validate_include(self, value):
        return _parse_resource_include(value)


class SessionListItemSerializer(SessionResourceSerializer):
    match = serializers.ChoiceField(
        choices=("direct", "related"),
        required=False,
        help_text=(
            "With search: direct when the session's project, subproject or note "
            "contains the search text, related when it matches only by meaning."
        ),
    )


class SessionListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    total = serializers.IntegerField()
    sessions = SessionListItemSerializer(many=True)


class RelatedSummaryMarkSerializer(serializers.Serializer):
    label = serializers.CharField()
    value = serializers.FloatField()


class RelatedSummarySerializer(serializers.Serializer):
    available = serializers.BooleanField()
    similarity = serializers.FloatField()
    default = serializers.FloatField()
    floor = serializers.FloatField()
    ceiling = serializers.FloatField()
    step = serializers.FloatField()
    marks = RelatedSummaryMarkSerializer(many=True)
    counts = serializers.ListField(child=serializers.IntegerField())
    count = serializers.IntegerField()
    best = serializers.FloatField(allow_null=True)
    loosen_to = serializers.FloatField(allow_null=True)


class CommitmentHistoryWarningSerializer(serializers.Serializer):
    commitment_history_unaffected = serializers.BooleanField()


class SessionListQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(required=False, default=100, min_value=1, max_value=500)
    offset = serializers.IntegerField(required=False, default=0, min_value=0)
    include = serializers.CharField(required=False, allow_blank=False)
    ids = serializers.CharField(
        required=False,
        help_text="Comma-separated session IDs.",
    )
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
        help_text=SEARCH_HELP,
    )
    related = serializers.BooleanField(
        required=False,
        help_text=(
            "With search, also include completed sessions that match it by meaning. "
            "Needs AI features and an OpenAI key on the account; otherwise ignored."
        ),
    )
    similarity = similarity_field()

    def validate_include(self, value):
        return _parse_resource_include(value)
    ordering = serializers.ChoiceField(
        required=False,
        default="relevance",
        choices=("relevance", "newest"),
        help_text=(
            "relevance (default): direct matches newest first, then related "
            "matches best first, the order the Sessions page shows. newest: all "
            "by end time, newest first. Without search the two are the same."
        ),
    )
    uuid = serializers.UUIDField(required=False)


class SessionRelatedSummaryQuerySerializer(SessionListQuerySerializer):
    """Session list filters without result paging or representation controls."""

    related = serializers.BooleanField(
        required=False,
        help_text=(
            "Accepted for session-list query parity; this summary always describes "
            "related-only matches."
        ),
    )
    similarity = similarity_field(
        help_text=(
            "Cutoff whose related-only count is returned in count. Defaults to the "
            "account setting."
        )
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ("limit", "offset", "include", "ordering"):
            self.fields.pop(field_name)


COMMITMENT_AGGREGATION_CHOICES = ("project", "subproject", "context", "tag")
COMMITMENT_TYPE_CHOICES = ("time", "sessions")
COMMITMENT_PERIOD_CHOICES = (
    "daily",
    "weekly",
    "fortnightly",
    "monthly",
    "quarterly",
    "yearly",
)


class CommitmentChangesRequestSerializer(serializers.Serializer):
    aggregation_type = serializers.ChoiceField(
        required=False, choices=COMMITMENT_AGGREGATION_CHOICES
    )
    project_id = serializers.IntegerField(required=False, min_value=1)
    subproject_id = serializers.IntegerField(required=False, min_value=1)
    context_id = serializers.IntegerField(required=False, min_value=1)
    tag_id = serializers.IntegerField(required=False, min_value=1)
    commitment_type = serializers.ChoiceField(
        required=False, choices=COMMITMENT_TYPE_CHOICES
    )
    period = serializers.ChoiceField(
        required=False, choices=COMMITMENT_PERIOD_CHOICES
    )
    start_date = serializers.DateField(required=False)
    timezone = serializers.CharField(required=False, max_length=64)
    target_value = serializers.IntegerField(required=False, min_value=1)
    banking_enabled = serializers.BooleanField(required=False)
    max_balance = serializers.IntegerField(required=False)
    min_balance = serializers.IntegerField(required=False)
    active = serializers.BooleanField(required=False)
    include_project_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    exclude_project_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    include_subproject_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    exclude_subproject_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    include_context_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    exclude_context_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    include_tag_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    exclude_tag_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )

    def validate(self, attrs):
        target_fields = (
            "project_id",
            "subproject_id",
            "context_id",
            "tag_id",
        )
        supplied = [field for field in target_fields if field in attrs]
        if len(supplied) > 1:
            raise serializers.ValidationError(
                "Specify at most one commitment target ID."
            )
        return attrs


class CommitmentCreateRequestSerializer(CommitmentChangesRequestSerializer):
    aggregation_type = serializers.ChoiceField(
        choices=COMMITMENT_AGGREGATION_CHOICES
    )
    target_value = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        expected = f"{attrs['aggregation_type']}_id"
        target_fields = (
            "project_id",
            "subproject_id",
            "context_id",
            "tag_id",
        )
        supplied = [field for field in target_fields if field in attrs]
        if supplied != [expected]:
            raise serializers.ValidationError(
                f"Exactly one target ID is required and it must be '{expected}'."
            )
        return attrs


class CommitmentRestartRequestSerializer(serializers.Serializer):
    keep_balance = serializers.BooleanField()
    changes = CommitmentChangesRequestSerializer(required=False, default=dict)


class CommitmentAdjustmentRequestSerializer(serializers.Serializer):
    amount = serializers.IntegerField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class CommitmentPeriodsQuerySerializer(serializers.Serializer):
    generation = serializers.IntegerField(required=False, min_value=1)
    limit = serializers.IntegerField(
        required=False, default=100, min_value=1, max_value=500
    )
    offset = serializers.IntegerField(required=False, default=0, min_value=0)


class CommitmentListQuerySerializer(serializers.Serializer):
    include = serializers.ChoiceField(required=False, choices=("streak",))
    applies_to = serializers.RegexField(
        required=False,
        regex=r"^(project|subproject|context|tag):[1-9][0-9]*$",
        help_text=(
            "Return commitments relevant to one owned resource, formatted as "
            "project:<id>, subproject:<id>, context:<id>, or tag:<id>."
        ),
    )

    def validate_applies_to(self, value):
        kind, raw_id = value.split(":", 1)
        return kind, int(raw_id)


class CommitmentTargetSerializer(serializers.Serializer):
    kind = serializers.CharField()
    id = serializers.IntegerField()
    name = serializers.CharField()


class CommitmentFiltersSerializer(serializers.Serializer):
    include_project_ids = serializers.ListField(child=serializers.IntegerField())
    exclude_project_ids = serializers.ListField(child=serializers.IntegerField())
    include_subproject_ids = serializers.ListField(child=serializers.IntegerField())
    exclude_subproject_ids = serializers.ListField(child=serializers.IntegerField())
    include_context_ids = serializers.ListField(child=serializers.IntegerField())
    exclude_context_ids = serializers.ListField(child=serializers.IntegerField())
    include_tag_ids = serializers.ListField(child=serializers.IntegerField())
    exclude_tag_ids = serializers.ListField(child=serializers.IntegerField())


class CommitmentCurrentPeriodSerializer(serializers.Serializer):
    start = UTCDateTimeField()
    end = UTCDateTimeField()
    accrued = serializers.FloatField()
    target = serializers.FloatField()
    met = serializers.BooleanField()
    percentage = serializers.FloatField(allow_null=True)
    status = serializers.CharField(allow_null=True)


class CommitmentPendingRevisionSerializer(serializers.Serializer):
    effective_from = UTCDateTimeField()
    changes = serializers.DictField()


class CommitmentResourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    version = serializers.IntegerField()
    active = serializers.BooleanField()
    aggregation_type = serializers.ChoiceField(
        choices=COMMITMENT_AGGREGATION_CHOICES
    )
    target = CommitmentTargetSerializer()
    commitment_type = serializers.ChoiceField(choices=COMMITMENT_TYPE_CHOICES)
    period = serializers.ChoiceField(choices=COMMITMENT_PERIOD_CHOICES)
    start_date = serializers.DateField()
    timezone = serializers.CharField()
    generation = serializers.IntegerField()
    target_value = serializers.FloatField()
    banking_enabled = serializers.BooleanField()
    max_balance = serializers.FloatField()
    min_balance = serializers.FloatField()
    balance = serializers.FloatField()
    current_surplus = serializers.FloatField()
    filters = CommitmentFiltersSerializer()
    current_period = CommitmentCurrentPeriodSerializer()
    pending_revision = CommitmentPendingRevisionSerializer(allow_null=True)
    ledger_start_at = UTCDateTimeField()
    # Present on detail responses and list responses with ?include=streak.
    streak = serializers.DictField(required=False)


class CommitmentListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    commitments = CommitmentResourceSerializer(many=True)


class CommitmentAdjustmentResponseSerializer(serializers.Serializer):
    seq = serializers.IntegerField()
    amount = serializers.IntegerField()
    effective_at = UTCDateTimeField()
    reason = serializers.CharField()
    balance = serializers.FloatField()


class CommitmentPeriodSerializer(serializers.Serializer):
    generation = serializers.IntegerField()
    period_start = UTCDateTimeField()
    period_end = UTCDateTimeField()
    accrued = serializers.FloatField()
    session_count = serializers.IntegerField()
    carryover_in = serializers.FloatField()
    balance_out = serializers.FloatField()
    closed_at = UTCDateTimeField()
    revision_id = serializers.IntegerField()


class CommitmentPeriodListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    total = serializers.IntegerField()
    periods = CommitmentPeriodSerializer(many=True)


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
    session_count = serializers.IntegerField()
    total_minutes = serializers.SerializerMethodField()
    avg_session_minutes = serializers.SerializerMethodField()

    def get_total_minutes(self, context) -> float:
        return round(context.total_minutes, 2)

    def get_avg_session_minutes(self, context) -> float:
        if not context.session_count:
            return 0.0
        return round(context.total_minutes / context.session_count, 2)


class TagResourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    color = serializers.CharField(allow_null=True)
    project_count = serializers.IntegerField()
    session_count = serializers.IntegerField()
    total_minutes = serializers.SerializerMethodField()
    avg_session_minutes = serializers.SerializerMethodField()

    def get_total_minutes(self, tag) -> float:
        return round(tag.total_minutes, 2)

    def get_avg_session_minutes(self, tag) -> float:
        if not tag.session_count:
            return 0.0
        return round(tag.total_minutes / tag.session_count, 2)


class ContextListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    contexts = ContextResourceSerializer(many=True)


class TagListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    tags = TagResourceSerializer(many=True)


class SubprojectResourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    # Always present in API responses. Keep it optional in the generated type
    # so existing callers that construct Subproject fixtures remain compatible.
    version = serializers.IntegerField(required=False)
    name = serializers.CharField()
    description = serializers.SerializerMethodField()
    project_id = serializers.IntegerField(source="parent_project_id")
    start_date = serializers.SerializerMethodField()
    last_activity = serializers.SerializerMethodField()
    total_minutes = serializers.SerializerMethodField()
    session_count = serializers.IntegerField(source="completed_session_count")

    @extend_schema_field(serializers.CharField())
    def get_description(self, subproject):
        return subproject.description or ""

    @extend_schema_field(serializers.DateField())
    def get_start_date(self, subproject):
        return _local_date(subproject.start_date)

    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_last_activity(self, subproject):
        return _local_date(subproject.derived_last_updated)

    @extend_schema_field(serializers.FloatField())
    def get_total_minutes(self, subproject):
        return round(subproject.derived_total_time, 2)


class ProjectResourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    # Always present in API responses. Keep it optional in the generated type
    # so adding optimistic concurrency remains backward compatible for callers.
    version = serializers.IntegerField(required=False)
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
    celebration = serializers.SerializerMethodField(required=False)

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

    @extend_schema_field(CelebrationSerializer(allow_null=True))
    def get_celebration(self, project):
        return getattr(project, "celebration", None)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not hasattr(instance, "celebration"):
            data.pop("celebration", None)
        return data


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
    related = serializers.BooleanField(
        required=False,
        help_text=(
            "With search, also include projects that match it by meaning (their "
            "name, subprojects, description or session notes). Needs AI features "
            "and an OpenAI key on the account; otherwise ignored."
        ),
    )
    similarity = similarity_field()
    context_ids = serializers.CharField(required=False)
    tag_ids = serializers.CharField(required=False)
    exclude_project_ids = serializers.CharField(required=False)
    start_date = serializers.DateField(
        required=False,
        help_text="Earliest project start date (inclusive).",
    )
    end_date = serializers.DateField(
        required=False,
        help_text="Latest project start date (inclusive).",
    )
    limit = serializers.IntegerField(
        required=False, default=100, min_value=1, max_value=500
    )
    offset = serializers.IntegerField(required=False, default=0, min_value=0)
    ordering = serializers.ChoiceField(
        required=False,
        default="name",
        choices=("name", "id", "last_activity"),
        help_text=(
            "name (default), id, or last_activity (most recently active first)."
        ),
    )

    def validate(self, attrs):
        if (
            attrs.get("start_date") is not None
            and attrs.get("end_date") is not None
            and attrs["end_date"] < attrs["start_date"]
        ):
            raise serializers.ValidationError(
                {"end_date": ["End date must be on or after start date."]}
            )
        return attrs


class ProjectRelatedSummaryQuerySerializer(ProjectListQuerySerializer):
    """Project list filters without result paging or ordering controls."""

    related = serializers.BooleanField(
        required=False,
        help_text=(
            "Accepted for project-list query parity; this summary always describes "
            "related-only matches."
        ),
    )
    similarity = similarity_field(
        help_text=(
            "Cutoff whose related-only count is returned in count. Defaults to the "
            "account setting."
        )
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ("limit", "offset", "ordering"):
            self.fields.pop(field_name)


class ProjectListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    total = serializers.IntegerField()
    projects = ProjectResourceSerializer(many=True)


class SubprojectCreateRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, allow_blank=False)
    description = serializers.CharField(required=False, allow_blank=True)
    start_date = serializers.DateField(required=False)


class SubprojectPatchRequestSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, max_length=255, allow_blank=False)
    description = serializers.CharField(required=False, allow_blank=True)
    start_date = serializers.DateField(required=False)


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
    default_chart_start_date = serializers.DateField()
    default_chart_end_date = serializers.DateField()
    openai_key_configured = serializers.BooleanField()


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
    weekday = serializers.IntegerField(required=False, min_value=0, max_value=6)
    hour = serializers.IntegerField(required=False, min_value=0, max_value=23)
    average_hours = serializers.FloatField(required=False, min_value=0)


class ChartTallyRowSerializer(serializers.Serializer):
    name = serializers.CharField()
    total_time = serializers.FloatField(help_text="Minutes.")


class ChartStatusRowSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=("active", "paused", "complete", "archived")
    )
    count = serializers.IntegerField()
    total_time = serializers.FloatField(help_text="Minutes.")


class ChartBubbleRowSerializer(serializers.Serializer):
    name = serializers.CharField()
    tag_id = serializers.IntegerField()
    total_time = serializers.FloatField(help_text="Minutes.")
    project_count = serializers.IntegerField()
    color = serializers.CharField(allow_null=True)


class ChartScatterRowSerializer(serializers.Serializer):
    x = serializers.DateTimeField(help_text="Session end instant.")
    y = serializers.FloatField(help_text="Session duration in hours.")
    series = serializers.CharField()


class ChartDailySeriesRowSerializer(serializers.Serializer):
    date = serializers.DateField()
    series = serializers.CharField()
    hours = serializers.FloatField()


class ChartDailyTotalRowSerializer(serializers.Serializer):
    date = serializers.DateField()
    hours = serializers.FloatField()


class ChartIntervalRowSerializer(serializers.Serializer):
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()


class ChartHeatmapCellSerializer(serializers.Serializer):
    weekday = serializers.IntegerField(min_value=0, max_value=6)
    hour = serializers.IntegerField(min_value=0, max_value=23)
    average_hours = serializers.FloatField(min_value=0)


class ChartHistogramRowSerializer(serializers.Serializer):
    label = serializers.CharField()
    count = serializers.IntegerField()


class ChartWordRowSerializer(serializers.Serializer):
    text = serializers.CharField()
    weight = serializers.IntegerField()


class ChartRadarRowSerializer(serializers.Serializer):
    name = serializers.CharField()
    total_time = serializers.FloatField(help_text="Minutes.")
    session_count = serializers.IntegerField()
    subproject_count = serializers.IntegerField()
    days_since_update = serializers.IntegerField()
    status = serializers.ChoiceField(
        choices=("active", "paused", "complete", "archived")
    )


class ChartHierarchySubprojectSerializer(serializers.Serializer):
    name = serializers.CharField()
    subproject_id = serializers.IntegerField()
    total_time = serializers.FloatField(help_text="Minutes.")


class ChartHierarchyProjectSerializer(serializers.Serializer):
    name = serializers.CharField()
    project_id = serializers.IntegerField()
    total_time = serializers.FloatField(help_text="Minutes.")
    children = ChartHierarchySubprojectSerializer(many=True)


class ChartHierarchyContextSerializer(serializers.Serializer):
    name = serializers.CharField()
    children = ChartHierarchyProjectSerializer(many=True)


class ChartHierarchyResponseSerializer(serializers.Serializer):
    name = serializers.CharField()
    children = ChartHierarchyContextSerializer(many=True)


class PreferenceContextSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    color = serializers.CharField(allow_null=True)


class BackgroundSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=("upload", "bing", "apod", "none"))
    image_url = serializers.CharField(allow_null=True)
    video_url = serializers.CharField(allow_null=True)
    title = serializers.CharField(allow_null=True)
    description = serializers.CharField(allow_null=True)
    copyright = serializers.CharField(allow_null=True)
    source_url = serializers.CharField(allow_null=True)


class ConfiguredApiKeysSerializer(serializers.Serializer):
    gemini = serializers.BooleanField()
    openai = serializers.BooleanField()
    openai_chatgpt = serializers.BooleanField()
    claude = serializers.BooleanField()


class PreferencesRequestSerializer(serializers.Serializer):
    timezone = serializers.CharField(required=False, max_length=64)
    default_filter_value = serializers.IntegerField(required=False, min_value=1, max_value=1000)
    default_filter_unit = serializers.ChoiceField(
        required=False,
        choices=(
            "days", "weeks", "months", "years", "month_to_date",
            "quarter_to_date", "year_to_date",
        ),
    )
    insights_default_filter_value = serializers.IntegerField(
        required=False, min_value=1, max_value=1000
    )
    insights_default_filter_unit = serializers.ChoiceField(
        required=False,
        choices=(
            "days", "weeks", "months", "years", "month_to_date",
            "quarter_to_date", "year_to_date",
        ),
    )
    default_chart_project_count = serializers.IntegerField(
        required=False, min_value=1, max_value=100
    )
    background_dimming = serializers.IntegerField(required=False, min_value=0, max_value=85)
    automatic_background = serializers.BooleanField(required=False)
    bing_background = serializers.BooleanField(required=False)
    nasa_apod_background = serializers.BooleanField(required=False)
    luna_recommendation_effort = serializers.ChoiceField(
        required=False, choices=("low", "medium", "high", "xhigh", "max")
    )
    ai_features_enabled = serializers.BooleanField(required=False)
    related_similarity = similarity_field(allow_null=True)
    active_context_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate_background_dimming(self, value):
        if value % 5:
            raise serializers.ValidationError("Use increments of 5.")
        return value

    def validate_timezone(self, value):
        from users.models import validate_iana_timezone

        try:
            validate_iana_timezone(value)
        except Exception as exc:
            raise serializers.ValidationError("Enter a valid IANA timezone.") from exc
        return value

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide at least one preference.")
        if attrs.get("bing_background") and attrs.get("nasa_apod_background"):
            raise serializers.ValidationError(
                "Bing and NASA APOD backgrounds cannot both be enabled."
            )
        return attrs


class PreferencesResponseSerializer(PreferencesRequestSerializer):
    timezone = serializers.CharField()
    default_filter_value = serializers.IntegerField()
    default_filter_unit = serializers.CharField()
    insights_default_filter_value = serializers.IntegerField()
    insights_default_filter_unit = serializers.CharField()
    default_chart_project_count = serializers.IntegerField()
    background_dimming = serializers.IntegerField()
    automatic_background = serializers.BooleanField()
    bing_background = serializers.BooleanField()
    nasa_apod_background = serializers.BooleanField()
    luna_recommendation_effort = serializers.CharField()
    ai_features_enabled = serializers.BooleanField()
    related_similarity = serializers.FloatField(allow_null=True)
    related_similarity_default = serializers.FloatField()
    related_similarity_min = serializers.FloatField()
    related_similarity_max = serializers.FloatField()
    active_context_id = serializers.IntegerField(allow_null=True)
    insights_access_enabled = serializers.BooleanField()
    avatar_url = serializers.CharField()
    background = BackgroundSerializer()
    configured_api_keys = ConfiguredApiKeysSerializer()
    openai_source = serializers.ChoiceField(
        choices=("server", "codex", "profile", "codex_with_api_fallback"),
        allow_null=True,
    )
    contexts = PreferenceContextSerializer(many=True)


class TimerSuggestionSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=("recent", "habit", "commitment", "luna"))
    label = serializers.CharField()
    detail = serializers.CharField(allow_blank=True)
    recommendation_detail = serializers.CharField(allow_blank=True, required=False)
    icon = serializers.CharField(allow_blank=True, required=False)
    project = ProjectSummarySerializer(allow_null=True)
    subprojects = ProjectSummarySerializer(many=True)
    metric = serializers.CharField(allow_null=True, required=False)
    recommendation_score = serializers.FloatField(allow_null=True, required=False)
    no_activity = serializers.BooleanField(required=False)


class TimerSuggestionGroupsSerializer(serializers.Serializer):
    commitments = TimerSuggestionSerializer(many=True)
    habits = TimerSuggestionSerializer(many=True)
    recent = TimerSuggestionSerializer(many=True)


class LunaRecommendationsSerializer(serializers.Serializer):
    suggestions = TimerSuggestionSerializer(many=True)
    advice_status = serializers.CharField()


class LunaRefreshRequestSerializer(serializers.Serializer):
    luna_effort = serializers.ChoiceField(
        required=False, choices=("low", "medium", "high", "xhigh", "max")
    )


class LunaRefreshResponseSerializer(serializers.Serializer):
    refreshed = serializers.BooleanField()
    luna_recommendation_effort = serializers.CharField()


class RecommendationUsageRequestSerializer(serializers.Serializer):
    days = serializers.IntegerField(required=False, default=7, min_value=1, max_value=90)


class RecommendationUsageSummarySerializer(serializers.Serializer):
    provider = serializers.CharField()
    model = serializers.CharField(allow_null=True)
    effort = serializers.CharField(allow_null=True)
    auth_route = serializers.CharField(allow_null=True)
    calls = serializers.IntegerField()
    failures = serializers.IntegerField()
    known_usage = serializers.IntegerField()
    known_cost = serializers.IntegerField()
    input_total = serializers.IntegerField(allow_null=True)
    cached_total = serializers.IntegerField(allow_null=True)
    output_total = serializers.IntegerField(allow_null=True)
    reasoning_total = serializers.IntegerField(allow_null=True)
    cost_total = serializers.DecimalField(max_digits=16, decimal_places=8, allow_null=True)
    average_ms = serializers.FloatField(allow_null=True)


class RecommendationCacheHitSerializer(serializers.Serializer):
    provider = serializers.CharField()
    count = serializers.IntegerField()


class RecommendationUsageResponseSerializer(serializers.Serializer):
    days = serializers.IntegerField()
    summary = RecommendationUsageSummarySerializer(many=True)
    cache_hits = RecommendationCacheHitSerializer(many=True)


class TimelineTickSerializer(serializers.Serializer):
    label = serializers.CharField()
    x_pct = serializers.FloatField()
    minor = serializers.BooleanField()


class TimelineGapSerializer(serializers.Serializer):
    minutes = serializers.IntegerField()
    label = serializers.CharField()
    start_pct = serializers.FloatField()
    width_pct = serializers.FloatField()


class TimelineBlockSerializer(serializers.Serializer):
    session_id = serializers.IntegerField()
    is_live = serializers.BooleanField()
    start = UTCDateTimeField()
    end = UTCDateTimeField(allow_null=True)
    minutes = serializers.FloatField()
    duration_label = serializers.CharField()
    label = serializers.CharField(allow_blank=True)
    note_html = serializers.CharField()
    start_pct = serializers.FloatField()
    end_pct = serializers.FloatField()
    width_pct = serializers.FloatField()


class TimelineLaneSerializer(serializers.Serializer):
    project = ProjectSummarySerializer()
    colour = serializers.CharField()
    total_minutes = serializers.FloatField()
    live_minutes = serializers.FloatField()
    total_label = serializers.CharField(allow_null=True)
    live_label = serializers.CharField(allow_null=True)
    blocks = TimelineBlockSerializer(many=True)


class TimelineResponseSerializer(serializers.Serializer):
    range_key = serializers.CharField()
    range_title = serializers.CharField()
    is_multi_day = serializers.BooleanField()
    tracked_minutes = serializers.FloatField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    window_start = UTCDateTimeField()
    window_end = UTCDateTimeField()
    window_start_hour = serializers.IntegerField(allow_null=True)
    window_end_hour = serializers.IntegerField(allow_null=True)
    ticks = TimelineTickSerializer(many=True)
    grid_pct = serializers.FloatField()
    lanes = TimelineLaneSerializer(many=True)
    gaps = TimelineGapSerializer(many=True)
    now_pct = serializers.FloatField(allow_null=True)
    now_label = serializers.CharField(allow_null=True)


class TimelineQuerySerializer(serializers.Serializer):
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    context = serializers.CharField(required=False, allow_blank=False)

    def validate(self, attrs):
        if ("start" in attrs) != ("end" in attrs):
            raise serializers.ValidationError("Provide start and end together.")
        if attrs.get("start") and attrs["start"] > attrs["end"]:
            raise serializers.ValidationError("start must be on or before end.")
        return attrs


class DashboardActivityDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    active = serializers.BooleanField()
    weekday = serializers.IntegerField(min_value=0, max_value=6)


class DashboardStreakSerializer(serializers.Serializer):
    current_streak = serializers.IntegerField()
    recent_days = DashboardActivityDaySerializer(many=True)


class DashboardQuickStartSerializer(serializers.Serializer):
    project = ProjectSummarySerializer()
    subprojects = ProjectSummarySerializer(many=True)
    label = serializers.CharField()


class DashboardRecentDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    total_minutes = serializers.FloatField()
    sessions = SessionResourceSerializer(many=True)


class DashboardCommitmentProgressSerializer(serializers.Serializer):
    actual = serializers.FloatField()
    target = serializers.FloatField()
    percentage = serializers.FloatField()
    balance = serializers.FloatField()
    current_surplus = serializers.FloatField()
    status = serializers.CharField()
    period_start = UTCDateTimeField()
    effective_period_start = UTCDateTimeField()
    period_end = UTCDateTimeField()
    commitment_type = serializers.CharField()
    period = serializers.CharField()


class DashboardCommitmentPeriodSerializer(serializers.Serializer):
    period_start = UTCDateTimeField()
    effective_period_start = UTCDateTimeField()
    period_end = UTCDateTimeField()
    actual = serializers.FloatField()
    target = serializers.FloatField()
    is_current = serializers.BooleanField()
    met = serializers.BooleanField()
    saved_by_bank = serializers.BooleanField()


class DashboardCommitmentStreakSerializer(serializers.Serializer):
    current_streak = serializers.IntegerField()
    periods = DashboardCommitmentPeriodSerializer(many=True)


class DashboardCommitmentSerializer(serializers.Serializer):
    commitment = CommitmentResourceSerializer()
    progress = DashboardCommitmentProgressSerializer()
    streak = DashboardCommitmentStreakSerializer()


class DashboardResponseSerializer(serializers.Serializer):
    today_total = serializers.FloatField()
    week_total = serializers.FloatField()
    active_timers_count = serializers.IntegerField()
    daily_streak = DashboardStreakSerializer()
    active_timers = SessionResourceSerializer(many=True)
    quick_starts = DashboardQuickStartSerializer(many=True)
    recent_sessions = DashboardRecentDaySerializer(many=True)
    commitments = DashboardCommitmentSerializer(many=True)
    timeline = TimelineResponseSerializer()
