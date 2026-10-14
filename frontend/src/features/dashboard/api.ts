import { useEffect, useRef } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { keys } from "@/api/keys";
import type { components } from "@/api/schema";
import { useActiveContext } from "@/app/context";
import { localDateKey } from "@/lib/format";
import type { Timer } from "@/api/types";

export type Dashboard = components["schemas"]["DashboardResponse"];
export type Timeline = components["schemas"]["TimelineResponse"];
export type TimelineRange = "today" | "d3" | "wk";
export type DashboardCommitment = components["schemas"]["DashboardCommitment"];

export const RANGE_DAYS: Record<TimelineRange, number> = { today: 1, d3: 3, wk: 7 };

export function useDashboard() {
  const { contextIdsParam } = useActiveContext();
  return useQuery({
    queryKey: keys.dashboard(contextIdsParam),
    queryFn: () =>
      unwrap(api.GET("/api/v2/dashboard/", { params: { query: contextIdsParam ? { context: contextIdsParam } : {} } })),
  });
}

/* Day range ending today, in the browser's calendar. */
export function rangeDates(range: TimelineRange, today = new Date()): { start: string; end: string } {
  const start = new Date(today);
  start.setDate(start.getDate() - (RANGE_DAYS[range] - 1));
  return { start: localDateKey(start), end: localDateKey(today) };
}

/* The timeline's shape only changes when sessions do; the live block and the
   now-marker are walked forward locally. A 5-minute backstop catches edits
   made elsewhere (CLI, another device). */
export function useTimeline(range: TimelineRange, initial?: Timeline) {
  const { contextIdsParam } = useActiveContext();
  const { start, end } = rangeDates(range);
  return useQuery({
    queryKey: keys.reports("timeline", { range, start, end, context: contextIdsParam ?? "all" }),
    queryFn: () =>
      unwrap(
        api.GET("/api/v2/reports/timeline/", {
          params: { query: { start, end, ...(contextIdsParam ? { context: contextIdsParam } : {}) } },
        }),
      ),
    initialData: range === "today" ? initial : undefined,
    initialDataUpdatedAt: range === "today" && initial ? Date.now() : undefined,
    placeholderData: keepPreviousData,
    refetchInterval: 5 * 60_000,
  });
}

/* When the set of running timers changes under us (a timer started or
   stopped from the CLI, MCP or another device), the dashboard figures and
   the timeline have a new shape: refresh them. */
export function useRefreshOnRunningChange(timers: Timer[] | undefined) {
  const client = useQueryClient();
  const last = useRef<string | null>(null);
  useEffect(() => {
    if (!timers) return;
    const signature = timers
      .filter((t) => t.id > 0 || t.pending_sync)
      .map((t) => t.id)
      .sort((a, b) => a - b)
      .join(",");
    if (last.current !== null && last.current !== signature) {
      void client.invalidateQueries({ queryKey: ["dashboard"] });
      void client.invalidateQueries({ queryKey: ["reports", "timeline"] });
      void client.invalidateQueries({ queryKey: ["sessions"] });
    }
    last.current = signature;
  }, [timers, client]);
}
