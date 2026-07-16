"""Deterministic parameter grids derived from the clone and clone timestamp."""

from datetime import datetime, timedelta

from django.db.models import F

from core.models import Context, Projects, Tag


def frozen_date(meta):
    return datetime.fromisoformat(meta["frozen_at"].replace("Z", "+00:00")).date()


def date_grids(meta):
    end = frozen_date(meta)
    grids = [("all-time", {})]
    for days in (7, 30, 365):
        grids.append(
            (
                "last-%s-days" % days,
                {
                    "start_date": (end - timedelta(days=days - 1)).isoformat(),
                    "end_date": end.isoformat(),
                },
            )
        )
    return grids


def top_projects(user, limit=3):
    return list(
        Projects.objects.filter(user=user)
        .order_by(F("total_time").desc(nulls_last=True), "name")
        .values_list("name", flat=True)[:limit]
    )


def context_names(user, limit=2):
    return list(
        Context.objects.filter(user=user).order_by("name").values_list("name", flat=True)[:limit]
    )


def tag_names(user, limit=2):
    return list(
        Tag.objects.filter(user=user).order_by("name").values_list("name", flat=True)[:limit]
    )


def bounded_and_project_grids(meta, user, project_key="project_name"):
    result = date_grids(meta)
    for name in top_projects(user):
        result.append(("project-" + name, {project_key: name}))
    return result
