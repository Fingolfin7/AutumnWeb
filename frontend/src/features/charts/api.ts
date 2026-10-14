import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { ApiError, toApiError } from "@/api/errors";
import { keys } from "@/api/keys";
import type { Preferences } from "@/api/types";
import type { ChartQuery, RelatedState } from "./filters";

export interface ChartResult {
  data: unknown;
  /** X-Autumn-Related of this very response, kept with the payload so a
      cached chart brings back its own state. */
  related: RelatedState;
}

export function parseRelatedHeader(value: string | null): RelatedState {
  return value === "included" || value === "unavailable" ? value : null;
}

/* GET /api/v2/reports/charts/. The schema's chart_type enum lacks the legacy
   kinds (pie, bar, context, status, bubble, treemap, radar) the server still
   answers, and types the context as a number, so the query is cast. */
export async function fetchChart(query: ChartQuery): Promise<ChartResult> {
  let result;
  try {
    result = await api.GET("/api/v2/reports/charts/", { params: { query: query as never } });
  } catch (cause) {
    throw new ApiError(0, "network", "Can't reach Autumn. Check your connection.", cause);
  }
  if (!result.response.ok) throw toApiError(result.response.status, result.error);
  return { data: result.data, related: parseRelatedHeader(result.response.headers.get("X-Autumn-Related")) };
}

/* Reports are cheap to recompute but not free: a payload per query stays
   fresh for a few minutes, so flipping between chart types you have already
   seen is instant. Refresh invalidates the lot. */
export const CHART_STALE = 5 * 60_000;

export function useChartData(query: ChartQuery, enabled: boolean) {
  return useQuery({
    queryKey: keys.reports("charts", query),
    queryFn: () => fetchChart(query),
    enabled,
    staleTime: CHART_STALE,
  });
}

/* Profile defaults the page needs: the default date range, and whether
   meaning-based ("related") search can work at all. */
export function usePreferences() {
  return useQuery({
    queryKey: keys.preferences(),
    queryFn: (): Promise<Preferences> => unwrap(api.GET("/api/v2/me/preferences/")),
    staleTime: 5 * 60_000,
  });
}

/* Same rule as core.services.semantic_search.semantic_search_available. */
export function semanticSearchAvailable(preferences: Preferences | undefined): boolean {
  return !!preferences && preferences.ai_features_enabled && preferences.configured_api_keys.openai;
}
