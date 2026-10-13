import { forwardRef, type AnchorHTMLAttributes } from "react";
import { Link, matchRoutes } from "react-router";
import { appRoutePatterns } from "./routePatterns";

/* Paths the React router owns. Everything else (server-rendered pages that
   have not moved yet, login, admin, the MCP OAuth screens) must be a real
   page load, so <AppLink> falls back to a plain anchor for those. */
export function isAppPath(href: string): boolean {
  if (!href.startsWith("/") || href.startsWith("//")) return false;
  const path = href.split(/[?#]/)[0] ?? href;
  return matchRoutes(appRoutePatterns.map((path) => ({ path })), path) !== null;
}

type Props = AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; replace?: boolean };

export const AppLink = forwardRef<HTMLAnchorElement, Props>(function AppLink({ href, replace, ...rest }, ref) {
  if (isAppPath(href)) return <Link ref={ref} to={href} replace={replace} {...rest} />;
  return <a ref={ref} href={href} {...rest} />;
});

/* Server URLs the app links to. One place, so a page moving into the app
   only changes the router, not every link. */
export const urls = {
  home: () => "/",
  projects: () => "/projects/",
  timers: () => "/timers/",
  startTimer: () => "/start_timer/",
  stopTimer: (id: number) => `/stop_timer/${id}/`,
  sessions: () => "/sessions/",
  updateSession: (id: number) => `/update_session/${id}/`,
  deleteSession: (id: number) => `/delete_session/${id}/`,
  updateProject: (id: number) => `/update_project/${id}/`,
  updateSubproject: (id: number) => `/update_subproject/${id}/`,
  createProject: () => "/create_project/",
  createSubproject: (projectId: number) => `/create_subproject/${projectId}/`,
  deleteProject: (id: number) => `/delete_project/${id}/`,
  deleteSubproject: (id: number) => `/delete_subproject/${id}/`,
  mergeProjects: () => "/merge_projects/",
  mergeSubprojects: (projectId: number) => `/merge_subprojects/${projectId}/`,
  charts: () => "/charts/",
  insights: () => "/insights/",
  notifications: () => "/notifications/",
  weeklyReview: () => "/review/weekly/",
  contexts: () => "/contexts/",
  updateContext: (id: number) => `/update_context/${id}/`,
  tags: () => "/tags/",
  updateTag: (id: number) => `/update_tag/${id}/`,
  createCommitment: (projectId?: number) => (projectId ? `/create_commitment/${projectId}/` : "/create_commitment/"),
  updateCommitment: (id: number) => `/update_commitment/${id}/`,
  deleteCommitment: (id: number) => `/delete_commitment/${id}/`,
  import: () => "/import/",
  export: () => "/export/",
  profile: () => "/profile/",
  mcpConnections: () => "/mcp/connections/",
  logout: () => "/logout/",
};
