import { useCallback, useEffect } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { announce, listen, type BroadcastTopic } from "@/lib/broadcast";
import { staleAfter } from "./keys";

function invalidateTopics(client: QueryClient, topics: BroadcastTopic[]) {
  const seen = new Set<string>();
  for (const topic of topics) {
    const prefixes = topic === "meta" ? staleAfter.meta : staleAfter[topic];
    for (const prefix of prefixes) {
      const id = JSON.stringify(prefix);
      if (seen.has(id)) continue;
      seen.add(id);
      void client.invalidateQueries({ queryKey: [...prefix] });
    }
  }
}

/** Mark data stale here and in every other open Autumn tab. */
export function useInvalidate() {
  const client = useQueryClient();
  return useCallback(
    (...topics: BroadcastTopic[]) => {
      invalidateTopics(client, topics);
      announce(...topics);
    },
    [client],
  );
}

/** Mounted once: apply other tabs' announcements to this tab's cache. */
export function useCrossTabSync() {
  const client = useQueryClient();
  useEffect(() => listen((topics) => invalidateTopics(client, topics)), [client]);
}
