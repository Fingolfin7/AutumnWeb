import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BOOTSTRAP_REFRESHED, bootstrap } from "@/bootstrap";
import { requestJson } from "@/api/client";
import { useToast } from "./toasts";
import { errorMessage } from "@/api/errors";

/* The active context narrows the dashboard, projects, sessions, timers,
   charts and Insights. It is kept on the server (session + Profile) so the
   CLI-free web flows and server-rendered pages agree, and mirrored here so a
   switch re-scopes every query instantly without a page reload. */
interface ActiveContextValue {
  contextId: number | null;
  contexts: { id: number; name: string }[];
  setContextId: (id: number | null) => Promise<void>;
  /** Query-string value for API filters: undefined means "all contexts". */
  contextIdsParam: string | undefined;
}

const ActiveContext = createContext<ActiveContextValue | null>(null);

export function useActiveContext(): ActiveContextValue {
  const value = useContext(ActiveContext);
  if (!value) throw new Error("useActiveContext outside ActiveContextProvider");
  return value;
}

export function ActiveContextProvider({ children }: { children: ReactNode }) {
  const initial = bootstrap();
  const [contextId, setLocal] = useState<number | null>(initial.active_context_id);
  const [contexts, setContexts] = useState(initial.contexts);
  const queryClient = useQueryClient();
  const toast = useToast();

  /* Something replaced the account's data in place (a backup restore) and
     refreshed the bootstrap blob: follow it without a reload. */
  useEffect(() => {
    const follow = () => {
      setContexts(bootstrap().contexts);
      setLocal(bootstrap().active_context_id);
    };
    window.addEventListener(BOOTSTRAP_REFRESHED, follow);
    return () => window.removeEventListener(BOOTSTRAP_REFRESHED, follow);
  }, []);

  const setContextId = useCallback(
    async (id: number | null) => {
      const previous = contextId;
      setLocal(id);
      try {
        await requestJson("PATCH", "/api/v2/me/preferences/", { active_context_id: id });
      } catch (error) {
        setLocal(previous);
        toast.error(`Couldn't switch context: ${errorMessage(error)}`);
        return;
      }
      await queryClient.invalidateQueries();
    },
    [contextId, queryClient, toast],
  );

  const value = useMemo<ActiveContextValue>(
    () => ({
      contextId,
      contexts,
      setContextId,
      contextIdsParam: contextId === null ? undefined : String(contextId),
    }),
    [contextId, contexts, setContextId],
  );

  return <ActiveContext.Provider value={value}>{children}</ActiveContext.Provider>;
}
