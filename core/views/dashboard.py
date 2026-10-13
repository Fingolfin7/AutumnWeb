from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.generic import TemplateView

from core.services.dashboard import (
    DEFAULT_RANGE,
    build_dashboard,
    build_dashboard_timeline,
)


TIMELINE_FRAGMENT_TEMPLATE = "core/partials/day_timeline.html"


@login_required
def timeline_fragment(request):
    """Render the dashboard timeline for range-tab and live-poll updates."""
    timeline = build_dashboard_timeline(
        request.user, request.GET.get("range", DEFAULT_RANGE)
    )
    response = HttpResponse(
        render_to_string(TIMELINE_FRAGMENT_TEMPLATE, {"timeline": timeline})
    )
    response["Cache-Control"] = "no-store"
    return response


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Autumn"
        context.update(build_dashboard(self.request.user, context=self.request))
        return context
