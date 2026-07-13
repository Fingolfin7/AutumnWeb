import json
from core.forms import *
from core.utils import *
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def ChartsView(request):
    # Preserve multi-select tags across reloads (?tags=1&tags=2)
    selected_tags = request.GET.getlist("tags")
    default_start_date, default_end_date = (
        request.user.profile.default_filter_date_range()
    )

    search_form = SearchProjectForm(
        initial={
            "project_name": request.GET.get("project_name"),
            "start_date": request.GET.get("start_date") or default_start_date,
            "end_date": request.GET.get("end_date") or default_end_date,
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
        "default_chart_project_count": request.user.profile.default_chart_project_count,
        "exclude_project_meta_json": json.dumps(build_exclude_project_meta(request.user)),
    }
    return render(request, "core/charts.html", context)
