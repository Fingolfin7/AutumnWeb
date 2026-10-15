import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { ApiError, errorMessage, toApiError } from "@/api/errors";
import { useToast } from "@/app/toasts";
import { insightKeys } from "./keys";
import { CHAT_PAGE_SIZE, mergeChatPages, nextChatOffset, type SelectionQuery } from "./logic";
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

/* The chat list, one server page at a time (newest first). The pages are
   merged back into the Today / Yesterday / Previous 7 days / Older groups. */
export function useInsightChats(enabled: boolean) {
  const query = useInfiniteQuery({
    queryKey: insightKeys.chats(),
    enabled,
    retry: noRetryOn4xx,
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      unwrap(api.GET("/api/v2/insights/chats/", { params: { query: { limit: CHAT_PAGE_SIZE, offset: pageParam } } })),
    getNextPageParam: (_last, pages) => nextChatOffset(pages),
    select: (data): ChatGroup[] => mergeChatPages(data.pages),
  });
  return query;
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

/* How many sessions the filters select, over what dates, and whether related
   matches were included: the header line the old page computed server-side. */
export function useInsightSelection(query: SelectionQuery, enabled: boolean) {
  return useQuery({
    queryKey: insightKeys.selection(query),
    enabled,
    staleTime: 60_000,
    retry: noRetryOn4xx,
    queryFn: () => unwrap(api.GET("/api/v2/insights/selection/", { params: { query } })),
  });
}
