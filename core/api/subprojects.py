from __future__ import annotations
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from core.models import Projects, SubProjects
from core.serializers import (
    SubProjectSerializer,
)
from django.db import transaction
from core.api.helpers import _compact, _err


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def subprojects_list(request):
    """
    List subprojects for a given project.

    Query params:
      - project (required): project name
      - compact: true/false (default true)

    Returns (compact):
      {"project": str, "subprojects": ["Sub A", "Sub B", ...]}
    Returns (full):
      {"project": str, "project_id": int, "subprojects": [
          {"id", "name", "description", "session_count", "total_minutes"}, ...
      ]}
    """
    project_name = request.query_params.get("project") or request.query_params.get(
        "project_name"
    )
    if not project_name:
        return _err("Missing 'project'")

    project = Projects.objects.filter(name=project_name, user=request.user).first()
    if not project:
        return _err("Project not found", status.HTTP_404_NOT_FOUND)

    subprojects = SubProjects.objects.filter(
        parent_project=project, user=request.user
    ).order_by("name")

    compact = _compact(request)
    if compact:
        return Response(
            {"project": project_name, "subprojects": [s.name for s in subprojects]}
        )

    payload = []
    for sp in subprojects:
        session_count = sp.sessions.filter(is_active=False).count()
        total_minutes = float(sp.total_time or 0.0)
        payload.append(
            {
                "id": sp.id,
                "name": sp.name,
                "description": sp.description or "",
                "session_count": session_count,
                "total_minutes": round(total_minutes, 2),
            }
        )

    return Response(
        {"project": project_name, "project_id": project.id, "subprojects": payload}
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_subproject(request):
    parent_raw = request.data.get("parent_project")
    if not parent_raw:
        return _err("Missing 'parent_project'")

    parent_project = None
    if isinstance(parent_raw, int) or (
        isinstance(parent_raw, str) and parent_raw.isdigit()
    ):
        parent_project = Projects.objects.filter(
            pk=int(parent_raw), user=request.user
        ).first()
    else:
        parent_project = Projects.objects.filter(
            name=str(parent_raw), user=request.user
        ).first()

    if parent_project is None:
        return Response(
            {"error": f"Parent project {parent_raw} does not exist"}, status=400
        )

    payload = request.data.copy()
    payload["parent_project"] = parent_project.pk
    payload["user"] = request.user.pk
    serializer = SubProjectSerializer(data=payload)
    if serializer.is_valid():
        serializer.save(user=request.user, parent_project=parent_project)
        return Response(serializer.data)
    return Response(serializer.errors, status=400)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_subprojects(request, **kwargs):
    project_name = request.query_params.get("project_name") or kwargs.get(
        "project_name"
    )
    subprojects = SubProjects.objects.filter(
        parent_project__name=project_name, user=request.user
    )
    serializer = SubProjectSerializer(subprojects, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search_subprojects(request):
    parent_project = (
        request.query_params.get("project_name")
        or request.query_params.get("project")
    )
    if not parent_project:
        return _err("Missing 'project_name' or 'project'")
    search_term = request.query_params.get("search_term", "")
    subprojects = SubProjects.objects.filter(
        parent_project__name=parent_project,
        name__icontains=search_term,
        user=request.user,
    )
    if not subprojects.exists():
        subprojects = SubProjects.objects.filter(
            parent_project__name=parent_project, user=request.user
        )
    serializer = SubProjectSerializer(subprojects, many=True)
    return Response(serializer.data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_subproject(request, project_name, subproject_name):
    subproject = get_object_or_404(
        SubProjects,
        name=subproject_name,
        parent_project__name=project_name,
        user=request.user,
    )
    subproject.delete()
    return Response(status=204)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def merge_subprojects_api(request):
    """
    API endpoint to merge two subprojects into one new subproject.
    Moves all sessions from both subprojects to the new merged subproject.
    """
    subproject1_name = request.data.get("subproject1")
    subproject2_name = request.data.get("subproject2")
    new_subproject_name = request.data.get("new_subproject_name")
    project_id = request.data.get("project_id")

    if not all([subproject1_name, subproject2_name, new_subproject_name, project_id]):
        return Response(
            {
                "error": "subproject1, subproject2, new_subproject_name, and project_id are required"
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if subproject1_name == subproject2_name:
        return Response(
            {"error": "Cannot merge a subproject with itself"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Get the parent project
        parent_project = get_object_or_404(Projects, id=project_id, user=request.user)

        # Get the subprojects to merge (must belong to the same parent project)
        subproject1 = get_object_or_404(
            SubProjects,
            name=subproject1_name,
            parent_project=parent_project,
            user=request.user,
        )
        subproject2 = get_object_or_404(
            SubProjects,
            name=subproject2_name,
            parent_project=parent_project,
            user=request.user,
        )

        # Check if new subproject name already exists in the same project
        if SubProjects.objects.filter(
            user=request.user, name=new_subproject_name, parent_project=parent_project
        ).exists():
            return Response(
                {
                    "error": f'Subproject with name "{new_subproject_name}" already exists in this project'
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create merged description
        merged_description = (
            f"Merged from '{subproject1.name}' and '{subproject2.name}'\n\n"
        )

        if subproject1.description:
            merged_description += (
                f"--- {subproject1.name} Description ---\n{subproject1.description}\n\n"
            )

        if subproject2.description:
            merged_description += (
                f"--- {subproject2.name} Description ---\n{subproject2.description}\n\n"
            )

        # Remove trailing newlines
        merged_description = merged_description.strip()

        # Create the new merged subproject
        merged_subproject = SubProjects.objects.create(
            user=request.user,
            name=new_subproject_name,
            parent_project=parent_project,
            start_date=min(subproject1.start_date, subproject2.start_date),
            last_updated=max(subproject1.last_updated, subproject2.last_updated),
            total_time=0.0,  # Will be calculated by audit function
            description=merged_description,
        )

        # Move all sessions from both subprojects to the merged subproject
        subproject1_sessions = subproject1.sessions.all()
        subproject2_sessions = subproject2.sessions.all()

        for session in subproject1_sessions:
            session.subprojects.remove(subproject1)
            session.subprojects.add(merged_subproject)

        for session in subproject2_sessions:
            session.subprojects.remove(subproject2)
            session.subprojects.add(merged_subproject)

        # Audit total time for the merged subproject
        merged_subproject.audit_total_time(log=False)

        # Delete the original subprojects
        subproject1.delete()
        subproject2.delete()

        # Serialize and return the merged subproject
        serializer = SubProjectSerializer(merged_subproject)
        return Response(
            {
                "message": f'Successfully merged "{subproject1_name}" and "{subproject2_name}" into "{new_subproject_name}"',
                "subproject": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )

    except Exception as e:
        return Response(
            {"error": f"An error occurred while merging subprojects: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
