import { useMutation, useQueries, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { errorMessage } from "@/api/errors";
import { keys } from "@/api/keys";
import { fetchAllProjects } from "@/api/meta";
import { useInvalidate } from "@/api/sync";
import type { Commitment, Project, ProjectDetail, ProjectStatus, Subproject } from "@/api/types";
import { useActiveContext } from "@/app/context";
import {
  applyClientFilters,
  relatedOnly,
  serverQuery,
  sortByActivity,
  type ProjectFilters,
} from "./logic";

/* ------------------------------------------------------------------ lists */

export interface ProjectLists {
  /** Keyword matches (or everything, with no search), newest activity first. */
  direct: Project[];
  /** Meaning-based matches the keyword search missed. */
  related: Project[];
}

/* The Projects page. The API's list has no date range, include-only or
   activity ordering, so those are applied to the fetched set here. With a
   search, a second request with related=true supplies the related matches. */
export function useProjectLists(filters: ProjectFilters) {
  const { contextIdsParam } = useActiveContext();
  const query = serverQuery(filters, contextIdsParam);
  return useQuery({
    queryKey: keys.projects({ list: { query, client: [filters.start_date, filters.end_date, filters.projectMode === "include" ? filters.projects : []] } }),
    queryFn: async (): Promise<ProjectLists> => {
      const direct = await fetchAllProjects(query);
      const related = query.search ? relatedOnly(await fetchAllProjects({ ...query, related: true }), direct) : [];
      return {
        direct: sortByActivity(applyClientFilters(direct, filters)),
        related: applyClientFilters(related, filters),
      };
    },
  });
}

export function useCommitments() {
  return useQuery({
    queryKey: keys.commitments(),
    queryFn: async (): Promise<Commitment[]> => (await unwrap(api.GET("/api/v2/commitments/"))).commitments,
  });
}

/* ---------------------------------------------------------------- details */

/* `enabled: false` is how a delete page stops its own record being refetched
   (and answering 404) between the delete and the navigation away. */
export function useProject(id: number, enabled = true) {
  return useQuery({
    queryKey: keys.project(id),
    enabled: enabled && id > 0,
    queryFn: (): Promise<ProjectDetail> => unwrap(api.GET("/api/v2/projects/{project_id}", { params: { path: { project_id: id } } })),
  });
}

export function useSubproject(id: number, enabled = true) {
  return useQuery({
    queryKey: ["projects", "subproject", id] as const,
    enabled,
    queryFn: (): Promise<Subproject> => unwrap(api.GET("/api/v2/subprojects/{subproject_id}", { params: { path: { subproject_id: id } } })),
  });
}

/* The API does not return a subproject's creation date, so the page shows the
   day of its first session instead: one request for the oldest session. */
export function useFirstSessionDate(subprojectId: number, sessionCount: number | undefined) {
  return useQuery({
    queryKey: ["sessions", "subproject-first", subprojectId, sessionCount ?? 0] as const,
    enabled: !!sessionCount,
    queryFn: async (): Promise<string | null> => {
      const data = await unwrap(
        api.GET("/api/v2/sessions/", {
          params: {
            query: {
              subproject_ids: String(subprojectId),
              active: false,
              ordering: "newest",
              limit: 1,
              offset: Math.max(0, (sessionCount ?? 1) - 1),
            },
          },
        }),
      );
      return data.sessions[0]?.start ?? null;
    },
  });
}

/** Names for subproject ids a commitment's rules mention. */
export function useSubprojectNames(ids: number[]) {
  const results = useQueries({
    queries: ids.map((id) => ({
      queryKey: ["projects", "subproject", id] as const,
      queryFn: (): Promise<Subproject> => unwrap(api.GET("/api/v2/subprojects/{subproject_id}", { params: { path: { subproject_id: id } } })),
      staleTime: 5 * 60_000,
    })),
  });
  return new Map(results.flatMap((result) => (result.data ? [[result.data.id, result.data.name] as [number, string]] : [])));
}

/* -------------------------------------------------------------- mutations */

function useMutationEffects() {
  return { invalidate: useInvalidate() };
}

export interface ProjectInput {
  name: string;
  description: string;
  status?: ProjectStatus;
  context_id: number | null;
  tag_ids: number[];
}

export function useCreateProject() {
  const { invalidate } = useMutationEffects();
  return useMutation({
    mutationFn: (input: ProjectInput) =>
      unwrap(
        api.POST("/api/v2/projects/", {
          body: { ...input, status: input.status ?? "active" },
        }),
      ),
    onSuccess: () => invalidate("projects"),
  });
}

export function useUpdateProject(id: number) {
  const { invalidate } = useMutationEffects();
  return useMutation({
    mutationFn: (patch: Partial<ProjectInput>) =>
      unwrap(api.PATCH("/api/v2/projects/{project_id}", { params: { path: { project_id: id } }, body: patch })),
    onSuccess: () => invalidate("projects", "commitments"),
  });
}

export function useDeleteProject() {
  const { invalidate } = useMutationEffects();
  return useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/api/v2/projects/{project_id}", { params: { path: { project_id: id } } })),
    onSuccess: () => invalidate("projects", "commitments"),
  });
}

export function useMergeProjects() {
  const { invalidate } = useMutationEffects();
  return useMutation({
    mutationFn: (input: { source_ids: number[]; new_name: string }) =>
      unwrap(api.POST("/api/v2/projects/merge/", { body: input })),
    onSuccess: () => invalidate("projects", "commitments"),
  });
}

export function useCreateSubproject(projectId: number) {
  const { invalidate } = useMutationEffects();
  return useMutation({
    mutationFn: (input: { name: string; description: string }) =>
      unwrap(api.POST("/api/v2/projects/{project_id}/subprojects/", { params: { path: { project_id: projectId } }, body: input })),
    onSuccess: () => invalidate("projects"),
  });
}

export function useUpdateSubproject(id: number) {
  const { invalidate } = useMutationEffects();
  return useMutation({
    mutationFn: (patch: { name?: string; description?: string }) =>
      unwrap(api.PATCH("/api/v2/subprojects/{subproject_id}", { params: { path: { subproject_id: id } }, body: patch })),
    onSuccess: () => invalidate("projects", "commitments"),
  });
}

export function useDeleteSubproject() {
  const { invalidate } = useMutationEffects();
  return useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/api/v2/subprojects/{subproject_id}", { params: { path: { subproject_id: id } } })),
    onSuccess: () => invalidate("projects", "commitments"),
  });
}

export function useMergeSubprojects() {
  const { invalidate } = useMutationEffects();
  return useMutation({
    mutationFn: (input: { project_id: number; source_ids: number[]; new_name: string }) =>
      unwrap(api.POST("/api/v2/subprojects/merge/", { body: input })),
    onSuccess: () => invalidate("projects", "commitments"),
  });
}

/** Toast text for a failed mutation, with the server's own message. */
export function failure(action: string, error: unknown): string {
  return `Couldn't ${action}: ${errorMessage(error)}`;
}
