import { infiniteQueryOptions, useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { keys } from "@/api/keys";
import { useInvalidate } from "@/api/sync";
import type { Session } from "@/api/types";
import { useToast } from "@/app/toasts";
import { ApiError, errorMessage } from "@/api/errors";
import { enqueue, isNetworkFailure, resolveRefs, type QueuedOp } from "@/lib/offlineQueue";

export interface SessionFilters {
  search?: string;
  ordering?: "best" | "relevance";
  start_date?: string;
  end_date?: string;
  context_ids?: string;
  note_snippet?: string;
  tag_ids?: string;
  project_ids?: string;
  exclude_project_ids?: string;
  /** The Related cutoff; absent = the account's default. */
  similarity?: number;
}

/* Session rows as the list pages need them. note_html is the server's
   sanitised markdown rendering (see components/SessionNote). */
/* pending_sync: logged while Autumn was unreachable; lives in the offline
   queue until it syncs. */
export type SessionRow = Session & { pending_sync?: boolean };

export const SESSION_PAGE = 30;

interface SessionPage {
  sessions: SessionRow[];
  total: number;
}

const cleanFilters = (filters: SessionFilters) =>
  Object.fromEntries(Object.entries(filters).filter(([, value]) => value)) as SessionFilters;

function fetchSessionPage(query: SessionFilters, offset: number, limit: number, includeHtml: boolean, signal: AbortSignal): Promise<SessionPage> {
  return unwrap(api.GET("/api/v2/sessions/", {
    signal,
    params: {
      query: {
        ...query,
        active: false,
        include: includeHtml ? "note,note_html" : "note",
        limit,
        offset,
        ...(query.search ? { related: true, ordering: query.ordering ?? "relevance" } : { ordering: "newest" as const }),
      },
    },
  }));
}

/* One ranked list shared with API v2 and MCP (core.search.rank_sessions):
   with a search term and related=true the server returns direct matches
   newest first, then related matches best first, or all by similarity with
   ordering=best, each tagged by `match`. */
export function sessionListQuery(filters: SessionFilters) {
  const query = cleanFilters(filters);
  return infiniteQueryOptions({
    queryKey: keys.sessions({ list: query }),
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => fetchSessionPage(query, pageParam, SESSION_PAGE, true, signal),
    getNextPageParam: (last, all) => {
      const loaded = all.reduce((sum, page) => sum + page.sessions.length, 0);
      return last.sessions.length && loaded < last.total ? loaded : undefined;
    },
  });
}

export const useSessionList = (filters: SessionFilters) => useInfiniteQuery(sessionListQuery(filters));

/** Reuse the visible pages when exporting, fetching the rest without adding
 * them to the journal. A shift in the list while paging can otherwise look
 * like a successful export with some sessions missing. */
export async function fetchAllSessionPages(filters: SessionFilters, {
  signal,
  loadedPages = [],
  includeHtml = false,
}: { signal: AbortSignal; loadedPages?: readonly SessionPage[]; includeHtml?: boolean }): Promise<SessionPage[]> {
  const query = cleanFilters(filters);
  const attempt = (loaded: readonly SessionPage[]) => collectSessionPages(query, loaded, includeHtml, signal);
  const pages = await attempt(loadedPages) ?? await attempt([]);
  if (!pages) throw new Error("Sessions changed while preparing the export. Try again.");
  return pages;
}

async function collectSessionPages(
  query: SessionFilters, loaded: readonly SessionPage[], includeHtml: boolean, signal: AbortSignal,
): Promise<SessionPage[] | null> {
  const pages = [...loaded];
  let offset = pages.reduce((sum, page) => sum + page.sessions.length, 0);
  let total = pages[0]?.total;
  while (total === undefined || offset < total) {
    // Best-match reranking replaces the first journal-sized page.
    const limit = offset === 0 && query.ordering === "best" ? SESSION_PAGE : 500;
    const page = await fetchSessionPage(query, offset, limit, includeHtml, signal);
    total ??= page.total;
    if (page.total !== total || (!page.sessions.length && offset < total)) return null;
    pages.push(page);
    offset += page.sessions.length;
  }
  if (pages.some((page) => page.total !== total) || offset !== total || mergeSessionPages(pages).length !== total) return null;
  return pages;
}

/** The AI order replaces the first ranked page and may add related matches. */
export function mergeSessionPages(pages: readonly SessionPage[], orderedHead?: SessionRow[]): SessionRow[] {
  const seen = new Set<number>();
  return pages.flatMap((page, index) => index === 0 && orderedHead ? orderedHead : page.sessions).filter((row) => {
    if (seen.has(row.id)) return false;
    seen.add(row.id);
    return true;
  });
}

/** The filtered list's whole duration, whatever pages are loaded. */
export function useSessionTotals(filters: SessionFilters, enabled: boolean) {
  const { ordering: _ordering, ...rest } = filters;
  const query = Object.fromEntries(Object.entries(rest).filter(([, value]) => value)) as Omit<SessionFilters, "ordering">;
  const params = { ...query, active: "false", ...(query.search ? { related: true } : {}) };
  return useQuery({
    queryKey: keys.reports("totals", params),
    queryFn: () => unwrap(api.GET("/api/v2/reports/totals/", { params: { query: params } })),
    enabled,
  });
}

/** Explicit URL choice wins; older links use the last choice on this device. */
export function readSessionOrder(params: URLSearchParams): "best" | "newest" {
  const order = params.get("order");
  if (order === "best" || order === "newest") return order;
  try {
    return localStorage.getItem("autumn.sessions.order") === "best" ? "best" : "newest";
  } catch {
    return "newest";
  }
}

export function saveSessionOrder(order: "best" | "newest") {
  try { localStorage.setItem("autumn.sessions.order", order); } catch { /* device storage unavailable */ }
}

export function useBestMatchOrder(filters: SessionFilters, depth: string, enabled: boolean) {
  const { ordering: _ordering, ...rest } = filters;
  const query = Object.fromEntries(Object.entries(rest).filter(([, value]) => value)) as typeof rest;
  return useQuery({
    queryKey: keys.sessions({ bestMatchOrder: query, depth }),
    enabled,
    staleTime: 10 * 60_000,
    gcTime: 10 * 60_000,
    retry: false,
    queryFn: () => unwrap(api.GET("/api/v2/sessions/best-match-order/", {
      params: { query: { ...query, related: true, active: false, include: "note,note_html" } },
    })),
  });
}

/* A finished session as the track endpoint takes it: plain data, so it can
   be queued and replayed. The server dedupes on `uuid`, so a replay or a
   double submit records one session. */
export interface LogSessionInput {
  uuid: string;
  project_id: number;
  start: string;
  end: string;
  note?: string | null;
  subproject_ids?: number[];
  subproject_allocations?: { subproject_id: number; allocation_bp: number }[];
}

const postSession = (body: LogSessionInput) => unwrap(api.POST("/api/v2/sessions/", { body })) as Promise<SessionRow>;

/** Record a session that already happened (Log past session). Kept on the
    device when Autumn can't be reached, or when it is on a project or
    subproject that hasn't synced yet; then it resolves to "queued". */
export function useLogSession() {
  const invalidate = useInvalidate();
  return useMutation({
    networkMode: "always",
    mutationFn: async ({
      projectName,
      subprojects,
      ...input
    }: LogSessionInput & { projectName: string; subprojects?: { id: number; name: string }[] }): Promise<SessionRow | "queued"> => {
      const { body, waiting } = resolveRefs(input);
      const queue = () => (enqueue({ kind: "session", body, display: { projectName, subprojects } }), "queued" as const);
      if (waiting) return queue();
      try {
        return await postSession(body);
      } catch (error) {
        if (!(error instanceof ApiError && isNetworkFailure(error.status))) throw error;
        return queue();
      }
    },
    onSuccess: (result) => {
      if (result !== "queued") invalidate("sessions");
    },
  });
}

/** Sessions logged on this device that haven't synced, as list rows. */
export function pendingSessions(ops: QueuedOp[]): SessionRow[] {
  return ops.flatMap((op) => {
    if (op.kind !== "session") return [];
    const names = new Map((op.display.subprojects ?? []).map((sub) => [sub.id, sub.name]));
    const body = op.body as LogSessionInput;
    const ids = body.subproject_allocations?.map((a) => a.subproject_id) ?? body.subproject_ids ?? [];
    const row = {
      id: -Date.parse(op.queuedAt),
      uuid: body.uuid,
      version: 0,
      project: { id: body.project_id, name: op.display.projectName },
      subproject_allocations: ids.map((id) => ({
        subproject_id: id,
        name: names.get(id) ?? "Subproject",
        allocation_bp: body.subproject_allocations?.find((a) => a.subproject_id === id)?.allocation_bp ?? Math.floor(10000 / ids.length),
      })),
      start: body.start,
      end: body.end,
      duration_minutes: (Date.parse(body.end) - Date.parse(body.start)) / 60_000,
      note: body.note ?? null,
      pending_sync: true,
    };
    return [row as unknown as SessionRow];
  });
}

/* Delete with undo: the toast's Undo re-records the same session (same uuid,
   instants, note and allocations) through the track endpoint. */
export function useDeleteSession() {
  const client = useQueryClient();
  const invalidate = useInvalidate();
  const toast = useToast();

  const restore = useMutation({
    mutationFn: (session: SessionRow) =>
      postSession({
        uuid: session.uuid ?? crypto.randomUUID(),
        project_id: session.project.id,
        start: session.start,
        end: session.end!,
        note: session.note ?? null,
        ...(session.subproject_allocations.length
          ? { subproject_allocations: session.subproject_allocations.map(({ subproject_id, allocation_bp }) => ({ subproject_id, allocation_bp })) }
          : {}),
      }),
    onSuccess: () => toast.success("Session restored."),
    onError: (error) => toast.error(`Couldn't restore the session: ${errorMessage(error)}`),
    onSettled: () => invalidate("sessions"),
  });

  return useMutation({
    mutationFn: async (session: SessionRow) =>
      unwrap(
        api.DELETE("/api/v2/sessions/{session_id}", {
          params: { path: { session_id: session.id }, header: { "If-Match": session.version } },
        }),
      ),
    onMutate: async (session) => {
      await client.cancelQueries({ queryKey: keys.sessions() });
      client.setQueriesData<{ pages: { sessions: SessionRow[] }[] }>({ queryKey: keys.sessions() }, (data) =>
        data && Array.isArray(data.pages)
          ? { ...data, pages: data.pages.map((page) => ({ ...page, sessions: page.sessions.filter((s) => s.id !== session.id) })) }
          : data,
      );
    },
    onSuccess: (_data, session) => {
      toast.success(`Deleted ${session.project.name} session.`, {
        action: { label: "Undo", run: () => restore.mutate(session) },
      });
    },
    onError: (error) => toast.error(`Couldn't delete the session: ${errorMessage(error)}`),
    onSettled: () => invalidate("sessions"),
  });
}

/* ---- Single-session reads and edits (edit / delete pages) ---------------- */

import { useQuery } from "@tanstack/react-query";
import type { SessionPatch } from "@/api/types";

const UUID_RE = /^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$/i;

/* The URL param of /update_session/:id/ is a numeric id or a session uuid
   (the uuid survives export/re-import, so it works as a stable link). */
export type SessionParam = { kind: "id"; id: number } | { kind: "uuid"; uuid: string } | { kind: "invalid" };

export function parseSessionParam(param: string | undefined): SessionParam {
  if (param && /^\d+$/.test(param)) return { kind: "id", id: Number(param) };
  if (param && UUID_RE.test(param)) return { kind: "uuid", uuid: param };
  return { kind: "invalid" };
}

const uuidKey = (uuid: string) => [...keys.sessions(), "detail", "uuid", uuid.toLowerCase().replace(/-/g, "")] as const;

/** One session by numeric id or uuid; a 404 ApiError when it doesn't exist. */
export function useSession(param: string | undefined) {
  const parsed = parseSessionParam(param);
  return useQuery({
    queryKey: parsed.kind === "id" ? keys.session(parsed.id) : parsed.kind === "uuid" ? uuidKey(parsed.uuid) : ["sessions", "detail", "invalid"],
    enabled: parsed.kind !== "invalid",
    /* The form reads this once; edits elsewhere are caught by If-Match. */
    refetchOnWindowFocus: false,
    queryFn: async (): Promise<SessionRow> => {
      if (parsed.kind === "id") {
        return unwrap(
          api.GET("/api/v2/sessions/{session_id}", {
            params: { path: { session_id: parsed.id }, query: { include: "note_html" } },
          }),
        );
      }
      if (parsed.kind === "uuid") {
        const data = await unwrap(
          api.GET("/api/v2/sessions/", { params: { query: { uuid: parsed.uuid, include: "note,note_html", limit: 1 } } }),
        );
        const found = data.sessions[0];
        if (!found) throw new ApiError(404, "not_found", "That session no longer exists.");
        return found;
      }
      throw new ApiError(404, "not_found", "That session no longer exists.");
    },
  });
}

function writeSessionCache(client: ReturnType<typeof useQueryClient>, session: SessionRow) {
  client.setQueryData(keys.session(session.id), session);
  if (session.uuid) client.setQueryData(uuidKey(session.uuid), session);
  /* Lists show the change at once; the refetch after brings note_html. */
  client.setQueriesData<{ pages: { sessions: SessionRow[] }[] }>({ queryKey: keys.sessions() }, (data) =>
    data && Array.isArray(data.pages)
      ? { ...data, pages: data.pages.map((page) => ({ ...page, sessions: page.sessions.map((row) => (row.id === session.id ? { ...row, ...session, note_html: session.note_html ?? undefined } : row)) })) }
      : data,
  );
}

/* PATCH with the version the form was opened on (If-Match): the server
   answers 409 version_conflict, with the current session in error.details,
   when it changed meanwhile. Pass `version` to override (save over it). */
export function useUpdateSession() {
  const client = useQueryClient();
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ session, body, version }: { session: SessionRow; body: SessionPatch; version?: number }) =>
      unwrap(
        api.PATCH("/api/v2/sessions/{session_id}", {
          params: { path: { session_id: session.id }, header: { "If-Match": version ?? session.version } },
          body,
        }),
      ) as Promise<SessionRow>,
    onSuccess: (session) => {
      writeSessionCache(client, session);
      invalidate("sessions");
    },
  });
}

