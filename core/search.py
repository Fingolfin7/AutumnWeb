"""Shared search semantics for pages that browse tracked work."""

from django.db.models import Exists, OuterRef, Q

from core.models import SessionSubproject, Sessions, SubProjects


def search_projects(projects, term):
    """Find projects with a matching name, child name, or session note."""
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
        | Q(search_subproject=True)
        | Q(search_note=True)
    )


def search_sessions(sessions, term):
    """Find sessions by project, assigned subproject, or their own note."""
    term = (term or "").strip()
    if not term:
        return sessions

    matching_subprojects = SessionSubproject.objects.filter(
        session_id=OuterRef("pk"),
        subproject__user_id=OuterRef("user_id"),
        subproject__name__icontains=term,
    )
    return sessions.alias(
        search_subproject=Exists(matching_subprojects)
    ).filter(
        Q(project__name__icontains=term)
        | Q(search_subproject=True)
        | Q(note__icontains=term)
    )
