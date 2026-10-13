from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.models import Context, Projects, SubProjects, Tag
from core.search import rank_sessions, search_sessions
from core.services.semantic_search import parse_similarity


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
    search: str | None = None
    related: bool = False
    similarity: float | None = None

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

        parsed_id_fields = {}
        fields_by_model = {}
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

            parsed_id_fields[field_name] = (model, ids)
            fields_by_model.setdefault(model, []).append(field_name)

        # Include and exclude filters often target the same model. Validate
        # all IDs for that model in one ownership query, while retaining the
        # original per-field errors and parsed values.
        owned_ids_by_model = {}
        for model, field_names in fields_by_model.items():
            requested_ids = set().union(
                *(parsed_id_fields[field_name][1] for field_name in field_names)
            )
            owned_ids_by_model[model] = frozenset(
                model.objects.filter(user=user, id__in=requested_ids).values_list(
                    "id", flat=True
                )
            )

        for field_name, (model, ids) in parsed_id_fields.items():
            owned_ids = owned_ids_by_model[model]
            if not ids.issubset(owned_ids):
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

        values["search"] = (qp.get("search") or "").strip() or None
        raw_related = qp.get("related")
        if raw_related in (None, "") or str(raw_related).lower() == "false":
            values["related"] = False
        elif str(raw_related).lower() == "true":
            values["related"] = True
        else:
            errors["related"] = ["Enter true or false."]

        try:
            values["similarity"] = parse_similarity(qp.get("similarity"))
        except (TypeError, ValueError):
            errors["similarity"] = ["Enter a number from 0.25 to 0.60."]

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

    def apply(self, queryset, *, user=None, outcome=None):
        """Narrow ``queryset``; ``user`` is needed only for related=true."""
        queryset = self._filter(queryset)
        # Last: related matches are drawn from what the other filters left.
        if self.search is not None:
            queryset = search_sessions(
                queryset,
                self.search,
                user=user,
                related=self.related,
                cutoff=self.similarity,
                outcome=outcome,
            )
        return queryset

    def rank(self, queryset, *, user=None, outcome=None):
        """The core.search.SessionSearch of these filters and ``search``."""
        return rank_sessions(
            self._filter(queryset),
            self.search,
            user=user,
            related=self.related,
            cutoff=self.similarity,
            outcome=outcome,
        )

    def _filter(self, queryset):
        """Every filter but ``search``."""
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
