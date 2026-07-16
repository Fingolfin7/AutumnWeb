from __future__ import annotations
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from core.attribution import hierarchy_child_credit
from core.models import Projects, SubProjects, Sessions, status_choices, Context
from core.serializers import (
    ProjectSerializer,
)
from core.services import (
    CommitmentTargetProtectedError,
    DestructiveMutationService,
    DestructiveOperationError,
)
from core.utils import (
    filter_sessions_by_params,
    filter_by_active_context,
)
from django.db import transaction
from django.db.models import Count, DurationField, ExpressionWrapper, F, Sum
from core.api.helpers import _apply_exclude_filters, _apply_tag_filters, _clean_optional_text, _clean_required_name, _coerce_list, _compact, _err, _json_ok, _resolve_context_name, _resolve_tag_names, _serialize_project_grouped, _serialize_project_metadata, in_window


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def projects_list_grouped(request):
    """
    List all projects grouped by status.
    Query: start_date?, end_date?, compact?, context?, tags?
    """
    compact = _compact(request)
    qp = request.query_params
    start = qp.get("start_date")
    end = qp.get("end_date")

    projects_qs = Projects.objects.filter(user=request.user)
    projects_qs = filter_by_active_context(
        projects_qs, request, override_context_id=qp.get("context")
    )
    projects_qs = _apply_tag_filters(
        qp, projects_qs, kind="projects", user=request.user
    )
    projects_qs = _apply_exclude_filters(qp, projects_qs, kind="projects", user=request.user)

    if start or end:
        projects = in_window(projects_qs, start, end)
    else:
        projects = list(projects_qs)

    return Response(_serialize_project_grouped(projects, compact))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def projects_list_flat(request):
    """
    List all projects as a flat (ungrouped) list with optional filters.

    Query params:
      - status: filter by status (active, paused, complete, archived) - optional
      - context: filter by context id or name - optional
      - tags: filter by tag names (comma-separated) - optional
      - search: search by name (icontains) - optional
      - compact: true/false (default true)

    Returns (compact):
      {"count": int, "projects": ["Project A", "Project B", ...]}
    Returns (full):
      {"count": int, "projects": [{"id", "name", "status", "description",
                                   "total_minutes", "session_count", "avg_session_minutes",
                                   "context", "tags"}, ...]}
    """
    compact = _compact(request)
    qp = request.query_params

    projects_qs = Projects.objects.filter(user=request.user)

    # Filter by status
    status_filter = qp.get("status")
    if status_filter:
        projects_qs = projects_qs.filter(status=status_filter.lower())

    # Filter by context (id or name)
    context_filter = qp.get("context")
    if context_filter:
        try:
            context_id = int(context_filter)
            projects_qs = projects_qs.filter(context_id=context_id)
        except (TypeError, ValueError):
            # Treat as context name
            projects_qs = projects_qs.filter(context__name__iexact=context_filter)

    # Filter by tags
    projects_qs = _apply_tag_filters(qp, projects_qs, kind="projects", user=request.user)

    # Exclude projects
    projects_qs = _apply_exclude_filters(qp, projects_qs, kind="projects", user=request.user)

    # Search by name
    search_term = qp.get("search")
    if search_term:
        projects_qs = projects_qs.filter(name__icontains=search_term)

    projects_qs = projects_qs.order_by("name")

    if compact:
        payload = [p.name for p in projects_qs]
    else:
        payload = []
        for p in projects_qs:
            sessions = p.sessions.filter(end_time__isnull=False)
            session_count = sessions.count()
            total_minutes = float(p.total_time or 0.0)
            avg_session_minutes = (
                round(total_minutes / session_count, 2) if session_count > 0 else 0.0
            )
            payload.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "status": p.status,
                    "description": p.description or "",
                    "total_minutes": round(total_minutes, 2),
                    "session_count": session_count,
                    "avg_session_minutes": avg_session_minutes,
                    "context": p.context.name if p.context else None,
                    "tags": [t.name for t in p.tags.all()],
                }
            )

    return Response({"count": len(payload), "projects": payload})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def rename_entity(request):
    """
    Rename a project or subproject.
    JSON:
      - Project: { "type": "project", "project": "Old", "new_name": "New" }
      - Subproject: {
          "type": "subproject",
          "project": "Parent",
          "subproject": "OldSub",
          "new_name": "NewSub"
        }
    """
    ent_type = (request.data.get("type") or "").lower()
    new_name = request.data.get("new_name")
    if ent_type not in ("project", "subproject"):
        return _err("type must be 'project' or 'subproject'")
    if not new_name:
        return _err("Missing 'new_name'")

    if ent_type == "project":
        old = request.data.get("project")
        if not old:
            return _err("Missing 'project'")
        try:
            proj = DestructiveMutationService.rename_project(
                user=request.user, project_name=old, new_name=new_name
            )
        except DestructiveOperationError as exc:
            return _err(str(exc), status.HTTP_409_CONFLICT)
        return Response({"ok": True, "project": proj.name})

    # subproject
    parent = request.data.get("project")
    sub = request.data.get("subproject")
    if not parent or not sub:
        return _err("Missing 'project' or 'subproject'")
    try:
        sp = DestructiveMutationService.rename_subproject(
            user=request.user,
            project_name=parent,
            subproject_name=sub,
            new_name=new_name,
        )
    except DestructiveOperationError as exc:
        return _err(str(exc), status.HTTP_409_CONFLICT)
    return Response({"ok": True, "project": parent, "subproject": sp.name})


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def project_delete_body(request):
    """
    Delete a project via JSON body: { "project": "name" }
    """
    name = request.data.get("project")
    if not name:
        return _err("Missing 'project'")
    try:
        DestructiveMutationService.delete_project(
            user=request.user, project_name=name
        )
    except CommitmentTargetProtectedError as exc:
        return Response(
            {"error": str(exc)}, status=status.HTTP_409_CONFLICT
        )
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mark_project(request):
    """
    Mark a project as active, paused, or complete.
    JSON: { "project": str, "status": "active|paused|complete" }
    """
    project_name = request.data.get("project")
    status_val = (request.data.get("status") or "").lower()
    valid = {k for k, _ in status_choices}
    if status_val not in valid:
        return _err("Invalid status (use: active, paused, complete)")
    proj = get_object_or_404(Projects, name=project_name, user=request.user)
    proj.status = status_val
    proj.save()
    return Response({"ok": True, "project": proj.name, "status": proj.status})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_project(request):
    has_context = "context" in request.data
    has_tags = "tags" in request.data
    context = None
    tags = []
    try:
        if has_context:
            context = _resolve_context_name(request.user, request.data.get("context"))
        if has_tags:
            raw_tags = request.data.get("tags")
            if not isinstance(raw_tags, list):
                raise ValueError("'tags' must be a list of strings.")
            [_clean_required_name(tag, "tag") for tag in _coerce_list(raw_tags)]
    except ValueError as exc:
        return _err(str(exc))

    payload = request.data.copy()
    payload.pop("context", None)
    payload.pop("tags", None)
    payload["user"] = request.user.pk
    serializer = ProjectSerializer(data=payload)
    if serializer.is_valid():
        with transaction.atomic():
            project = serializer.save(user=request.user)
            if has_context:
                project.context = context
                project.save(update_fields=["context"])
            if has_tags:
                tags = _resolve_tag_names(request.user, request.data.get("tags"))
                project.tags.set(tags)

        response_payload = serializer.data
        if has_context or has_tags:
            response_payload["context"] = project.context.name if project.context else None
            response_payload["tags"] = [tag.name for tag in project.tags.all()]
        return Response(response_payload)
    return Response(serializer.errors, status=400)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def update_project_metadata(request):
    """Update a project's description, context, and tags without renaming it."""
    compact = _compact(request)
    data = request.data
    disallowed = {"name", "status"}.intersection(data.keys())
    if disallowed:
        return _err(
            f"Use the dedicated endpoint to change {', '.join(sorted(disallowed))}."
        )
    if "project" not in data:
        return _err("Missing 'project'.")
    if not {"description", "context", "tags"}.intersection(data.keys()):
        return _err("Provide at least one of: description, context, tags.")

    try:
        project_name = _clean_required_name(data.get("project"), "project")
    except ValueError as exc:
        return _err(str(exc))
    project = Projects.objects.filter(
        user=request.user, name__iexact=project_name
    ).first()
    if not project:
        return _err("Project not found.", status.HTTP_404_NOT_FOUND)

    fields_to_save = []
    try:
        if "description" in data:
            project.description = _clean_optional_text(
                data.get("description"), "description", allow_null=True
            )
            fields_to_save.append("description")
        if "context" in data:
            context_value = data.get("context")
            if context_value is None or (
                isinstance(context_value, str) and not context_value.strip()
            ):
                project.context = None
            else:
                project.context = _resolve_context_name(request.user, context_value)
            fields_to_save.append("context")
        if "tags" in data:
            tags = _resolve_tag_names(request.user, data.get("tags"))
        else:
            tags = None
    except ValueError as exc:
        return _err(str(exc))

    if fields_to_save:
        # Projects.save() assigns the user's General context when context is None.
        # Preserve a deliberately cleared context even when this PATCH also updates
        # another metadata field.
        if project.context_id is None:
            Projects.objects.filter(pk=project.pk).update(
                **{field: getattr(project, field) for field in fields_to_save}
            )
        else:
            project.save(update_fields=fields_to_save)
    if tags is not None:
        project.tags.set(tags)
    return Response(_json_ok({"project": _serialize_project_metadata(project, compact)}, compact))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_projects(request):
    qp = request.query_params
    if "start_date" in qp and "end_date" in qp:
        start = qp["start_date"]
        end = qp["end_date"]
        projects_qs = Projects.objects.filter(user=request.user)
        projects_qs = filter_by_active_context(
            projects_qs, request, override_context_id=qp.get("context")
        )
        projects = in_window(projects_qs, start, end)
        serializer = ProjectSerializer(projects, many=True)
        return Response(serializer.data)
    elif "start_date" in qp:
        start = qp["start_date"]
        projects_qs = Projects.objects.filter(user=request.user)
        projects_qs = filter_by_active_context(
            projects_qs, request, override_context_id=qp.get("context")
        )
        projects = in_window(projects_qs, start)
        serializer = ProjectSerializer(projects, many=True)
        return Response(serializer.data)

    projects = Projects.objects.filter(user=request.user)
    projects = filter_by_active_context(
        projects, request, override_context_id=qp.get("context")
    )
    serializer = ProjectSerializer(projects, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def hierarchy_data(request):
    """Return hierarchical Context -> Project -> SubProject structure with times."""

    user = request.user
    contexts = Context.objects.filter(user=user)

    # Apply context filter if provided
    context_id = request.query_params.get("context")
    if context_id:
        contexts = contexts.filter(id=context_id)

    # Apply date filters to sessions for time calculation
    sessions = Sessions.objects.filter(end_time__isnull=False, user=user)
    sessions = filter_sessions_by_params(request, sessions)

    # Re-anchor on session IDs so M2M filters cannot fan out duration sums.
    base_sessions = Sessions.objects.filter(pk__in=sessions.values("pk"))
    duration_expr = ExpressionWrapper(
        F("end_time") - F("start_time"), output_field=DurationField()
    )
    project_times = {
        row["project_id"]: (
            row["total"].total_seconds() / 60.0 if row["total"] else 0.0
        )
        for row in base_sessions.values("project_id").annotate(
            total=Sum(duration_expr)
        )
    }
    subproject_times = {
        row["subproject_id"]: (
            row["total"].total_seconds() / 60.0 if row["total"] else 0.0
        )
        for row in hierarchy_child_credit(base_sessions)
    }

    projects = Projects.objects.filter(user=user)
    if context_id:
        projects = projects.filter(context_id=context_id)
    projects = _apply_tag_filters(
        request.query_params, projects, kind="projects", user=user
    )

    # Apply exclude filter (by ID from web UI)
    exclude_ids = request.query_params.getlist("exclude_projects")
    if exclude_ids:
        projects = projects.exclude(id__in=exclude_ids)

    projects_by_context = {}
    for project in projects.prefetch_related("subprojects"):
        projects_by_context.setdefault(project.context_id, []).append(project)

    hierarchy = {
        "name": "All",
        "children": []
    }

    for ctx in contexts:
        ctx_children = []
        for proj in projects_by_context.get(ctx.id, []):
            proj_time = project_times.get(proj.id, 0)
            if proj_time == 0:
                continue  # Skip projects with no time in range

            proj_children = []
            for sub in proj.subprojects.all():
                sub_time = subproject_times.get(sub.id, 0)
                if sub_time > 0:
                    proj_children.append({
                        "name": sub.name,
                        "subproject_id": sub.id,
                        "total_time": sub_time
                    })

            ctx_children.append({
                "name": proj.name,
                "project_id": proj.id,
                "total_time": proj_time,
                "children": proj_children
            })

        if ctx_children:
            hierarchy["children"].append({
                "name": ctx.name,
                "context_id": ctx.id,
                "children": ctx_children
            })

    return Response(hierarchy)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def projects_with_stats(request):
    """Return projects with additional stats for radar chart."""
    from django.utils import timezone

    user = request.user
    projects = Projects.objects.filter(user=user)

    # Apply context filter if provided
    context_id = request.query_params.get("context")
    if context_id:
        projects = projects.filter(context_id=context_id)

    # Apply tag filters
    projects = _apply_tag_filters(
        request.query_params, projects, kind="projects", user=user
    )

    # Apply exclude filter (by ID from web UI)
    exclude_ids = request.query_params.getlist("exclude_projects")
    if exclude_ids:
        projects = projects.exclude(id__in=exclude_ids)

    projects = projects.annotate(
        aggregated_subproject_count=Count("subprojects", distinct=True)
    ).order_by("name")

    # Filter sessions by date range and other params
    sessions = Sessions.objects.filter(end_time__isnull=False, user=user)
    sessions = filter_sessions_by_params(request, sessions)

    # Re-anchor on session IDs so M2M filters cannot fan out aggregates.
    base_sessions = Sessions.objects.filter(pk__in=sessions.values("pk"))
    duration_expr = ExpressionWrapper(
        F("end_time") - F("start_time"), output_field=DurationField()
    )
    project_stats = {
        row["project_id"]: {
            "total_time": (
                row["total"].total_seconds() / 60.0 if row["total"] else 0.0
            ),
            "session_count": row["session_count"],
        }
        for row in base_sessions.values("project_id").annotate(
            total=Sum(duration_expr), session_count=Count("pk")
        )
    }

    now = timezone.now()
    payload = []
    for p in projects:
        stats = project_stats.get(p.id, {"total_time": 0, "session_count": 0})
        subproject_count = p.aggregated_subproject_count
        days_since_update = (now - p.last_updated).days if p.last_updated else 999

        payload.append({
            "name": p.name,
            "total_time": stats["total_time"],
            "computed_total_time": stats["total_time"],
            "persisted_total_time": p.total_time,
            "session_count": stats["session_count"],
            "subproject_count": subproject_count,
            "days_since_update": days_since_update,
            "status": p.status
        })

    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search_projects(request):
    term = request.query_params.get("search_term", "")
    if "status" in request.query_params:
        st = request.query_params["status"]
        projects = Projects.objects.filter(
            name__icontains=term, status=st, user=request.user
        )
    else:
        projects = Projects.objects.filter(name__icontains=term, user=request.user)
    serializer = ProjectSerializer(projects, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_project(request, project_name):
    project = get_object_or_404(Projects, name=project_name, user=request.user)
    serializer = ProjectSerializer(project)
    return Response(serializer.data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_project(request, project_name):
    try:
        DestructiveMutationService.delete_project(
            user=request.user, project_name=project_name
        )
    except CommitmentTargetProtectedError as exc:
        return Response(
            {"error": str(exc)}, status=status.HTTP_409_CONFLICT
        )
    return Response(status=204)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def merge_projects_api(request):
    """
    API endpoint to merge two projects into one new project.
    Moves all sessions and subprojects from both projects to the new merged project.
    """
    project1_name = request.data.get("project1")
    project2_name = request.data.get("project2")
    new_project_name = request.data.get("new_project_name")

    if not all([project1_name, project2_name, new_project_name]):
        return Response(
            {"error": "project1, project2, and new_project_name are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if project1_name == project2_name:
        return Response(
            {"error": "Cannot merge a project with itself"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        merged_project, _ = DestructiveMutationService.merge_projects(
            user=request.user,
            project1_name=project1_name,
            project2_name=project2_name,
            new_project_name=new_project_name,
        )
        serializer = ProjectSerializer(merged_project)
        return Response(
            {
                "message": f'Successfully merged "{project1_name}" and "{project2_name}" into "{new_project_name}"',
                "project": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )

    except CommitmentTargetProtectedError as exc:
        return Response(
            {"error": str(exc)}, status=status.HTTP_409_CONFLICT
        )
    except DestructiveOperationError as exc:
        return Response(
            {"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        return Response(
            {"error": f"An error occurred while merging projects: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
