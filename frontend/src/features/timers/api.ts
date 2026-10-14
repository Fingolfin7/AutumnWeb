import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { ApiError, toApiError } from "@/api/errors";
import { keys } from "@/api/keys";
import { useInvalidate } from "@/api/sync";
import type { Timer } from "@/api/types";
import { csrfToken } from "@/lib/csrf";
import { toOffsetIso } from "@/lib/format";
import { cancelStart, enqueueStart, enqueueStop, isNetworkFailure, overlayTimers, type QueuedStart } from "@/lib/offlineQueue";
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
  /* Reminders ride along (and are covered by the ETag), so the cards need no
     request of their own. */
  const url = `/api/v2/timers/?include=reminders${context ? `&context=${encodeURIComponent(context)}` : ""}`;
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
    queryFn: async () => overlayTimers(await fetchTimers(contextIdsParam), pendingTimer),
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
  notify_on_auto_stop?: boolean;
  reminder?: { mode: "after" | "interval" | "at"; amount?: number; unit?: "minutes" | "hours"; at?: string; message?: string };
  /** Shown on the optimistic card until the server answers. */
  optimistic?: { projectName: string; subprojects: { id: number; name: string }[] };
}

/* A timer the server hasn't seen yet, drawn from the offline queue. */
export function pendingTimer(op: QueuedStart): Timer {
  const subs = op.display.subprojects;
  return {
    id: -Date.parse(op.queuedAt) || -1,
    uuid: op.uuid,
    version: 0,
    project: { id: op.body.project_id, name: op.display.projectName },
    subproject_allocations: subs.map((sub) => ({
      subproject_id: sub.id,
      name: sub.name,
      allocation_bp: Math.floor(10000 / Math.max(1, subs.length)),
    })),
    start: op.body.start,
    end: null,
    active: true,
    auto_stop_at:
      typeof op.body.stop_after_minutes === "number"
        ? new Date(Date.parse(op.body.start) + op.body.stop_after_minutes * 60000).toISOString()
        : null,
    duration_minutes: null,
    elapsed_minutes: 0,
    note: (op.body.note as string | null | undefined) ?? null,
    notify_on_auto_stop: op.body.notify_on_auto_stop === true,
    pending_sync: true,
  };
}

const isOffline = (error: unknown) => error instanceof ApiError && isNetworkFailure(error.status);

/* Client instants and a client uuid make start safe to retry and correct
   even when the server was asleep: the timer starts when you tapped. If the
   server can't be reached at all, the start is queued and replays later. */
export function useStartTimer() {
  const client = useQueryClient();
  const invalidate = useInvalidate();
  return useMutation({
    networkMode: "always",
    mutationFn: async (input: StartTimerInput): Promise<Timer> => {
      const { optimistic, ...rest } = input;
      const body = { ...rest, start: toOffsetIso(new Date()), uuid: crypto.randomUUID() };
      try {
        return await unwrap(
          api.POST("/api/v2/timers/", { body }),
        );
      } catch (error) {
        if (!isOffline(error)) throw error;
        const op = enqueueStart({
          uuid: body.uuid,
          body,
          display: optimistic ?? { projectName: "Project", subprojects: [] },
        });
        return pendingTimer(op);
      }
    },
    onMutate: async (input) => {
      await client.cancelQueries({ queryKey: keys.timers() });
      const previous = client.getQueriesData<Timer[]>({ queryKey: keys.timers() });
      const placeholderId = -Date.now();
      if (input.optimistic) {
        const placeholder: Timer = {
          id: placeholderId,
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
          auto_stop_at: input.stop_after_minutes ? new Date(Date.now() + input.stop_after_minutes * 60000).toISOString() : null,
          duration_minutes: null,
          elapsed_minutes: 0,
          note: input.note ?? null,
          notify_on_auto_stop: input.notify_on_auto_stop ?? false,
        };
        client.setQueriesData<Timer[]>({ queryKey: keys.timers() }, (list) => [...(list ?? []), placeholder]);
      }
      return { previous, placeholderId };
    },
    onSuccess: (timer, _input, context) => {
      /* Swap the placeholder for the real (or queued) timer, so an offline
         start keeps its card even though the refetch below can't run. */
      client.setQueriesData<Timer[]>({ queryKey: keys.timers() }, (list) => [
        ...(list ?? []).filter((t) => t.id !== context?.placeholderId && t.id !== timer.id),
        timer,
      ]);
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
  /** ISO instant; defaults to now. */
  end?: string;
}

export function useStopTimer() {
  const client = useQueryClient();
  const invalidate = useInvalidate();
  return useMutation({
    networkMode: "always",
    mutationFn: async ({ timer, note, allocations, end }: StopTimerInput): Promise<Timer> => {
      const at = end ?? toOffsetIso(new Date());
      const queue = (target: { id: number } | { uuid: string }): Timer => {
        enqueueStop({
          target,
          end: at,
          ...(note !== undefined ? { note } : {}),
          ...(allocations ? { subproject_allocations: allocations } : {}),
        });
        return { ...timer, end: at, active: false, pending_sync: true };
      };
      /* Started offline: stop it in the queue, right behind its start. */
      if (timer.pending_sync && timer.uuid) return queue({ uuid: timer.uuid });
      try {
        return await unwrap(
          api.POST("/api/v2/timers/{session_id}/stop/", {
            params: { path: { session_id: timer.id }, header: { "If-Match": timer.version } },
            body: {
              end: at,
              ...(note !== undefined ? { note } : {}),
              ...(allocations ? { subproject_allocations: allocations } : {}),
            },
          }),
        );
      } catch (error) {
        if (!isOffline(error)) throw error;
        return queue({ id: timer.id });
      }
    },
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
    mutationFn: async (timer: Timer) => {
      /* Never reached the server: just forget the queued start. */
      if (timer.pending_sync && timer.uuid) {
        cancelStart(timer.uuid);
        return undefined;
      }
      return unwrap(
        api.DELETE("/api/v2/timers/{session_id}", {
          params: { path: { session_id: timer.id }, header: { "If-Match": timer.version } },
        }),
      );
    },
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
