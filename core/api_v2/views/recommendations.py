from datetime import timedelta

from django.db.models import Avg, Count, Q, Sum

from .base import *

from core.api_v2.serializers import (
    LunaRecommendationsSerializer,
    LunaRefreshRequestSerializer,
    LunaRefreshResponseSerializer,
    RecommendationUsageRequestSerializer,
    RecommendationUsageResponseSerializer,
    TimerSuggestionGroupsSerializer,
)
from core.models import RecommendationCache, RecommendationUsage
from core.services import timer_suggestions


def _suggestion_payload(suggestion):
    project = suggestion.get("project")
    return {
        "kind": suggestion["kind"],
        "label": suggestion.get("title", ""),
        "detail": suggestion.get("detail", ""),
        "recommendation_detail": suggestion.get("recommendation_detail", ""),
        "icon": suggestion.get("icon", ""),
        "project": (
            {"id": project.pk, "name": project.name} if project is not None else None
        ),
        "subprojects": [
            {"id": subproject.pk, "name": subproject.name}
            for subproject in suggestion.get("subprojects", [])
        ],
        "metric": suggestion.get("metric"),
        "recommendation_score": suggestion.get("recommendation_score"),
        **(
            {"no_activity": True}
            if suggestion.get("no_activity")
            else {}
        ),
    }


class TimerRecommendationsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "context",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Context ID or 'all'; defaults to all contexts.",
            )
        ],
        responses=TimerSuggestionGroupsSerializer,
    )
    def get(self, request):
        suggestions = timer_suggestions.build_timer_suggestions(
            request.user, _context_request(request)
        )
        return Response(
            {
                group: [_suggestion_payload(item) for item in suggestions[group]]
                for group in ("commitments", "habits", "recent")
            }
        )


class LunaRecommendationsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "context",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Context ID or 'all'; defaults to all contexts.",
            )
        ],
        responses={
            200: LunaRecommendationsSerializer,
            202: LunaRecommendationsSerializer,
        },
    )
    def get(self, request):
        result = timer_suggestions.build_luna_suggestions(
            request.user, _context_request(request)
        )
        payload = {
            "suggestions": [
                _suggestion_payload(item) for item in result.suggestions
            ],
            "advice_status": result.advice_status,
        }
        if result.pending:
            response = Response(payload, status=status.HTTP_202_ACCEPTED)
            response["Retry-After"] = "5"
            response["Cache-Control"] = "no-store"
            return response
        response = Response(payload)
        response["Cache-Control"] = "no-store"
        return response


class LunaRecommendationsRefreshView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=LunaRefreshRequestSerializer,
        responses={200: LunaRefreshResponseSerializer},
    )
    def post(self, request):
        serializer = LunaRefreshRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = request.user.profile
        effort = serializer.validated_data.get("luna_effort")
        if effort is not None:
            if not profile.ai_features_enabled:
                return Response(
                    _envelope(
                        "permission_denied",
                        "AI features are not enabled for this account.",
                    ),
                    status=status.HTTP_403_FORBIDDEN,
                )
            profile.luna_recommendation_effort = effort
            profile.save(update_fields=["luna_recommendation_effort"])
        RecommendationCache.objects.filter(
            user=request.user, provider="luna"
        ).update(expires_at=timezone.now())
        return Response(
            {
                "refreshed": True,
                "luna_recommendation_effort": profile.luna_recommendation_effort,
            }
        )


class RecommendationUsageView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=RecommendationUsageRequestSerializer,
        responses={200: RecommendationUsageResponseSerializer},
    )
    def post(self, request):
        serializer = RecommendationUsageRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        days = serializer.validated_data["days"]
        rows = RecommendationUsage.objects.filter(
            user=request.user,
            created_at__gte=timezone.now() - timedelta(days=days),
        )
        summary = list(
            rows.filter(event="attempt")
            .values("provider", "model", "effort", "auth_route")
            .annotate(
                calls=Count("id"),
                failures=Count("id", filter=Q(success=False)),
                known_usage=Count("input_tokens"),
                known_cost=Count("estimated_cost_usd"),
                input_total=Sum("input_tokens"),
                cached_total=Sum("cached_input_tokens"),
                output_total=Sum("output_tokens"),
                reasoning_total=Sum("reasoning_tokens"),
                cost_total=Sum("estimated_cost_usd"),
                average_ms=Avg("duration_ms"),
            )
            .order_by("provider", "auth_route")
        )
        hits = list(
            rows.filter(event="cache_hit")
            .values("provider")
            .annotate(count=Count("id"))
            .order_by("provider")
        )
        return Response({"days": days, "summary": summary, "cache_hits": hits})
