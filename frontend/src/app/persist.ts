import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { removeOldestQuery, type PersistQueryClientOptions } from "@tanstack/react-query-persist-client";
import { bootstrap } from "@/bootstrap";

/* The last data for the screens you open most, kept on this device: a cold
   start on a phone paints from it at once (then refreshes), and with no
   signal the app still shows your timers, projects and recent sessions
   instead of an error. Per user, dropped on every new build and on logout. */

const PREFIX = "autumn:query-cache:";
const KEPT = new Set(["timers", "dashboard", "projects", "sessions", "tags", "contexts", "commitments"]);
export const MAX_AGE = 3 * 24 * 60 * 60_000;

export function persistOptions(): Omit<PersistQueryClientOptions, "queryClient"> | null {
  let storage: Storage;
  try {
    storage = window.localStorage;
  } catch {
    return null;
  }
  const userId = bootstrap().user.id;
  if (!userId) return null;
  return {
    persister: createSyncStoragePersister({
      storage,
      key: `${PREFIX}${userId}`,
      throttleTime: 2_000,
      /* Over quota: shed the oldest queries until it fits. */
      retry: removeOldestQuery,
    }),
    maxAge: MAX_AGE,
    buster: __BUILD_ID__,
    dehydrateOptions: {
      shouldDehydrateQuery: (query) =>
        query.state.status === "success" && KEPT.has(String(query.queryKey[0])),
    },
  };
}

/** Forget every user's saved data on this device (logout), including the
    service worker's offline copy of the app page. */
export function clearPersistedQueries() {
  navigator.serviceWorker?.controller?.postMessage({ type: "forget-shell" });
  try {
    const storage = window.localStorage;
    for (const key of Object.keys(storage)) if (key.startsWith(PREFIX)) storage.removeItem(key);
  } catch {
    /* storage unavailable */
  }
}
