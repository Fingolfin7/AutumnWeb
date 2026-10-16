/* Query keys, one factory per resource. Invalidate by prefix: everything about
   sessions starts with ["sessions"], so invalidating that refreshes lists,
   details and the dashboard sections built from them. */
export const keys = {
  timers: () => ["timers"] as const,
  /* Not under ["timers"]: the optimistic updates there edit Timer[] lists. */
  timersOutsideContext: (context: string) => ["timers-outside-context", context] as const,
  sessions: (params?: object) => (params ? (["sessions", params] as const) : (["sessions"] as const)),
  session: (id: number) => ["sessions", "detail", id] as const,
  projects: (params?: object) => (params ? (["projects", params] as const) : (["projects"] as const)),
  project: (id: number) => ["projects", "detail", id] as const,
  subprojects: (projectId: number) => ["projects", "subprojects", projectId] as const,
  tags: () => ["tags"] as const,
  contexts: () => ["contexts"] as const,
  commitments: () => ["commitments"] as const,
  dashboard: (context?: string) => ["dashboard", context ?? "all"] as const,
  reports: (kind: string, params?: object) => ["reports", kind, params ?? {}] as const,
  preferences: () => ["me", "preferences"] as const,
  recommendations: (kind: string) => ["recommendations", kind] as const,
};

/* What a mutation of each kind makes stale. Timers feed the dashboard and
   session lists (a stopped timer becomes a session), so they fan out. */
export const staleAfter = {
  timers: [["timers"], ["dashboard"], ["sessions"], ["reports"], ["commitments"], ["recommendations"]],
  sessions: [["sessions"], ["dashboard"], ["reports"], ["projects"], ["commitments"]],
  projects: [["projects"], ["sessions"], ["dashboard"], ["reports"]],
  commitments: [["commitments"], ["dashboard"]],
  meta: [["tags"], ["contexts"], ["projects"]],
} as const;
