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
