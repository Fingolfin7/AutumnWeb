import { useMemo } from "react";
import { useMutation, useQueries, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { keys } from "@/api/keys";
import { useInvalidate } from "@/api/sync";
import { useAllProjects } from "@/api/meta";
import { sortCommitments, type EntityKind } from "./applies";
import type { Commitment, CommitmentChanges, CommitmentCreate, Subproject } from "@/api/types";

const STALE = 30_000;

/* All the user's commitments, reconciled by the server, with current-period
   progress. Pages pick theirs out of the list (one request, shared). */
export function useCommitments() {
  return useQuery({
    queryKey: keys.commitments(),
    queryFn: async (): Promise<Commitment[]> => (await unwrap(api.GET("/api/v2/commitments/"))).commitments,
    staleTime: STALE,
  });
}

/* The commitments that apply to one context, tag, project or subproject (the
   server decides: GET /commitments/?applies_to=kind:id), in display order. */
export function useCommitmentsAppliedTo(kind: EntityKind, id: number) {
  return useQuery({
    queryKey: [...keys.commitments(), "applies", kind, id] as const,
    enabled: id > 0,
    queryFn: async (): Promise<Commitment[]> =>
      (await unwrap(api.GET("/api/v2/commitments/", { params: { query: { applies_to: `${kind}:${id}` } } }))).commitments,
    select: sortCommitments,
    staleTime: STALE,
  });
}

/* Single commitment, read fresh: carries the streak and the version that
   If-Match guards writes with. */
export function useCommitment(id: number, enabled = true) {
  return useQuery({
    queryKey: [...keys.commitments(), "detail", id] as const,
    queryFn: () => unwrap(api.GET("/api/v2/commitments/{commitment_id}", { params: { path: { commitment_id: id } } })),
    staleTime: 0,
    enabled,
  });
}

/* There is no bulk subproject listing in API v2, so this fans out over the
   projects' own lists (the same cache entries useSubprojects fills). Only
   enabled where subprojects are actually needed. */
export function useAllSubprojects(enabled: boolean) {
  const projects = useAllProjects();
  const list = projects.data ?? [];
  const results = useQueries({
    queries: list.map((project) => ({
      queryKey: keys.subprojects(project.id),
      enabled: enabled && projects.isSuccess,
      staleTime: 5 * 60_000,
      queryFn: async (): Promise<Subproject[]> =>
        (await unwrap(api.GET("/api/v2/projects/{project_id}/subprojects/", { params: { path: { project_id: project.id } } })))
          .subprojects,
    })),
  });
  const loaded = results.every((r) => r.isSuccess);
  const failed = results.find((r) => r.isError)?.error;
  const data = useMemo(() => results.flatMap((r) => r.data ?? []), [results]);
  return { subprojects: data, isPending: enabled && (projects.isPending || (!loaded && !failed)), error: failed ?? projects.error };
}

export function useCreateCommitment() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: CommitmentCreate) => unwrap(api.POST("/api/v2/commitments/", { body })),
    onSuccess: () => invalidate("commitments"),
  });
}

export function useUpdateCommitment(id: number) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ body, version }: { body: CommitmentChanges; version: number }) =>
      unwrap(
        api.PATCH("/api/v2/commitments/{commitment_id}", {
          params: { path: { commitment_id: id }, header: { "If-Match": version } },
          body,
        }),
      ),
    onSuccess: () => invalidate("commitments"),
  });
}

export function useRestartCommitment(id: number) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ keepBalance, changes, version }: { keepBalance: boolean; changes: CommitmentChanges; version: number }) =>
      unwrap(
        api.POST("/api/v2/commitments/{commitment_id}/restart/", {
          params: { path: { commitment_id: id }, header: { "If-Match": version } },
          body: { keep_balance: keepBalance, changes },
        }),
      ),
    onSuccess: () => invalidate("commitments"),
  });
}

export function useDeleteCommitment(id: number) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (version: number) =>
      unwrap(
        api.DELETE("/api/v2/commitments/{commitment_id}", {
          params: { path: { commitment_id: id }, header: { "If-Match": version } },
        }),
      ),
    onSuccess: () => invalidate("commitments"),
  });
}
