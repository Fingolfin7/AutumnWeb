import json
import os
from AutumnWeb import settings
from core.forms import *
from core.importer import iter_import
from core.utils import *
from core.models import Context
from django.contrib import messages
from django.http import StreamingHttpResponse, JsonResponse, HttpResponse
from django.utils import timezone
from datetime import datetime, time
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from core.models import Sessions
from core.export2 import build_format2_export


def stream_response(message):
    return f"data: {json.dumps({'message': message})}\n\n"


@login_required
def import_view(request):
    # clear session data
    request.session.delete("file_path")
    request.session.delete("import_data")

    if request.method == "POST":
        form = ImportJSONForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            uploaded_file = request.FILES.get("file")

            if uploaded_file:
                # Save to disk in media/temp
                file_path = os.path.join(
                    settings.MEDIA_ROOT, "temp", uploaded_file.name
                )

                if not os.path.exists(os.path.dirname(file_path)):
                    os.makedirs(os.path.dirname(file_path))

                with open(file_path, "wb+") as destination:
                    for chunk in uploaded_file.chunks():
                        destination.write(chunk)

                # Store file path in session for later processing
                request.session["file_path"] = file_path

            # Exclude 'file' since it's already handled separately
            form_data = form.cleaned_data.copy()
            form_data.pop("file", None)  # Remove the file from cleaned_data

            # ModelChoiceField isn't JSON/session friendly; store just the id.
            ctx = form_data.get("import_context")
            form_data["import_context_id"] = ctx.id if ctx else None
            form_data.pop("import_context", None)

            request.session["import_data"] = form_data
            return JsonResponse({"message": "Form submitted successfully."}, status=200)

        # Return form errors so the streaming JS can surface them as a notification.
        return JsonResponse({"errors": form.errors}, status=400)
    else:
        form = ImportJSONForm(user=request.user)

    context = {
        "title": "Import Data",
        "form": form,
    }

    return render(request, "core/import.html", context)


@csrf_exempt
def import_stream(request):
    def event_stream():
        # Get data from the session.
        file_path = request.session.get("file_path")
        import_data = request.session.get("import_data") or {}
        autumn_import = import_data.get("autumn_import")
        force = import_data.get("force")
        merge = import_data.get("merge")
        tolerance = import_data.get("tolerance")
        verbose = import_data.get("verbose")

        import_context_id = import_data.get("import_context_id")
        import_context_new = (import_data.get("import_context_new") or "").strip()

        user = request.user
        import_into_context = None
        if import_context_new:
            import_into_context, _ = Context.objects.get_or_create(
                user=user, name=import_context_new
            )
        elif import_context_id:
            try:
                import_into_context = Context.objects.get(
                    user=user, id=int(import_context_id)
                )
            except (Context.DoesNotExist, ValueError, TypeError):
                import_into_context = None

        # Clear session data.
        request.session.pop("file_path", None)
        request.session.pop("import_data", None)

        try:
            with open(file_path) as f:
                try:
                    data = json_decompress(f.read())
                except RuntimeError:
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError:
                        os.remove(file_path)
                        yield stream_response("Error: Invalid JSON file")
                        return

            os.remove(file_path)

            # Stream progress live as the importer works through the file.
            for message in iter_import(
                user,
                data,
                force=force,
                merge=merge,
                tolerance=tolerance,
                verbose=verbose,
                autumn_import=autumn_import,
                import_into_context=import_into_context,
            ):
                yield stream_response(message)

        except Exception as e:
            yield stream_response(f"Error: {str(e)}")

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def export_view(request):
    if request.method == "POST":
        form = ExportJSONForm(request.POST, user=request.user)
        if not form.is_valid():
            messages.error(request, "Invalid form data. Please check your inputs.")
            return render(
                request, "core/export.html", {"title": "Export Data", "form": form}
            )

        # pull form data
        project_name = form.cleaned_data["project_name"]
        output_file = form.cleaned_data["output_file"]
        compress = form.cleaned_data["compress"]
        autumn_compatible = form.cleaned_data["autumn_compatible"]
        legacy_format = form.cleaned_data["legacy_format"]
        start_date = form.cleaned_data["start_date"]
        end_date = form.cleaned_data["end_date"]
        context_id = form.cleaned_data.get("context")
        tag_objs = form.cleaned_data.get("tags")

        # default filename
        if not output_file:
            output_file = f"{project_name or 'projects'}.json"
        if not output_file.endswith(".json"):
            output_file += ".json"

        # prepare date-filters
        start_dt = None
        end_dt = None
        if start_date:
            # include all times on start_date
            start_dt = datetime.combine(start_date, time.min)
            start_dt = timezone.make_aware(start_dt)
        if end_date:
            # include up through end of the day
            end_dt = datetime.combine(end_date, time.max)
            end_dt = timezone.make_aware(end_dt)

        # Flat query for every session in the window (and optionally a single project)
        qs = Sessions.objects.filter(end_time__isnull=False, user=request.user)
        if project_name:
            qs = qs.filter(project__name__icontains=project_name)
        if start_date:
            qs = qs.filter(end_time__gte=start_dt)
        if end_date:
            qs = qs.filter(end_time__lte=end_dt)

        # New: context + tags filters
        if context_id:
            try:
                qs = qs.filter(project__context__id=int(context_id))
            except (TypeError, ValueError):
                pass

        if tag_objs:
            tag_ids = [t.id for t in tag_objs]
            if tag_ids:
                qs = qs.filter(project__tags__id__in=tag_ids).distinct()

        exclude_objs = form.cleaned_data.get("exclude_projects")
        if exclude_objs:
            exclude_ids = [p.id for p in exclude_objs]
            qs = qs.exclude(project__id__in=exclude_ids)

        # Avoid N+1 when later reading .project and .subprojects
        qs = qs.select_related("project", "project__context").prefetch_related(
            "subprojects",
            "project__tags",
        )
        # "id" tie-breaker keeps equal end_time rows in a stable order
        # regardless of the query plan (historical order: ascending id).
        qs = qs.order_by("-end_time", "id")

        # build export dict
        export_dict = (
            build_project_json_from_sessions(qs, autumn_compatible)
            if legacy_format
            else build_format2_export(qs)
        )

        # finally serialize
        contents = (
            json.dumps(json_compress(export_dict))
            if compress
            else json.dumps(export_dict, indent=4)
        )
        response = HttpResponse(contents, content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="{output_file}"'
        return response

    # GET
    form = ExportJSONForm(user=request.user)
    return render(request, "core/export.html", {
        "title": "Export Data",
        "form": form,
        "exclude_project_meta_json": json.dumps(build_exclude_project_meta(request.user)),
    })
