"""Shared search semantics for pages that browse tracked work."""

from django.db.models import Exists, OuterRef, Q

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


def search_sessions(sessions, term, *, user=None, related=False):
    """Find sessions by project, assigned subproject, or their own note.

    With ``related`` (and the ``user`` whose OpenAI key pays for the query),
    sessions that match the term by meaning are added; see
    core.services.semantic_search. ``sessions`` must already carry every other
    filter, because related matches are drawn from it.
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
    if not (related and user is not None):
        return keyword

    from core.services.semantic_search import INCLUDED_LIMIT, related_session_ids

    extra = related_session_ids(user, sessions, keyword, term, limit=INCLUDED_LIMIT)
    return with_extra(sessions, keyword, extra)


def with_extra(queryset, matches, extra_ids):
    """``matches`` plus the rows of ``queryset`` whose ids are ``extra_ids``."""
    if not extra_ids:
        return matches
    return queryset.filter(
        Q(pk__in=matches.order_by().values("pk")) | Q(pk__in=list(extra_ids))
    )


def is_truthy(value):
    """Checkbox and query-string booleans: on/true/1/yes."""
    return str(value or "").strip().lower() in {"on", "true", "1", "yes"}
