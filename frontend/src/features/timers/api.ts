import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { ApiError, toApiError } from "@/api/errors";
import { keys } from "@/api/keys";
import { useInvalidate } from "@/api/sync";
import type { Timer } from "@/api/types";
import { csrfToken } from "@/lib/csrf";
import { toOffsetIso } from "@/lib/format";
import { useActiveContext } from "@/app/context";

/* Running timers are the one piece of data other clients (CLI, MCP, another
   device) change under us all the time, so they are polled while the tab is
   visible. The server answers an unchanged list with 304 via ETag, so a quiet
   poll costs almost nothing; hidden tabs don't poll at all, and a refocus,
   reconnect or any local mutation refreshes immediately. */
export const TIMER_POLL_MS = 15_000;

/* Last ETag and body per URL (one per context scope). */
const etagCache = new Map<string, { etag: string; timers: Timer[] }>();

export async function fetchTimers(context?: string): Promise<Timer[]> {
  const url = context ? `/api/v2/timers/?context=${encodeURIComponent(context)}` : "/api/v2/timers/";
  const cached = etagCache.get(url);
  const headers: Record<string, string> = { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" };
  if (cached) headers["If-None-Match"] = cached.etag;
  let response: Response;
  try {
    response = await fetch(url, { credentials: "same-origin", headers, cache: "no-store" });
  } catch (cause) {
    throw new ApiError(0, "network", "Can't reach Autumn. Check your connection.", cause);
  }
  if (response.status === 304 && cached) return cached.timers;
  if (!response.ok) {
    const body = await response.json().catch(() => undefined);
    throw toApiError(response.status, body);
  }
  const data = (await response.json()) as { timers: Timer[] };
  const etag = response.headers.get("ETag");
  if (etag) etagCache.set(url, { etag, timers: data.timers });
  return data.timers;
}

/** Running timers in the active context (the header's switch). */
export function useTimers() {
  const { contextIdsParam } = useActiveContext();
  return useQuery({
    queryKey: [...keys.timers(), contextIdsParam ?? "all"],
    queryFn: () => fetchTimers(contextIdsParam),
    refetchInterval: TIMER_POLL_MS,
    refetchIntervalInBackground: false,
    staleTime: 5_000,
  });
}

/** Re-renders every second while mounted: the clock the live cards read. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const tick = () => {
      if (!document.hidden) setNow(Date.now());
    };
    const id = window.setInterval(tick, intervalMs);
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [intervalMs]);
  return now;
}

export interface StartTimerInput {
  project_id: number;
  subproject_ids?: number[];
  note?: string | null;
  stop_after_minutes?: number;
  /** Shown on the optimistic card until the server answers. */
  optimistic?: { projectName: string; subprojects: { id: number; name: string }[] };
}

/* Client instants and a client uuid make start safe to retry and correct
   even when the server was asleep: the timer starts when you tapped. */
export function useStartTimer() {
  const client = useQueryClient();
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (input: StartTimerInput) => {
      const { optimistic: _optimistic, ...body } = input;
      return unwrap(
        api.POST("/api/v2/timers/", {
          body: { ...body, start: toOffsetIso(new Date()), uuid: crypto.randomUUID() },
        }),
      );
    },
    onMutate: async (input) => {
      await client.cancelQueries({ queryKey: keys.timers() });
      const previous = client.getQueriesData<Timer[]>({ queryKey: keys.timers() });
      if (input.optimistic) {
        const placeholder: Timer = {
          id: -Date.now(),
          uuid: null,
          version: 0,
          project: { id: input.project_id, name: input.optimistic.projectName },
          subproject_allocations: input.optimistic.subprojects.map((sub) => ({
            subproject_id: sub.id,
            name: sub.name,
            allocation_bp: Math.floor(10000 / Math.max(1, input.optimistic!.subprojects.length)),
          })),
          start: new Date().toISOString(),
          end: null,
          active: true,
          auto_stop_at: null,
          duration_minutes: null,
          elapsed_minutes: 0,
          note: input.note ?? null,
        };
        client.setQueriesData<Timer[]>({ queryKey: keys.timers() }, (list) => [...(list ?? []), placeholder]);
      }
      return { previous };
    },
    onError: (_error, _input, context) => {
      for (const [key, data] of context?.previous ?? []) client.setQueryData(key, data);
    },
    onSettled: () => invalidate("timers"),
  });
}

export interface StopTimerInput {
  timer: Timer;
  note?: string | null;
  allocations?: { subproject_id: number; allocation_bp: number }[];
}

export function useStopTimer() {
  const client = useQueryClient();
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ timer, note, allocations }: StopTimerInput) =>
      unwrap(
        api.POST("/api/v2/timers/{session_id}/stop/", {
          params: { path: { session_id: timer.id }, header: { "If-Match": timer.version } },
          body: {
            end: toOffsetIso(new Date()),
            ...(note !== undefined ? { note } : {}),
            ...(allocations ? { subproject_allocations: allocations } : {}),
          },
        }),
      ),
    onMutate: async ({ timer }) => {
      await client.cancelQueries({ queryKey: keys.timers() });
      const previous = client.getQueriesData<Timer[]>({ queryKey: keys.timers() });
      client.setQueriesData<Timer[]>({ queryKey: keys.timers() }, (list) => (list ?? []).filter((t) => t.id !== timer.id));
      return { previous };
    },
    onError: (_error, _input, context) => {
      for (const [key, data] of context?.previous ?? []) client.setQueryData(key, data);
    },
    onSettled: () => invalidate("timers"),
  });
}

export function useRestartTimer() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (timer: Timer) =>
      unwrap(
        api.POST("/api/v2/timers/{session_id}/restart/", {
          params: { path: { session_id: timer.id }, header: { "If-Match": timer.version } },
          body: { start: toOffsetIso(new Date()) },
        }),
      ),
    onSettled: () => invalidate("timers"),
  });
}

export function useDeleteTimer() {
  const client = useQueryClient();
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (timer: Timer) =>
      unwrap(
        api.DELETE("/api/v2/timers/{session_id}", {
          params: { path: { session_id: timer.id }, header: { "If-Match": timer.version } },
        }),
      ),
    onMutate: async (timer) => {
      await client.cancelQueries({ queryKey: keys.timers() });
      const previous = client.getQueriesData<Timer[]>({ queryKey: keys.timers() });
      client.setQueriesData<Timer[]>({ queryKey: keys.timers() }, (list) => (list ?? []).filter((t) => t.id !== timer.id));
      return { previous };
    },
    onError: (_error, _input, context) => {
      for (const [key, data] of context?.previous ?? []) client.setQueryData(key, data);
    },
    onSettled: () => invalidate("timers"),
  });
}

/* Note autosave. Sends If-Match so an edit from the CLI (`autumn note`) in
   the meantime is reported instead of silently overwritten. */
export async function saveTimerNote(timer: Pick<Timer, "id" | "version">, note: string): Promise<Timer> {
  const response = await fetch(`/api/v2/timers/${timer.id}`, {
    method: "PATCH",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken(),
      "X-Requested-With": "XMLHttpRequest",
      "If-Match": String(timer.version),
    },
    body: JSON.stringify({ note }),
  });
  const body = await response.json().catch(() => undefined);
  if (!response.ok) throw toApiError(response.status, body);
  return body as Timer;
}
