import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import { keys } from "./keys";
import type { Context, Project, Subproject, Tag } from "./types";

/* Lookup data for pickers and filters: every project, tag and context the
   user has. Small, changes rarely, shared by many pages, so it is cached for
   longer than page data. */
const META_STALE = 5 * 60_000;
const PAGE = 200;

export async function fetchAllProjects(query: Record<string, string | number | boolean> = {}): Promise<Project[]> {
  const all: Project[] = [];
  for (let offset = 0; ; offset += PAGE) {
    const data = await unwrap(
      api.GET("/api/v2/projects/", { params: { query: { ...query, limit: PAGE, offset, ordering: "name" } } }),
    );
    all.push(...data.projects);
    if (data.projects.length < PAGE || all.length >= data.total) break;
  }
  return all;
}

export function useAllProjects() {
  return useQuery({ queryKey: keys.projects({ all: true }), queryFn: () => fetchAllProjects(), staleTime: META_STALE });
}

export function useTags() {
  return useQuery({
    queryKey: keys.tags(),
    queryFn: async (): Promise<Tag[]> => (await unwrap(api.GET("/api/v2/tags/"))).tags,
    staleTime: META_STALE,
  });
}

export function useContexts() {
  return useQuery({
    queryKey: keys.contexts(),
    queryFn: async (): Promise<Context[]> => (await unwrap(api.GET("/api/v2/contexts/"))).contexts,
    staleTime: META_STALE,
  });
}

export function useSubprojects(projectId: number | null | undefined) {
  return useQuery({
    queryKey: keys.subprojects(projectId ?? 0),
    enabled: !!projectId,
    queryFn: async (): Promise<Subproject[]> =>
      (
        await unwrap(
          api.GET("/api/v2/projects/{project_id}/subprojects/", { params: { path: { project_id: projectId! } } }),
        )
      ).subprojects,
    staleTime: META_STALE,
  });
}
