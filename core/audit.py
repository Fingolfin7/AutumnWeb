from __future__ import annotations

from django.contrib.auth.models import User

from core.models import Projects, SubProjects


def audit_project_totals_for_user(user: User, log: bool = True) -> tuple[int, int]:
    """Recompute project/subproject total_time values for a single user.

    Returns a tuple of (project_count, subproject_count) audited.
    """
    projects = Projects.objects.filter(user=user)
    project_count = 0
    subproject_count = 0

    for project in projects:
        project.audit_total_time(log=log)
        project_count += 1
        for subproject in SubProjects.objects.filter(parent_project=project, user=user):
            subproject.audit_total_time(log=log)
            subproject_count += 1

    return project_count, subproject_count


def audit_project_totals_all_users(log: bool = False) -> tuple[int, int, int]:
    """Recompute project/subproject total_time values for all users.

    Returns (user_count, project_count, subproject_count).
    """
    user_count = 0
    project_count = 0
    subproject_count = 0

    for user in User.objects.all().iterator():
        user_count += 1
        p_count, sp_count = audit_project_totals_for_user(user, log=log)
        project_count += p_count
        subproject_count += sp_count

    return user_count, project_count, subproject_count
