import type { ComponentType } from "react";

/* Every page the React router serves. Add an entry when a page moves into
   the app AND point its Django route at core.spa.spa (keeping the URL name,
   so server-rendered pages can still {% url %} it). Loaders are dynamic
   imports, so this table can be imported anywhere (links check it) without
   pulling pages in. Paths match the old server URLs so bookmarks keep
   working. */
export interface PageEntry {
  path: string;
  load: () => Promise<{ default: ComponentType }>;
  /** Browser tab title; pages may refine it with useTitle. */
  title: string;
}

export const pages: PageEntry[] = [
  { path: "/", title: "Autumn", load: () => import("@/features/dashboard/HomePage") },

  { path: "/timers/", title: "Timers", load: () => import("@/features/timers/TimersPage") },
  { path: "/start_timer/", title: "Start a timer", load: () => import("@/features/timers/StartTimerPage") },
  { path: "/stop_timer/:sessionId/", title: "Stop timer", load: () => import("@/features/timers/StopTimerPage") },
  { path: "/remove_timer/:sessionId/", title: "Remove timer", load: () => import("@/features/timers/RemoveTimerPage") },

  { path: "/sessions/", title: "Sessions", load: () => import("@/features/sessions/SessionsPage") },
  { path: "/update_session/:sessionId/", title: "Edit session", load: () => import("@/features/sessions/UpdateSessionPage") },
  { path: "/delete_session/:sessionId/", title: "Delete session", load: () => import("@/features/sessions/DeleteSessionPage") },

  { path: "/projects/", title: "Projects", load: () => import("@/features/projects/ProjectsPage") },
  { path: "/create_project/", title: "New project", load: () => import("@/features/projects/CreateProjectPage") },
  { path: "/create_subproject/:projectId/", title: "New subproject", load: () => import("@/features/projects/CreateSubprojectPage") },
  { path: "/update_project/:projectId/", title: "Project", load: () => import("@/features/projects/UpdateProjectPage") },
  { path: "/update_subproject/:subprojectId/", title: "Subproject", load: () => import("@/features/projects/UpdateSubprojectPage") },
  { path: "/delete_project/:projectId/", title: "Delete project", load: () => import("@/features/projects/DeleteProjectPage") },
  { path: "/delete_subproject/:subprojectId/", title: "Delete subproject", load: () => import("@/features/projects/DeleteSubprojectPage") },
  { path: "/merge_projects/", title: "Merge projects", load: () => import("@/features/projects/MergeProjectsPage") },
  { path: "/merge_subprojects/:projectId/", title: "Merge subprojects", load: () => import("@/features/projects/MergeSubprojectsPage") },

  { path: "/charts/", title: "Charts", load: () => import("@/features/charts/ChartsPage") },

  { path: "/contexts/", title: "Contexts", load: () => import("@/features/contexts-tags/ContextsPage") },
  { path: "/update_context/:contextId/", title: "Context", load: () => import("@/features/contexts-tags/UpdateContextPage") },
  { path: "/delete_context/:contextId/", title: "Delete context", load: () => import("@/features/contexts-tags/DeleteContextPage") },
  { path: "/tags/", title: "Tags", load: () => import("@/features/contexts-tags/TagsPage") },
  { path: "/update_tag/:tagId/", title: "Tag", load: () => import("@/features/contexts-tags/UpdateTagPage") },
  { path: "/delete_tag/:tagId/", title: "Delete tag", load: () => import("@/features/contexts-tags/DeleteTagPage") },

  { path: "/create_commitment/", title: "New commitment", load: () => import("@/features/commitments/CreateCommitmentPage") },
  { path: "/create_commitment/:projectId/", title: "New commitment", load: () => import("@/features/commitments/CreateCommitmentPage") },
  { path: "/update_commitment/:commitmentId/", title: "Commitment", load: () => import("@/features/commitments/UpdateCommitmentPage") },
  { path: "/delete_commitment/:commitmentId/", title: "Delete commitment", load: () => import("@/features/commitments/DeleteCommitmentPage") },

  /* Being ported: reachable by in-app navigation; their Django routes still
     serve the old pages on a full load until the switch (see core/urls.py). */
  { path: "/notifications/", title: "Notifications", load: () => import("@/features/notifications/NotificationsPage") },
  { path: "/review/weekly/", title: "Weekly review", load: () => import("@/features/review/WeeklyReviewPage") },
  { path: "/import/", title: "Import", load: () => import("@/features/import-export/ImportPage") },
  { path: "/export/", title: "Export", load: () => import("@/features/import-export/ExportPage") },
  { path: "/profile/", title: "Profile", load: () => import("@/features/profile/ProfilePage") },
  { path: "/insights/", title: "Insights", load: () => import("@/features/insights/InsightsPage") },
  { path: "/insights/:chatId/", title: "Insights", load: () => import("@/features/insights/InsightsPage") },
];

export const appRoutePatterns: string[] = pages.map((page) => page.path);
