import { useMemo } from "react";
import { queryOptions, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { ApiError, errorMessage } from "@/api/errors";
import { keys } from "@/api/keys";
import { fetchAllProjects, useQueuedOps, withPendingProjects, withPendingSubprojects } from "@/api/meta";
import { useInvalidate } from "@/api/sync";
import type { Commitment, Context, Project, ProjectDetail, ProjectStatus, Subproject, Tag } from "@/api/types";
import { enqueue, isNetworkFailure, newTempId, queuedOps, resolveRefs } from "@/lib/offlineQueue";
import { useActiveContext } from "@/app/context";
import { conflictCurrent } from "./forms";
import { onlyIncluded, relatedOnly, serverQuery, type ProjectFilters } from "./logic";

/* ------------------------------------------------------------------ lists */

export interface ProjectLists {
  /** Keyword matches (or everything, with no search), newest activity first. */
  direct: Project[];
  /** Meaning-based matches the keyword search missed. */
  related: Project[];
}

/* The Projects page. The API does the searching, date range and activity
   ordering; only "only these projects" is applied to the fetched set here.
   With a search, a second request with related=true supplies the related
   matches. */
export function projectListsQuery(filters: ProjectFilters, contextIdsParam: string | undefined) {
  const query = serverQuery(filters, contextIdsParam);
  return queryOptions({
    queryKey: keys.projects({ list: { query, only: filters.projectMode === "include" ? filters.projects : [] } }),
    queryFn: async (): Promise<ProjectLists> => {
      const direct = await fetchAllProjects(query);
      const related = query.search ? relatedOnly(await fetchAllProjects({ ...query, related: true }), direct) : [];
      return {
        direct: onlyIncluded(direct, filters),
        related: onlyIncluded(related, filters),
      };
    },
  });
}

/* Projects not synced yet join the plain list (no search or filter but the
   context), newest first. */
export function useProjectLists(filters: ProjectFilters) {
  const { contextIdsParam } = useActiveContext();
  const query = useQuery(projectListsQuery(filters, contextIdsParam));
  const ops = useQueuedOps();
  const asked = serverQuery(filters, contextIdsParam);
  const plain = !asked.search && !asked.start_date && !asked.end_date && !asked.tag_ids && !filters.projects.length;
  const context_ids = asked.context_ids;
  const data = useMemo(() => {
    if (!plain) return query.data;
    const saved = query.data ?? { direct: [], related: [] };
    const contexts = context_ids?.split(",").map(Number);
    const direct = withPendingProjects(saved.direct, ops).filter(
      (project) => !project.pending_sync || !contexts || contexts.includes(project.context?.id ?? 0),
    );
    return direct.length === saved.direct.length ? query.data : { ...saved, direct };
  }, [plain, query.data, ops, context_ids]);
  /* Nothing saved on this device yet, but projects created here: show them. */
  if (data && !query.data) return { ...query, data, isPending: false, isError: false };
  return { ...query, data };
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

const subprojectKey = (id: number) => ["projects", "subproject", id] as const;

export function useSubproject(id: number, enabled = true) {
  return useQuery({
    queryKey: subprojectKey(id),
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

/* With no connection, a create is kept on the device (lib/offlineQueue) and
   the hook resolves to "queued"; the new record shows at once, marked
   pending_sync, and can be used before it syncs. A name already taken in
   what the device knows is refused as the server would refuse it. */
const nameTaken = (what: string) => new ApiError(409, "conflict", `${what} name already exists`);
const offline = (error: unknown) => error instanceof ApiError && isNetworkFailure(error.status);

export function useCreateProject() {
  const { invalidate } = useMutationEffects();
  const client = useQueryClient();
  return useMutation({
    networkMode: "always",
    mutationFn: async (input: ProjectInput): Promise<Project | "queued"> => {
      const body = { ...input, status: input.status ?? "active" };
      try {
        return await unwrap(api.POST("/api/v2/projects/", { body }));
      } catch (error) {
        if (!offline(error)) throw error;
        const known = withPendingProjects(client.getQueryData<Project[]>(keys.projects({ all: true })) ?? [], queuedOps());
        if (known.some((project) => project.name === body.name)) throw nameTaken("Project");
        const contexts = client.getQueryData<Context[]>(keys.contexts()) ?? [];
        const tags = client.getQueryData<Tag[]>(keys.tags()) ?? [];
        const context = contexts.find((c) => c.id === body.context_id);
        enqueue({
          kind: "project",
          tempId: newTempId(),
          body: { ...body, description: body.description ?? "" },
          display: {
            context: context ? { id: context.id, name: context.name } : null,
            tags: tags.filter((tag) => body.tag_ids.includes(tag.id)).map((tag) => ({ id: tag.id, name: tag.name })),
          },
        });
        return "queued";
      }
    },
    onSuccess: (result) => {
      if (result !== "queued") invalidate("projects");
    },
  });
}

/* Edits and deletes carry the version the page was opened on (If-Match): the
   server answers 409 version_conflict, with the current record in
   error.details, when the project changed meanwhile (see conflictCurrent). */
export function useUpdateProject(id: number) {
  const { invalidate } = useMutationEffects();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ patch, version }: { patch: Partial<ProjectInput>; version?: number }) =>
      unwrap(
        api.PATCH("/api/v2/projects/{project_id}", {
          params: { path: { project_id: id }, header: { "If-Match": version } },
          body: patch,
        }),
      ),
    onSuccess: (saved) => {
      /* Keep the open page's copy at the saved version so it doesn't read as
         "changed elsewhere" before the refetch lands. */
      client.setQueryData<ProjectDetail>(keys.project(id), (old) => (old ? { ...old, ...saved } : old));
      invalidate("projects", "commitments");
    },
    /* A conflict means the cached copy is out of date: fetch the new one. */
    onError: (error) => {
      if (conflictCurrent(error)) invalidate("projects");
    },
  });
}

export function useDeleteProject() {
  const { invalidate } = useMutationEffects();
  return useMutation({
    mutationFn: ({ id, version }: { id: number; version?: number }) =>
      unwrap(
        api.DELETE("/api/v2/projects/{project_id}", {
          params: { path: { project_id: id }, header: { "If-Match": version } },
        }),
      ),
    onSuccess: () => invalidate("projects", "commitments"),
    onError: (error) => {
      if (conflictCurrent(error)) invalidate("projects");
    },
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

/** `project` may be one created offline that hasn't synced yet. */
export function useCreateSubproject(project: Pick<Project, "id" | "name">) {
  const { invalidate } = useMutationEffects();
  const client = useQueryClient();
  return useMutation({
    networkMode: "always",
    mutationFn: async (input: { name: string; description: string }): Promise<Subproject | "queued"> => {
      const { body: { project_id }, waiting } = resolveRefs({ project_id: project.id });
      const queue = () => {
        const known = withPendingSubprojects(project_id, client.getQueryData<Subproject[]>(keys.subprojects(project_id)) ?? [], queuedOps());
        if (known.some((sub) => sub.name === input.name)) throw nameTaken("Subproject");
        enqueue({ kind: "subproject", tempId: newTempId(), project_id, body: input, display: { projectName: project.name } });
        return "queued" as const;
      };
      if (waiting) return queue();
      try {
        return await unwrap(api.POST("/api/v2/projects/{project_id}/subprojects/", { params: { path: { project_id } }, body: input }));
      } catch (error) {
        if (!offline(error)) throw error;
        return queue();
      }
    },
    onSuccess: (result) => {
      if (result !== "queued") invalidate("projects");
    },
  });
}

/* Same If-Match contract as projects. */
export function useUpdateSubproject(id: number) {
  const { invalidate } = useMutationEffects();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ patch, version }: { patch: { name?: string; description?: string }; version?: number }) =>
      unwrap(
        api.PATCH("/api/v2/subprojects/{subproject_id}", {
          params: { path: { subproject_id: id }, header: { "If-Match": version } },
          body: patch,
        }),
      ),
    onSuccess: (saved) => {
      client.setQueryData<Subproject>(subprojectKey(id), (old) => (old ? { ...old, ...saved } : old));
      invalidate("projects", "commitments");
    },
    onError: (error) => {
      if (conflictCurrent(error)) invalidate("projects");
    },
  });
}

export function useDeleteSubproject() {
  const { invalidate } = useMutationEffects();
  return useMutation({
    mutationFn: ({ id, version }: { id: number; version?: number }) =>
      unwrap(
        api.DELETE("/api/v2/subprojects/{subproject_id}", {
          params: { path: { subproject_id: id }, header: { "If-Match": version } },
        }),
      ),
    onSuccess: () => invalidate("projects", "commitments"),
    onError: (error) => {
      if (conflictCurrent(error)) invalidate("projects");
    },
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
