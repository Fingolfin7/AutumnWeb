import json
from core.forms import *
from core.utils import *
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def ChartsView(request):
    # Preserve multi-select tags across reloads (?tags=1&tags=2)
    selected_tags = request.GET.getlist("tags")

    search_form = SearchProjectForm(
        initial={
            "project_name": request.GET.get("project_name"),
            "start_date": request.GET.get("start_date"),
            "end_date": request.GET.get("end_date"),
            "chart_type": request.GET.get("chart_type"),
            "context": request.GET.get("context") or "",
            "tags": selected_tags,
            "exclude_projects": request.GET.getlist("exclude_projects"),
        },
        user=request.user,
    )

    context = {
        "title": "Charts",
        "search_form": search_form,
        "exclude_project_meta_json": json.dumps(build_exclude_project_meta(request.user)),
    }
    return render(request, "core/charts.html", context)
