import { useMemo, useSyncExternalStore } from "react";
import { queryOptions, useQuery, type QueryClient } from "@tanstack/react-query";
import { localDateKey } from "@/lib/format";
import { queuedOps, resolveId, subscribe, type QueuedOp, type QueuedProject, type QueuedSubproject } from "@/lib/offlineQueue";
import { api, unwrap } from "./client";
import { keys } from "./keys";
import type { Context, Project, ProjectListQuery, ProjectStatus, Subproject, Tag } from "./types";

/* Lookup data for pickers and filters: every project, tag and context the
   user has. Small, changes rarely, shared by many pages, so it is cached for
   longer than page data. */
const META_STALE = 5 * 60_000;
const PAGE = 200;

type ListedProject = Project & { subprojects?: Subproject[] };

/* Pages through GET /api/v2/projects/. By name unless `ordering` says otherwise. */
export async function fetchAllProjects(query: Omit<ProjectListQuery, "limit" | "offset"> = {}): Promise<ListedProject[]> {
  const all: ListedProject[] = [];
  for (let offset = 0; ; offset += PAGE) {
    const data = await unwrap(
      api.GET("/api/v2/projects/", { params: { query: { ordering: "name", ...query, limit: PAGE, offset } } }),
    );
    all.push(...data.projects);
    if (data.projects.length < PAGE || all.length >= data.total) break;
  }
  return all;
}

export const allProjectsQuery = () =>
  queryOptions({ queryKey: keys.projects({ all: true }), queryFn: () => fetchAllProjects(), staleTime: META_STALE });

/* Every project with its subprojects in one response, and each project's
   subproject list seeded from it: after one load the pickers work with no
   signal, whichever project you pick. */
export async function warmProjects(client: QueryClient) {
  const projects = await fetchAllProjects({ include: "subprojects" });
  for (const { subprojects, ...project } of projects) {
    if (subprojects) client.setQueryData(keys.subprojects(project.id), subprojects);
  }
  client.setQueryData(
    keys.projects({ all: true }),
    projects.map(({ subprojects: _subprojects, ...project }) => project),
  );
}

export const tagsQuery = () =>
  queryOptions({
    queryKey: keys.tags(),
    queryFn: async (): Promise<Tag[]> => (await unwrap(api.GET("/api/v2/tags/"))).tags,
    staleTime: META_STALE,
  });

export const contextsQuery = () =>
  queryOptions({
    queryKey: keys.contexts(),
    queryFn: async (): Promise<Context[]> => (await unwrap(api.GET("/api/v2/contexts/"))).contexts,
    staleTime: META_STALE,
  });

export const useAllProjects = () => useQuery(allProjectsQuery());
export const useTags = () => useQuery(tagsQuery());
export const useContexts = () => useQuery(contextsQuery());

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

/* ------------------------------------------- created offline, not synced */

export const useQueuedOps = () => useSyncExternalStore(subscribe, queuedOps);

function pendingProject(op: QueuedProject): Project {
  return {
    id: op.tempId,
    version: 0,
    name: op.body.name,
    status: op.body.status as ProjectStatus,
    description: op.body.description,
    context: op.display.context,
    tags: op.display.tags,
    start_date: localDateKey(new Date(op.queuedAt)),
    last_activity: null,
    total_minutes: 0,
    session_count: 0,
    pending_sync: true,
  };
}

function pendingSubproject(op: QueuedSubproject): Subproject {
  return {
    id: op.tempId,
    version: 0,
    name: op.body.name,
    description: op.body.description,
    project_id: op.project_id,
    start_date: localDateKey(new Date(op.queuedAt)),
    last_activity: null,
    total_minutes: 0,
    session_count: 0,
    pending_sync: true,
  };
}

/** `projects` plus the queued ones, marked pending_sync. A queued name the
    list already has is that project (replay will map it there), so it is
    not shown twice. */
export function withPendingProjects(projects: Project[], ops: QueuedOp[]): Project[] {
  const names = new Set(projects.map((project) => project.name));
  const pending = ops.flatMap((op) => (op.kind === "project" && !names.has(op.body.name) ? [pendingProject(op)] : []));
  return pending.length ? [...pending, ...projects] : projects;
}

/** A project's subprojects plus the queued ones. */
export function withPendingSubprojects(projectId: number, subprojects: Subproject[], ops: QueuedOp[]): Subproject[] {
  const names = new Set(subprojects.map((sub) => sub.name));
  const id = resolveId(projectId);
  const pending = ops.flatMap((op) =>
    op.kind === "subproject" && resolveId(op.project_id) === id && !names.has(op.body.name) ? [pendingSubproject(op)] : [],
  );
  return pending.length ? [...subprojects, ...pending] : subprojects;
}

/** The project picker's list: every project, with those not synced yet. */
export function usePickerProjects() {
  const query = useAllProjects();
  const ops = useQueuedOps();
  const data = useMemo(() => (query.data || ops.length ? withPendingProjects(query.data ?? [], ops) : undefined), [query.data, ops]);
  return { ...query, data };
}

/** The subproject picker's list for a project, with those not synced yet. A
    project not synced yet has only those; one that synced since the page
    picked it is read under its real id. */
export function usePickerSubprojects(projectId: number | null | undefined) {
  const id = projectId ? resolveId(projectId) : projectId;
  const query = useSubprojects(id && id > 0 ? id : null);
  const ops = useQueuedOps();
  const local = !!id && id < 0;
  const data = useMemo(
    () => (projectId && (query.data || local) ? withPendingSubprojects(projectId, query.data ?? [], ops) : query.data),
    [projectId, query.data, local, ops],
  );
  return local ? { data, isPending: false, isError: false } : { ...query, data };
}

/** A synced creation's real record, put in the saved lists before its queued
    copy leaves them, so it never blinks out between sync and refetch. */
export function seedSynced(client: QueryClient, op: QueuedOp, record: unknown) {
  if (op.kind === "project") {
    const project = record as Project;
    client.setQueryData<Project[]>(keys.projects({ all: true }), (list) =>
      list && !list.some((p) => p.id === project.id) ? [...list, project] : list,
    );
    client.setQueryData<Subproject[]>(keys.subprojects(project.id), (list) => list ?? []);
  } else if (op.kind === "subproject") {
    const sub = record as Subproject;
    client.setQueryData<Subproject[]>(keys.subprojects(op.project_id), (list) =>
      list?.some((s) => s.id === sub.id) ? list : [...(list ?? []), sub],
    );
  }
}
