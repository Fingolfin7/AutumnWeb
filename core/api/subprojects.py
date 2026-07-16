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
from core.services import (
    CommitmentTargetProtectedError,
    DestructiveMutationService,
    DestructiveOperationError,
)
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
        session_count = sp.sessions.filter(end_time__isnull=False).count()
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
    try:
        DestructiveMutationService.delete_subproject(
            user=request.user,
            project_name=project_name,
            subproject_name=subproject_name,
        )
    except CommitmentTargetProtectedError as exc:
        return Response(
            {"error": str(exc)}, status=status.HTTP_409_CONFLICT
        )
    return Response(status=204)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
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
        merged_subproject = DestructiveMutationService.merge_subprojects(
            user=request.user,
            project_id=project_id,
            name1=subproject1_name,
            name2=subproject2_name,
            new_name=new_subproject_name,
        )
        serializer = SubProjectSerializer(merged_subproject)
        return Response(
            {
                "message": f'Successfully merged "{subproject1_name}" and "{subproject2_name}" into "{new_subproject_name}"',
                "subproject": serializer.data,
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
            {"error": f"An error occurred while merging subprojects: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
