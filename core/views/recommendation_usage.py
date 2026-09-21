"""Account-only usage review and explicit cache refresh."""
import csv
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.models import RecommendationCache, RecommendationUsage


@login_required
@require_POST
def refresh_recommendations(request):
    # Keep any active lease: clicking twice must not launch duplicate calls.
    RecommendationCache.objects.filter(user=request.user).update(expires_at=timezone.now())
    return redirect("timers")


@login_required
@require_GET
def recommendation_usage(request):
    try:
        days = min(90, max(1, int(request.GET.get("days", "7"))))
    except ValueError:
        days = 7
    rows = RecommendationUsage.objects.filter(user=request.user, created_at__gte=timezone.now() - timedelta(days=days))
    if request.GET.get("format") == "csv":
        fields = ["created_at", "provider", "event", "model", "effort", "auth_route", "success",
                  "error_category", "duration_ms", "input_tokens", "cached_input_tokens", "cache_write_tokens",
                  "output_tokens", "reasoning_tokens", "estimated_cost_usd", "pricing"]
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="recommendation-usage.csv"'
        writer = csv.writer(response)
        writer.writerow(fields)
        for row in rows.order_by("created_at").values_list(*fields).iterator():
            writer.writerow(row)
    else:
        summary = rows.filter(event="attempt").values("provider", "model", "effort", "auth_route").annotate(
            calls=Count("id"), failures=Count("id", filter=Q(success=False)),
            known_usage=Count("input_tokens"), known_cost=Count("estimated_cost_usd"),
            input_total=Sum("input_tokens"), cached_total=Sum("cached_input_tokens"),
            output_total=Sum("output_tokens"), reasoning_total=Sum("reasoning_tokens"),
            cost_total=Sum("estimated_cost_usd"), average_ms=Avg("duration_ms"),
        ).order_by("provider", "auth_route")
        hits = rows.filter(event="cache_hit").values("provider").annotate(count=Count("id")).order_by("provider")
        response = render(request, "core/recommendation_usage.html", {"summary": summary, "hits": hits, "days": days})
    response["Cache-Control"] = "no-store"
    return response
