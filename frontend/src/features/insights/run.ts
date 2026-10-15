import type { Source, Usage } from "./types";

/* One question being answered. The event names and payloads are exactly the
   ones the old stream_insights view emitted (insights_stream.js):

     chat   {chat_id, chat_url, stream_url}        the chat exists now
     delta  {content}                              a fragment of the answer
     done   {content, html, sources, usage, model, chat_title, error?}
     error  {message}                              the stream itself broke

   `done` with an `error` field is a failed answer the server did save. */
export type RunStatus = "streaming" | "done" | "error" | "stopped";

export interface Run {
  id: number;
  /** null until the first `chat` event on a new chat. */
  chatId: string | null;
  prompt: string;
  /** The answer so far (plain text while streaming). */
  text: string;
  /** Server-rendered markdown of the final answer. */
  html: string | null;
  status: RunStatus;
  model: string;
  sources: Source[];
  usage: Usage | null;
  /** Visible messages the chat had when this run started; the run is hidden
      once the chat holds more, i.e. once the saved copy has arrived. */
  baseCount: number;
}

export function startRunState(args: { id: number; chatId: string | null; prompt: string; model: string; baseCount: number }): Run {
  return { ...args, text: "", html: null, status: "streaming", sources: [], usage: null };
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function applyStreamEvent(run: Run, event: string, payload: Record<string, unknown>): Run {
  switch (event) {
    case "chat":
      return typeof payload.chat_id === "string" ? { ...run, chatId: payload.chat_id } : run;
    case "delta":
      return { ...run, text: run.text + str(payload.content) };
    case "done": {
      const content = str(payload.content) || run.text;
      return {
        ...run,
        chatId: typeof payload.chat_id === "string" ? payload.chat_id : run.chatId,
        text: content,
        html: str(payload.html) || null,
        status: payload.error ? "error" : "done",
        model: str(payload.model) || run.model,
        sources: Array.isArray(payload.sources) ? (payload.sources as Source[]) : [],
        usage: payload.usage && typeof payload.usage === "object" ? (payload.usage as Usage) : null,
      };
    }
    case "error": {
      const message = str(payload.message) || "Streaming failed.";
      return { ...run, text: run.text ? `${run.text}\n\n${message}` : message, html: null, status: "error" };
    }
    default:
      return run;
  }
}

/* The stream failed before or while reading (network, HTTP error). */
export function failRun(run: Run, message: string): Run {
  const text = `Error: ${message}`;
  return { ...run, text: run.text ? `${run.text}\n\n${text}` : text, html: null, status: "error" };
}

export function stopRun(run: Run): Run {
  return run.status === "streaming" ? { ...run, status: "stopped" } : run;
}

export function isLive(run: Run): boolean {
  return run.status === "streaming";
}

/* Should this run's exchange be drawn in the chat open on screen? `chatId` is
   the open chat (undefined on the new-chat page); `saved` the number of
   visible messages the server returned for it. */
export function showsRun(run: Run, chatId: string | undefined, saved: number): boolean {
  const mine = chatId ? run.chatId === chatId : run.chatId === null;
  return mine && saved <= run.baseCount;
}
