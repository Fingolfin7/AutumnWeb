from __future__ import annotations
import json
from datetime import datetime, time
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from core.models import Sessions, Context
from core.utils import (
    parse_date_or_datetime,
    build_project_json_from_sessions,
    json_compress,
    json_decompress,
)
from core.importer import run_import
from core.services import CommitmentTargetProtectedError
from core.api.helpers import _bool, _coerce_list, _compact, _err, _json_ok


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def export_json_api(request):
    """Export sessions/projects as JSON (API form of the export page).

    Accepts filters via either query params (GET) or JSON body (POST):
      - project_name: str (icontains)
      - start_date: YYYY-MM-DD (inclusive)
      - end_date:   YYYY-MM-DD (inclusive)
      - context: context id
      - tags: list of tag ids (or comma-separated string)
      - compress: bool (wrap with json_compress)
      - autumn_compatible: bool (CLI compatibility format)

    Returns JSON data (not a file download).
    """
    compact = _compact(request)

    # Read from query params for GET, body for POST (but allow either in both)
    qp = getattr(request, "query_params", request.GET)
    data = {}
    try:
        if hasattr(request, "data") and isinstance(request.data, dict):
            data = request.data
    except Exception:
        data = {}

    def _get(key, default=None):
        if key in data and data.get(key) not in (None, ""):
            return data.get(key)
        return qp.get(key, default)

    project_name = (_get("project_name") or _get("project") or "").strip()
    start_date_s = (_get("start_date") or "").strip()
    end_date_s = (_get("end_date") or "").strip()
    context_id = _get("context")
    tag_ids_raw = _get("tags") or _get("tag_ids")

    compress = _bool(_get("compress"), False)
    autumn_compatible = _bool(_get("autumn_compatible"), False)

    # Parse dates (date-only, inclusive like export_view)
    start_dt = None
    end_dt = None
    if start_date_s:
        try:
            d = parse_date_or_datetime(start_date_s)
            if isinstance(d, datetime):
                d = d.date()
            start_dt = timezone.make_aware(datetime.combine(d, time.min))
        except Exception:
            return _err("Invalid start_date; expected YYYY-MM-DD")

    if end_date_s:
        try:
            d = parse_date_or_datetime(end_date_s)
            if isinstance(d, datetime):
                d = d.date()
            end_dt = timezone.make_aware(datetime.combine(d, time.max))
        except Exception:
            return _err("Invalid end_date; expected YYYY-MM-DD")

    qs = Sessions.objects.filter(is_active=False, user=request.user)

    if project_name:
        qs = qs.filter(project__name__icontains=project_name)
    if start_dt is not None:
        qs = qs.filter(end_time__gte=start_dt)
    if end_dt is not None:
        qs = qs.filter(end_time__lte=end_dt)

    if context_id:
        try:
            qs = qs.filter(project__context__id=int(context_id))
        except (TypeError, ValueError):
            # ignore invalid context
            pass

    tag_ids = _coerce_list(tag_ids_raw)
    # Allow comma-separated string, or repeated query params like ?tags=1&tags=2
    if isinstance(tag_ids_raw, str):
        tag_ids = _coerce_list(tag_ids_raw)

    # If query params had repeated tags=, _get() only returns first; handle manually.
    if not tag_ids and hasattr(qp, "getlist"):
        tag_ids = qp.getlist("tags")

    try:
        tag_ids = [int(t) for t in tag_ids if str(t).strip()]
    except ValueError:
        tag_ids = []

    if tag_ids:
        qs = qs.filter(project__tags__id__in=tag_ids).distinct()

    qs = qs.select_related("project", "project__context").prefetch_related(
        "subprojects",
        "project__tags",
    )

    export_dict = build_project_json_from_sessions(qs, autumn_compatible)
    payload = json_compress(export_dict) if compress else export_dict

    # API should return JSON object (not string)
    return Response(payload, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def import_json_api(request):
    """Import project/session JSON produced by :func:`export_json_api`."""
    try:
        body = request.data
    except Exception:
        return _err("Invalid JSON request body.")

    if not isinstance(body, dict):
        return _err("JSON request body must be an object.")

    has_data = "data" in body
    has_compressed = "data_compressed" in body
    if has_data == has_compressed:
        return _err("Provide exactly one of data or data_compressed.")

    if has_compressed:
        compressed = body.get("data_compressed")
        if not isinstance(compressed, (str, dict)):
            return _err("data_compressed must be a compressed JSON string.")
        try:
            compressed_data = json.loads(compressed) if isinstance(compressed, str) else compressed
            zipjson_key = "base64(zip(o))"
            if (
                not isinstance(compressed_data, dict)
                or set(compressed_data) != {zipjson_key}
                or not compressed_data[zipjson_key]
            ):
                raise ValueError
            import_data = json_decompress(compressed_data)
        except Exception:
            return _err("Could not decompress data_compressed.")
    else:
        import_data = body.get("data")

    if not isinstance(import_data, dict):
        return _err("Import data must be an object.")

    tolerance = body.get("tolerance", 2)
    if isinstance(tolerance, bool) or not isinstance(tolerance, int):
        return _err("tolerance must be an integer number of minutes.")
    if tolerance < 0:
        return _err("tolerance must be zero or greater.")

    import_into_context = None
    context_name = body.get("context")
    if context_name is not None:
        if not isinstance(context_name, str):
            return _err("context must be a context name.")
        context_name = context_name.strip()
        if context_name:
            import_into_context = Context.objects.filter(
                user=request.user,
                name__iexact=context_name,
            ).first()
            if import_into_context is None:
                import_into_context = Context.objects.create(
                    user=request.user,
                    name=context_name,
                )

    try:
        summary = run_import(
            request.user,
            import_data,
            force=_bool(body.get("force"), False),
            merge=_bool(body.get("merge"), False),
            tolerance=tolerance,
            autumn_import=_bool(body.get("autumn_import"), False),
            import_into_context=import_into_context,
        )
    except CommitmentTargetProtectedError as exc:
        return Response(
            {"error": str(exc)}, status=status.HTTP_409_CONFLICT
        )
    except Exception as exc:
        return _err(f"Invalid import data: {exc}")

    return Response(_json_ok({"summary": summary}), status=status.HTTP_200_OK)
