from __future__ import annotations
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from core.models import Sessions, Tag, Context
from core.api.helpers import _clean_optional_text, _clean_required_name, _compact, _err, _json_ok, _serialize_context_for_api, _serialize_tag_for_api


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def contexts_list(request):
    """List contexts for the authenticated user.

    Query params:
      - compact=true|false (default true)

    Returns (compact):
      {"count": int, "contexts": [{"id": int, "name": str}]}
    Returns (full):
      {"count": int, "contexts": [{"id", "name", "description", "project_count",
                                   "session_count", "total_minutes", "avg_session_minutes"}]}
    """
    compact = _compact(request)
    if request.method == "POST":
        try:
            name = _clean_required_name(request.data.get("name"), "name")
            description = (
                _clean_optional_text(request.data.get("description"), "description")
                if "description" in request.data
                else None
            )
        except ValueError as exc:
            return _err(str(exc))
        if Context.objects.filter(user=request.user, name__iexact=name).exists():
            return _err("You already have a context with this name.")
        context = Context.objects.create(
            user=request.user, name=name, description=description
        )
        return Response(
            _json_ok(
                {"context": _serialize_context_for_api(context, request.user, compact)},
                compact,
            ),
            status=status.HTTP_201_CREATED,
        )

    qs = request.user.contexts.all().order_by("name")

    if compact:
        payload = [{"id": c.id, "name": c.name} for c in qs]
    else:
        payload = []
        for c in qs:
            project_count = c.projects.count()
            # Get all completed sessions for projects in this context
            sessions = Sessions.objects.filter(
                user=request.user,
                project__context=c,
                is_active=False,
            )
            session_count = sessions.count()
            total_minutes = sum(s.duration or 0 for s in sessions)
            avg_session_minutes = (
                round(total_minutes / session_count, 2) if session_count > 0 else 0.0
            )
            payload.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "description": c.description or "",
                    "project_count": project_count,
                    "session_count": session_count,
                    "total_minutes": round(total_minutes, 2),
                    "avg_session_minutes": avg_session_minutes,
                }
            )

    return Response({"count": len(payload), "contexts": payload})


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def context_detail(request, context_id):
    context = Context.objects.filter(user=request.user, pk=context_id).first()
    if not context:
        return _err("Context not found.", status.HTTP_404_NOT_FOUND)
    if request.method == "DELETE":
        context.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    data = request.data
    if not {"name", "description"}.intersection(data.keys()):
        return _err("Provide at least one of: name, description.")
    try:
        if "name" in data:
            name = _clean_required_name(data.get("name"), "name")
            if Context.objects.filter(user=request.user, name__iexact=name).exclude(
                pk=context.pk
            ).exists():
                return _err("You already have a context with this name.")
            context.name = name
        if "description" in data:
            context.description = _clean_optional_text(
                data.get("description"), "description"
            )
    except ValueError as exc:
        return _err(str(exc))
    context.save()
    compact = _compact(request)
    return Response(
        _json_ok(
            {"context": _serialize_context_for_api(context, request.user, compact)},
            compact,
        )
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def tags_list(request):
    """List tags for the authenticated user.

    Query params:
      - compact=true|false (default true)

    Returns (compact):
      {"count": int, "tags": [{"id": int, "name": str}]}
    Returns (full):
      {"count": int, "tags": [{"id", "name", "color", "project_count",
                              "session_count", "total_minutes", "avg_session_minutes"}]}
    """
    compact = _compact(request)
    if request.method == "POST":
        try:
            name = _clean_required_name(request.data.get("name"), "name")
            color = (
                _clean_optional_text(
                    request.data.get("color"), "color", max_length=20
                )
                if "color" in request.data
                else None
            )
        except ValueError as exc:
            return _err(str(exc))
        if Tag.objects.filter(user=request.user, name__iexact=name).exists():
            return _err("You already have a tag with this name.")
        tag = Tag.objects.create(user=request.user, name=name, color=color)
        return Response(
            _json_ok({"tag": _serialize_tag_for_api(tag, request.user, compact)}, compact),
            status=status.HTTP_201_CREATED,
        )

    qs = request.user.tags.all().order_by("name")

    if compact:
        payload = [{"id": t.id, "name": t.name} for t in qs]
    else:
        payload = []
        for t in qs:
            project_count = t.projects.filter(user=request.user).count()
            # Get all completed sessions for projects with this tag
            sessions = Sessions.objects.filter(
                user=request.user,
                project__tags=t,
                is_active=False,
            )
            session_count = sessions.count()
            total_minutes = sum(s.duration or 0 for s in sessions)
            avg_session_minutes = (
                round(total_minutes / session_count, 2) if session_count > 0 else 0.0
            )
            payload.append(
                {
                    "id": t.id,
                    "name": t.name,
                    "color": t.color or "",
                    "project_count": project_count,
                    "session_count": session_count,
                    "total_minutes": round(total_minutes, 2),
                    "avg_session_minutes": avg_session_minutes,
                }
            )

    return Response({"count": len(payload), "tags": payload})


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def tag_detail(request, tag_id):
    tag = Tag.objects.filter(user=request.user, pk=tag_id).first()
    if not tag:
        return _err("Tag not found.", status.HTTP_404_NOT_FOUND)
    if request.method == "DELETE":
        tag.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    data = request.data
    if not {"name", "color"}.intersection(data.keys()):
        return _err("Provide at least one of: name, color.")
    try:
        if "name" in data:
            name = _clean_required_name(data.get("name"), "name")
            if Tag.objects.filter(user=request.user, name__iexact=name).exclude(
                pk=tag.pk
            ).exists():
                return _err("You already have a tag with this name.")
            tag.name = name
        if "color" in data:
            tag.color = _clean_optional_text(data.get("color"), "color", max_length=20)
    except ValueError as exc:
        return _err(str(exc))
    tag.save()
    compact = _compact(request)
    return Response(
        _json_ok({"tag": _serialize_tag_for_api(tag, request.user, compact)}, compact)
    )
