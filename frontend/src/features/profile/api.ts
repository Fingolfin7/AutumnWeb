import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, requestJson, unwrap } from "@/api/client";
import { ApiError, toApiError } from "@/api/errors";
import { keys } from "@/api/keys";
import { filenameFromDisposition, saveBlob } from "@/features/import-export/download";
import type { components } from "@/api/schema";
import type { Account, AccountPatch, KeyProvider, Prefs, PrefsPatch } from "./model";

type S = components["schemas"];
export type ChatGPTLogin = S["ChatGPTLogin"];
export type SocialAccount = S["SocialAccount"];
export type SocialAccounts = S["SocialAccounts"];
export type MediaStatus = S["MediaStatus"];

export const meKeys = {
  account: () => ["me", "account"] as const,
  social: () => ["me", "social-accounts"] as const,
  chatgpt: () => ["me", "chatgpt-login"] as const,
};

/* The profile page edits these, so it always shows fresh values on open. */
export function useAccount() {
  return useQuery({
    queryKey: meKeys.account(),
    queryFn: (): Promise<Account> => unwrap(api.GET("/api/v2/me/account/")),
    staleTime: 0,
  });
}

export const fetchPreferences = (): Promise<Prefs> => unwrap(api.GET("/api/v2/me/preferences/"));

export function useProfilePreferences() {
  return useQuery({
    queryKey: keys.preferences(),
    queryFn: fetchPreferences,
    staleTime: 0,
  });
}

export function useSocialAccounts() {
  return useQuery({
    queryKey: meKeys.social(),
    queryFn: (): Promise<SocialAccounts> => unwrap(api.GET("/api/v2/me/social-accounts/")),
    staleTime: 0,
  });
}

/* Codex (ChatGPT) device login. While a code is waiting, asking again polls
   OpenAI for the result, so poll at the interval the server suggests. */
export function useChatGPTLogin(enabled: boolean) {
  return useQuery({
    queryKey: meKeys.chatgpt(),
    enabled,
    queryFn: (): Promise<ChatGPTLogin> => unwrap(api.GET("/api/v2/me/chatgpt-login/")),
    staleTime: 0,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.status === "pending" ? Math.max(5, query.state.data.interval ?? 5) * 1000 : false,
  });
}

export const patchAccount = (body: AccountPatch): Promise<Account> =>
  unwrap(api.PATCH("/api/v2/me/account/", { body }));

export const patchPreferences = (body: PrefsPatch): Promise<Prefs> =>
  unwrap(api.PATCH("/api/v2/me/preferences/", { body }));

function imageForm(file: File): FormData {
  const form = new FormData();
  form.append("image", file);
  return form;
}

export const uploadAvatar = (file: File) => requestJson<MediaStatus>("PUT", "/api/v2/me/avatar/", imageForm(file));
export const removeAvatar = (): Promise<MediaStatus> => unwrap(api.DELETE("/api/v2/me/avatar/"));
export const uploadBackground = (file: File) =>
  requestJson<MediaStatus>("PUT", "/api/v2/me/background/", imageForm(file));
export const removeBackground = (): Promise<MediaStatus> => unwrap(api.DELETE("/api/v2/me/background/"));

export const putApiKey = (provider: KeyProvider, key: string) =>
  unwrap(
    api.PUT("/api/v2/me/api-keys/{provider}", {
      params: { path: { provider } },
      body: { key },
    }),
  );
export const deleteApiKey = (provider: KeyProvider) =>
  unwrap(api.DELETE("/api/v2/me/api-keys/{provider}", { params: { path: { provider } } }));

export const startChatGPTLogin = (): Promise<ChatGPTLogin> => unwrap(api.POST("/api/v2/me/chatgpt-login/"));
export const disconnectChatGPT = (): Promise<ChatGPTLogin> => unwrap(api.DELETE("/api/v2/me/chatgpt-login/"));

export const disconnectSocial = async (provider: string): Promise<void> => {
  await unwrap(api.DELETE("/api/v2/me/social-accounts/{provider}", { params: { path: { provider } } }));
};

/* The download endpoint answers with the file, or with a JSON error when
   there is nothing to download, so fetch it rather than navigate to it. */
export async function downloadBackground(): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/v2/me/background/download/", {
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
  } catch (cause) {
    throw new ApiError(0, "network", "Can't reach Autumn. Check your connection.", cause);
  }
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = undefined;
    }
    throw toApiError(response.status, body);
  }
  const blob = await response.blob();
  saveBlob(blob, filenameFromDisposition(response.headers.get("Content-Disposition")) ?? "background");
}

/* Fire once when a pending Codex login turns into a connected one. */
export function useOnCodexConnected(login: ChatGPTLogin | undefined, onConnected: () => void) {
  const previous = useRef<string | undefined>(undefined);
  const qc = useQueryClient();
  useEffect(() => {
    if (previous.current === "pending" && login?.status === "connected") {
      void qc.invalidateQueries({ queryKey: keys.preferences() });
      onConnected();
    }
    previous.current = login?.status;
  }, [login?.status, onConnected, qc]);
}
