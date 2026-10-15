import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { ApiError, errorMessage, toApiError } from "@/api/errors";
import { useToast } from "@/app/toasts";
import { parseRelatedHeader } from "@/features/charts/api";
import { insightKeys } from "./keys";
import type { ChatDetail, ChatGroup, InsightOptions } from "./types";

/* A 403 here means the account has no AI provider key (or AI is switched off):
   retrying will not change that. */
const noRetryOn4xx = (count: number, error: unknown) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2;

export function useInsightOptions(enabled: boolean) {
  return useQuery({
    queryKey: insightKeys.options(),
    enabled,
    staleTime: 5 * 60_000,
    retry: noRetryOn4xx,
    queryFn: (): Promise<InsightOptions> => unwrap(api.GET("/api/v2/insights/options/")),
  });
}

export function useInsightChats(enabled: boolean) {
  return useQuery({
    queryKey: insightKeys.chats(),
    enabled,
    retry: noRetryOn4xx,
    queryFn: async (): Promise<ChatGroup[]> => (await unwrap(api.GET("/api/v2/insights/chats/"))).groups,
  });
}

export function useInsightChat(chatId: string | undefined) {
  return useQuery({
    queryKey: insightKeys.chat(chatId ?? ""),
    enabled: !!chatId,
    retry: noRetryOn4xx,
    queryFn: (): Promise<ChatDetail> => unwrap(api.GET("/api/v2/insights/chats/{chat_id}", { params: { path: { chat_id: chatId! } } })),
  });
}

export function useDeleteChat() {
  const client = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: async (chatId: string) => {
      const result = await api.DELETE("/api/v2/insights/chats/{chat_id}", { params: { path: { chat_id: chatId } } });
      if (!result.response.ok) throw toApiError(result.response.status, result.error);
    },
    onSuccess: (_data, chatId) => {
      client.removeQueries({ queryKey: insightKeys.chat(chatId) });
      toast.success("Chat deleted.");
    },
    onError: (error) => toast.error(`Couldn't delete the chat: ${errorMessage(error)}`),
    onSettled: () => client.invalidateQueries({ queryKey: insightKeys.chats() }),
  });
}

export interface SelectionPreview {
  count: number;
  /** Start of the earliest and end of the latest selected session. */
  earliest: string | null;
  latest: string | null;
  related: "included" | "unavailable" | null;
}

const EMPTY_PREVIEW: SelectionPreview = { count: 0, earliest: null, latest: null, related: null };

/* How many sessions the filters select, and over what span: the header line
   the old page computed server-side. Two one-row reads of the sessions list
   (newest, then the last one). */
async function fetchPreview(query: Record<string, string | boolean>): Promise<SelectionPreview> {
  const params = { ...query, active: false, ordering: "newest" as const, limit: 1 };
  const first = await api.GET("/api/v2/sessions/", { params: { query: params } });
  if (!first.response.ok) throw toApiError(first.response.status, first.error);
  const total = first.data?.total ?? 0;
  const related = parseRelatedHeader(first.response.headers.get("X-Autumn-Related"));
  if (!total) return { ...EMPTY_PREVIEW, related };
  const latest = first.data?.sessions[0]?.end ?? null;
  let earliest = first.data?.sessions[0]?.start ?? null;
  if (total > 1) {
    const last = await api.GET("/api/v2/sessions/", { params: { query: { ...params, offset: total - 1 } } });
    if (last.response.ok) earliest = last.data?.sessions[0]?.start ?? earliest;
  }
  return { count: total, earliest, latest, related };
}

export function useSelectionPreview(query: Record<string, string | boolean> | null, enabled: boolean) {
  return useQuery({
    queryKey: insightKeys.preview(query ?? { none: true }),
    enabled,
    staleTime: 60_000,
    retry: noRetryOn4xx,
    queryFn: (): Promise<SelectionPreview> => (query ? fetchPreview(query) : Promise.resolve(EMPTY_PREVIEW)),
  });
}
