import { useEffect } from "react";
import { QueryCache, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/errors";
import { useActiveContext } from "./context";

/* What the app does when Autumn can't be reached (no signal, a weak one, or
   the server waking up).

   A refresh that fails must not take away what the screen was showing, nor
   the copy saved on this device: persist.ts keeps successful queries only, so
   a query left in "error" would be erased from the device on the next save.
   A query that already has data therefore stays "success" and keeps it; only
   a query with nothing to show reports the failure. `unreachable` drives the
   "Offline · saved data" pill for the case the browser still thinks it is
   online. */

const unreachableStatus = (status: number) => status === 0 || (status >= 502 && status <= 504);

let unreachable = false;
const listeners = new Set<() => void>();

function setUnreachable(next: boolean) {
  if (unreachable === next) return;
  unreachable = next;
  for (const listener of listeners) listener();
}

export function subscribeUnreachable(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export const isUnreachable = () => unreachable;

export function savedDataCache(): QueryCache {
  return new QueryCache({
    onError(error, query) {
      if (!(error instanceof ApiError) || !unreachableStatus(error.status)) return;
      setUnreachable(true);
      if (query.state.data !== undefined) query.setState({ status: "success", error: null });
    },
    onSuccess: () => setUnreachable(false),
  });
}

const WARM_DELAY_MS = 3_000;
const WARM_FRESH_MS = 5 * 60_000;
let projectsWarmedAt = 0;

/* Saves the screens you'd want with no signal (Home, the project list and
   picker with every project's subprojects, the latest sessions with their
   notes) a few seconds after each load, whichever page you opened. Without
   it only pages visited since the last deploy would be on the device.
   Anything fetched in the last five minutes is skipped. */
async function warm(client: QueryClient, contextIdsParam: string | undefined) {
  const [meta, dashboard, sessions, projects, projectLogic] = await Promise.all([
    import("@/api/meta"),
    import("@/features/dashboard/api"),
    import("@/features/sessions/api"),
    import("@/features/projects/api"),
    import("@/features/projects/logic"),
  ]);
  const fresh = { staleTime: WARM_FRESH_MS };
  /* One at a time: this is background work, not a burst. */
  for (const run of [
    /* Every project with its subprojects, so any one can be picked offline. */
    async () => {
      if (Date.now() - projectsWarmedAt < WARM_FRESH_MS) return;
      await meta.warmProjects(client);
      projectsWarmedAt = Date.now();
    },
    () => client.prefetchQuery({ ...meta.tagsQuery(), ...fresh }),
    () => client.prefetchQuery({ ...meta.contextsQuery(), ...fresh }),
    () => client.prefetchQuery({ ...dashboard.dashboardQuery(contextIdsParam), ...fresh }),
    () => client.prefetchInfiniteQuery({ ...sessions.sessionListQuery({ context_ids: contextIdsParam }), ...fresh }),
    () => client.prefetchQuery({ ...projects.projectListsQuery(projectLogic.emptyFilters, contextIdsParam), ...fresh }),
  ]) {
    if (!navigator.onLine || unreachable) return;
    await run();
  }
}

export function useWarmSavedData() {
  const client = useQueryClient();
  const { contextIdsParam } = useActiveContext();
  useEffect(() => {
    const id = window.setTimeout(() => void warm(client, contextIdsParam).catch(() => undefined), WARM_DELAY_MS);
    return () => window.clearTimeout(id);
  }, [client, contextIdsParam]);
}
