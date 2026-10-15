import { useSyncExternalStore } from "react";
import type { QueryClient } from "@tanstack/react-query";
import { ApiError, toApiError } from "@/api/errors";
import { redirectToLogin } from "@/api/client";
import { csrfToken } from "@/lib/csrf";
import { insightKeys } from "./keys";
import { applyStreamEvent, failRun, isLive, startRunState, stopRun as stopped, type Run } from "./run";
import { parsePayload, readSse, type SseEvent } from "./sse";
import type { StreamRequest } from "./types";

/* The answer being streamed lives here, outside any component, because the
   page remounts when the first answer creates the chat and the URL moves from
   /insights/ to /insights/<id>/ (two routes, two elements). A run also keeps
   going if you wander off to another page and come back. */
let current: Run | null = null;
let nextId = 1;
let controller: AbortController | null = null;
const listeners = new Set<() => void>();

function set(run: Run | null) {
  current = run;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}

export function useRun(): Run | null {
  return useSyncExternalStore(subscribe, () => current);
}

export function currentRun(): Run | null {
  return current;
}

export function dismissRun(id?: number) {
  if (current && (id === undefined || current.id === id) && !isLive(current)) set(null);
}

/* A non-200 answer is either the API's JSON error or, for a refused stream,
   a single SSE `error` event. */
async function streamError(response: Response): Promise<ApiError> {
  const text = await response.text();
  if (/^\s*(event|data):/.test(text)) {
    const first = text.split(/\r?\n\r?\n/).find((block) => /^data:/m.test(block)) ?? "";
    const data = first
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    const message = parsePayload(data).message;
    return new ApiError(response.status, "stream_error", typeof message === "string" ? message : "The request failed.");
  }
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    body = undefined;
  }
  return toApiError(response.status, body);
}

/* POST /api/v2/insights/stream/. openapi-fetch cannot consume a streamed
   body, so this is a plain fetch with the CSRF header. */
export async function openStream(body: StreamRequest, signal: AbortSignal): Promise<ReadableStream<Uint8Array>> {
  let response: Response;
  try {
    response = await fetch("/api/v2/insights/stream/", {
      method: "POST",
      credentials: "same-origin",
      signal,
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": csrfToken(),
      },
      body: JSON.stringify(body),
    });
  } catch (cause) {
    if (signal.aborted) throw cause;
    throw new ApiError(0, "network", "Can't reach Autumn. Check your connection.", cause);
  }
  if (response.status === 401) redirectToLogin();
  if (!response.ok) throw await streamError(response);
  if (!response.body) throw new ApiError(response.status, "no_body", "The server sent no stream.");
  return response.body;
}

export interface StartArgs {
  client: QueryClient;
  body: StreamRequest;
  /** Visible messages in the chat now (0 for a new chat). */
  baseCount: number;
  /** "provider:model" the chat will be stored with, to seed a new chat's cache. */
  chatModel: string;
  /** The filters sent, to seed a new chat's cache. */
  seedFilters: Record<string, unknown>;
}

/* Begin answering. Resolves when the stream has ended, however it ended. */
export async function startRun({ client, body, baseCount, chatModel, seedFilters }: StartArgs): Promise<void> {
  controller?.abort();
  const abort = new AbortController();
  controller = abort;
  let run = startRunState({
    id: nextId++,
    chatId: body.chat_id ?? null,
    prompt: body.message,
    model: body.model ?? "",
    baseCount,
  });
  const id = run.id;
  set(run);

  const update = (next: Run) => {
    run = next;
    if (current?.id === id) set(next);
  };

  const refresh = (chatId: string | null) => {
    void client.invalidateQueries({ queryKey: insightKeys.chats() });
    return chatId ? client.invalidateQueries({ queryKey: insightKeys.chat(chatId) }) : Promise.resolve();
  };

  const onEvent = (event: SseEvent) => {
    const payload = parsePayload(event.data);
    const before = run.chatId;
    update(applyStreamEvent(run, event.event, payload));
    if (event.event === "chat" && run.chatId && !before) {
      /* The chat exists on the server now: put a stub in the cache so the
         page that takes over at /insights/<id>/ opens instantly. */
      const now = new Date().toISOString();
      client.setQueryData(insightKeys.chat(run.chatId), {
        id: run.chatId,
        title: "New Chat",
        model: chatModel,
        filters: seedFilters,
        created_at: now,
        updated_at: now,
        messages: [],
      });
      void client.invalidateQueries({ queryKey: insightKeys.chats() });
    }
  };

  try {
    const stream = await openStream(body, abort.signal);
    await readSse(stream, onEvent);
    if (isLive(run)) {
      update(abort.signal.aborted ? stopped(run) : { ...run, status: "error", text: run.text || "The stream ended before an answer arrived." });
    }
  } catch (error) {
    if (abort.signal.aborted) update(stopped(run));
    else update(failRun(run, error instanceof Error ? error.message : "Streaming failed."));
  } finally {
    if (controller === abort) controller = null;
    const finished = run;
    await refresh(finished.chatId);
    /* A saved answer is in the chat's own data now; let the run go. */
    if (finished.status === "done") dismissRun(id);
  }
}

/* Stop reading. The server finishes and saves what it was asked, so the chat
   shows the full answer next time it is opened. */
export function stopStream() {
  controller?.abort();
}
