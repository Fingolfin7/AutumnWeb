import { useMutation } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { useInvalidate } from "@/api/sync";
import { useContexts, useTags } from "@/api/meta";
import type { Context, Tag } from "@/api/types";

/* Contexts and tags have no single-record read in API v2, so a detail page
   finds its record in the (cached, shared) list. `missing` means a fresh list
   loaded and the id is not in it: deleted elsewhere, or never yours. */
export function useContextById(id: number) {
  const query = useContexts();
  const item: Context | undefined = query.data?.find((context) => context.id === id);
  return { query, item, missing: query.isSuccess && !query.isFetching && !item };
}

export function useTagById(id: number) {
  const query = useTags();
  const item: Tag | undefined = query.data?.find((tag) => tag.id === id);
  return { query, item, missing: query.isSuccess && !query.isFetching && !item };
}

/* Context and tag lists feed pickers, filters and the commitment form, and a
   rename changes what commitments and projects show, so every write
   refreshes the whole "meta" family here and in other tabs. The header's
   context switcher is seeded from the bootstrap blob and is not part of
   this (see report). */
export function useCreateContext() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { name: string; description: string | null }) =>
      unwrap(api.POST("/api/v2/contexts/", { body })),
    onSuccess: () => invalidate("meta"),
  });
}

export function useUpdateContext(id: number) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { name: string; description: string | null }) =>
      unwrap(api.PATCH("/api/v2/contexts/{context_id}", { params: { path: { context_id: id } }, body })),
    onSuccess: () => invalidate("meta", "commitments"),
  });
}

export function useDeleteContext() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/api/v2/contexts/{context_id}", { params: { path: { context_id: id } } })),
    onSuccess: () => invalidate("meta", "commitments", "sessions"),
  });
}

export function useCreateTag() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { name: string; color: string | null }) => unwrap(api.POST("/api/v2/tags/", { body })),
    onSuccess: () => invalidate("meta"),
  });
}

export function useUpdateTag(id: number) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { name: string; color: string | null }) =>
      unwrap(api.PATCH("/api/v2/tags/{tag_id}", { params: { path: { tag_id: id } }, body })),
    onSuccess: () => invalidate("meta", "commitments"),
  });
}

export function useDeleteTag() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/api/v2/tags/{tag_id}", { params: { path: { tag_id: id } } })),
    onSuccess: () => invalidate("meta", "commitments", "sessions"),
  });
}
