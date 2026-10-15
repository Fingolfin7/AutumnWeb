import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { keys } from "@/api/keys";
import type { SimilarityScale } from "./similarity";

export type RelatedSummary = components["schemas"]["RelatedSummary"];

/* How many related matches each Related-slider step would keep for a search,
   with the cutoff in use and the closest match. Keyed under the list it
   summarises, so whatever refreshes that list refreshes this too. The query
   vector is cached server-side, so this costs no second embedding call. */
export function useRelatedSummary(resource: "sessions" | "projects", query: Record<string, unknown>, enabled: boolean) {
  return useQuery({
    queryKey: resource === "sessions" ? keys.sessions({ relatedSummary: query }) : keys.projects({ relatedSummary: query }),
    enabled,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
    queryFn: (): Promise<RelatedSummary> =>
      resource === "sessions"
        ? unwrap(api.GET("/api/v2/sessions/related-summary/", { params: { query: query as never } }))
        : unwrap(api.GET("/api/v2/projects/related-summary/", { params: { query: query as never } })),
  });
}

export function summaryScale(summary: RelatedSummary): SimilarityScale {
  return { floor: summary.floor, ceiling: summary.ceiling, step: summary.step, marks: summary.marks };
}
