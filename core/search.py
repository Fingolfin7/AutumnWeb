"""Shared search semantics for pages that browse tracked work."""

import json

from django.db import connections
from django.db.models import Exists, OuterRef, Q
from django.db.models.expressions import RawSQL

from core.models import SessionSubproject, Sessions, SubProjects


def search_projects(projects, term):
    """Find projects by name, description, child name, or session note."""
    term = (term or "").strip()
    if not term:
        return projects

    matching_subprojects = SubProjects.objects.filter(
        parent_project_id=OuterRef("pk"),
        user_id=OuterRef("user_id"),
        name__icontains=term,
    )
    matching_notes = Sessions.objects.filter(
        project_id=OuterRef("pk"),
        user_id=OuterRef("user_id"),
        note__icontains=term,
    )
    return projects.alias(
        search_subproject=Exists(matching_subprojects),
        search_note=Exists(matching_notes),
    ).filter(
        Q(name__icontains=term)
        | Q(description__icontains=term)
        | Q(search_subproject=True)
        | Q(search_note=True)
    )


def search_sessions(sessions, term, *, user=None, related=False, outcome=None):
    """Find sessions by project, assigned subproject, or their own note.

    With ``related`` (and the ``user`` whose OpenAI key pays for the query),
    sessions that match the term by meaning are added; see
    core.services.semantic_search. ``sessions`` must already carry every other
    filter, because related matches are drawn from it. ``outcome`` (a
    RelatedOutcome) records whether they could be added.
    """
    term = (term or "").strip()
    if not term:
        return sessions

    matching_subprojects = SessionSubproject.objects.filter(
        session_id=OuterRef("pk"),
        subproject__user_id=OuterRef("user_id"),
        subproject__name__icontains=term,
    )
    keyword = sessions.alias(
        search_subproject=Exists(matching_subprojects)
    ).filter(
        Q(project__name__icontains=term)
        | Q(search_subproject=True)
        | Q(note__icontains=term)
    )
    if not related:
        return keyword
    if user is None:
        if outcome is not None:
            outcome.requested = True
        return keyword

    from core.services.semantic_search import related_session_ids

    # Counted, not previewed: every match above the cutoff, no cap.
    extra = related_session_ids(user, sessions, keyword, term, limit=None, outcome=outcome)
    return with_extra(sessions, keyword, extra)


def with_extra(queryset, matches, extra_ids):
    """``matches`` plus the rows of ``queryset`` whose ids are ``extra_ids``."""
    if not extra_ids:
        return matches
    return queryset.filter(
        Q(pk__in=matches.order_by().values("pk"))
        | Q(pk__in=id_set(extra_ids, using=queryset.db))
    )


def id_set(ids, *, using="default"):
    """Any number of ids as ONE query parameter, for ``pk__in``.

    Counted related matches are uncapped, and a plain ``pk__in=[...]`` binds
    one variable per id: SQLite rejects a statement past 32,766 of them (999
    on older builds). A JSON array (SQLite) or an array (PostgreSQL) is one.
    """
    ids = [int(pk) for pk in ids]
    vendor = connections[using].vendor
    if vendor == "postgresql":
        return RawSQL("SELECT unnest(%s::bigint[])", [ids])
    if vendor == "sqlite":
        return RawSQL("SELECT value FROM json_each(%s)", [json.dumps(ids)])
    return ids


def is_truthy(value):
    """Checkbox and query-string booleans: on/true/1/yes."""
    return str(value or "").strip().lower() in {"on", "true", "1", "yes"}
