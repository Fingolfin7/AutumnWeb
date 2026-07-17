from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.models import Context, Projects, SubProjects, Tag


@dataclass(frozen=True)
class SessionFilterSpec:
    project_ids: frozenset[int] | None = None
    subproject_ids: frozenset[int] | None = None
    context_ids: frozenset[int] | None = None
    tag_ids: frozenset[int] | None = None
    exclude_project_ids: frozenset[int] | None = None
    exclude_subproject_ids: frozenset[int] | None = None
    exclude_tag_ids: frozenset[int] | None = None
    start_date: date | None = None
    end_date: date | None = None
    active: bool | None = None
    note_snippet: str | None = None
    uuid: UUID | None = None

    @classmethod
    def from_query_params(cls, qp, user):
        errors = {}
        id_fields = {
            "project_ids": Projects,
            "subproject_ids": SubProjects,
            "context_ids": Context,
            "tag_ids": Tag,
            "exclude_project_ids": Projects,
            "exclude_subproject_ids": SubProjects,
            "exclude_tag_ids": Tag,
        }
        values = {}

        for field_name, model in id_fields.items():
            raw_value = qp.get(field_name)
            if raw_value in (None, ""):
                values[field_name] = None
                continue
            try:
                parts = raw_value.split(",")
                if any(not part.strip() for part in parts):
                    raise ValueError
                ids = frozenset(int(part.strip()) for part in parts)
                if any(value <= 0 for value in ids):
                    raise ValueError
            except (AttributeError, TypeError, ValueError):
                errors[field_name] = ["Enter comma-separated positive integer IDs."]
                continue

            owned_ids = frozenset(
                model.objects.filter(user=user, id__in=ids).values_list("id", flat=True)
            )
            if owned_ids != ids:
                errors[field_name] = ["One or more IDs do not belong to this user."]
            values[field_name] = ids

        for field_name in ("start_date", "end_date"):
            raw_value = qp.get(field_name)
            if raw_value in (None, ""):
                values[field_name] = None
                continue
            try:
                values[field_name] = datetime.strptime(raw_value, "%Y-%m-%d").date()
            except (TypeError, ValueError):
                errors[field_name] = ["Enter a date in YYYY-MM-DD format."]

        raw_active = qp.get("active")
        if raw_active in (None, ""):
            values["active"] = None
        elif str(raw_active).lower() == "true":
            values["active"] = True
        elif str(raw_active).lower() == "false":
            values["active"] = False
        else:
            errors["active"] = ["Enter true or false."]

        raw_note = qp.get("note_snippet")
        values["note_snippet"] = raw_note if raw_note not in (None, "") else None

        raw_uuid = qp.get("uuid")
        if raw_uuid in (None, ""):
            values["uuid"] = None
        else:
            try:
                values["uuid"] = UUID(str(raw_uuid))
            except (TypeError, ValueError):
                errors["uuid"] = ["Enter a valid UUID."]

        if (
            values.get("start_date") is not None
            and values.get("end_date") is not None
            and values["end_date"] < values["start_date"]
        ):
            errors["end_date"] = ["End date must be on or after start date."]

        if errors:
            raise ValidationError(errors)
        return cls(**values)

    def apply(self, queryset):
        if self.project_ids is not None:
            queryset = queryset.filter(project_id__in=self.project_ids)
        if self.subproject_ids is not None:
            queryset = queryset.filter(subprojects__id__in=self.subproject_ids)
        if self.context_ids is not None:
            queryset = queryset.filter(project__context_id__in=self.context_ids)
        if self.tag_ids is not None:
            queryset = queryset.filter(project__tags__id__in=self.tag_ids)
        if self.exclude_project_ids is not None:
            queryset = queryset.exclude(project_id__in=self.exclude_project_ids)
        if self.exclude_subproject_ids is not None:
            queryset = queryset.exclude(subprojects__id__in=self.exclude_subproject_ids)
        if self.exclude_tag_ids is not None:
            queryset = queryset.exclude(project__tags__id__in=self.exclude_tag_ids)
        if self.active is not None:
            # is_active became a derived property in S12; end_time is the
            # database truth (active == no end_time yet).
            queryset = queryset.filter(end_time__isnull=self.active)
        if self.note_snippet is not None:
            queryset = queryset.filter(note__icontains=self.note_snippet)
        if self.uuid is not None:
            queryset = queryset.filter(uuid=self.uuid)

        current_timezone = timezone.get_current_timezone()
        if self.start_date is not None:
            start = timezone.make_aware(
                datetime.combine(self.start_date, time.min),
                current_timezone,
            )
            queryset = queryset.filter(end_time__gte=start)
        if self.end_date is not None:
            end = timezone.make_aware(
                datetime.combine(self.end_date + timedelta(days=1), time.min),
                current_timezone,
            )
            queryset = queryset.filter(end_time__lt=end)

        if any(
            value is not None
            for value in (
                self.subproject_ids,
                self.tag_ids,
                self.exclude_subproject_ids,
                self.exclude_tag_ids,
            )
        ):
            queryset = queryset.distinct()
        return queryset
