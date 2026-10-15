import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { keys } from "@/api/keys";
import { useInvalidate } from "@/api/sync";
import type { Session } from "@/api/types";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";

export interface SessionFilters {
  search?: string;
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
export type SessionRow = Session;

export const SESSION_PAGE = 30;

/* One ranked list shared with API v2 and MCP (core.search.rank_sessions):
   with a search term and related=true the server returns direct matches
   newest first, then related matches best first, each tagged by `match`. */
export function useSessionList(filters: SessionFilters) {
  const query = Object.fromEntries(Object.entries(filters).filter(([, value]) => value)) as SessionFilters;
  const searching = !!query.search;
  return useInfiniteQuery({
    queryKey: keys.sessions({ list: query }),
    initialPageParam: 0,
    queryFn: async ({ pageParam }) =>
      unwrap(
        api.GET("/api/v2/sessions/", {
          params: {
            query: {
              ...query,
              active: false,
              include: "note,note_html",
              limit: SESSION_PAGE,
              offset: pageParam,
              ...(searching ? { related: true, ordering: "relevance" as const } : { ordering: "newest" as const }),
            },
          },
        }),
      ),
    getNextPageParam: (last, all) => {
      const loaded = all.reduce((sum, page) => sum + page.sessions.length, 0);
      return last.sessions.length && loaded < last.total ? loaded : undefined;
    },
  });
}

/* Delete with undo: the toast's Undo re-records the same session (same uuid,
   instants, note and allocations) through the track endpoint. */
export function useDeleteSession() {
  const client = useQueryClient();
  const invalidate = useInvalidate();
  const toast = useToast();

  const restore = useMutation({
    mutationFn: async (session: SessionRow) =>
      unwrap(
        api.POST("/api/v2/sessions/", {
          body: {
            project_id: session.project.id,
            start: session.start,
            end: session.end!,
            note: session.note ?? null,
            ...(session.uuid ? { uuid: session.uuid } : {}),
            ...(session.subproject_allocations.length
              ? {
                  subproject_allocations: session.subproject_allocations.map((a) => ({
                    subproject_id: a.subproject_id,
                    allocation_bp: a.allocation_bp,
                  })),
                }
              : {}),
          },
        }),
      ),
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
import { ApiError } from "@/api/errors";
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

