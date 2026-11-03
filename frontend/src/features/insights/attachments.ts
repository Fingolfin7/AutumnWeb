import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, toApiError } from "@/api/errors";
import { redirectToLogin } from "@/api/client";
import { csrfToken } from "@/lib/csrf";
import type { components } from "@/api/schema";

/* Files added to the question being written. Each uploads as soon as it is
   added, so Send only has to name the ids; the server extracts what the
   models need (llm_insights/attachments.py). */

export type AttachmentKind = components["schemas"]["InsightAttachmentKindEnum"];
export type SavedAttachment = components["schemas"]["InsightAttachment"];

/** What a message shows for one of its files. */
export interface AttachmentView {
  name: string;
  kind: AttachmentKind;
  size: number;
  url: string;
}

export interface Draft {
  key: string;
  name: string;
  size: number;
  kind: AttachmentKind;
  /** A local object URL while an image uploads, so its thumbnail is instant. */
  preview: string | null;
  status: "uploading" | "ready" | "error";
  /** 0..1 while uploading. */
  progress: number;
  error?: string;
  saved?: SavedAttachment;
}

export const MAX_FILES = 5;
export const MAX_FILE_BYTES = 10 * 1024 * 1024;
export const ACCEPT = "image/png,image/jpeg,image/webp,image/gif,.pdf,.docx,.txt,.md,.markdown,.csv,.tsv,.json,.log,.vtt,.srt";

export function kindOf(file: { name: string; type: string }): AttachmentKind {
  if (file.type.startsWith("image/")) return "image";
  if (file.type === "application/pdf" || /\.pdf$/i.test(file.name)) return "pdf";
  return "text";
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/* Pasted screenshots arrive as "image.png": give them a name worth keeping. */
export function nameFor(file: File, now = new Date()): string {
  if (file.name && file.name !== "image.png") return file.name;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `Screenshot ${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}.${pad(now.getMinutes())}.${pad(now.getSeconds())}.png`;
}

/* The server's reason for refusing a file, without the "file:" field label. */
function uploadError(status: number, body: unknown): string {
  const error = toApiError(status, body);
  const details = error.details as Record<string, unknown> | undefined;
  const file = details && Array.isArray(details.file) ? details.file.join(" ") : "";
  return file || error.message;
}

/* XMLHttpRequest rather than fetch: fetch can't report upload progress. */
export function uploadAttachment(file: File, name: string, onProgress: (fraction: number) => void, signal: AbortSignal): Promise<SavedAttachment> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file, name);
    xhr.open("POST", "/api/v2/insights/attachments/");
    xhr.withCredentials = true;
    xhr.setRequestHeader("X-CSRFToken", csrfToken());
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = undefined;
      }
      if (xhr.status === 401) redirectToLogin();
      if (xhr.status === 201 && body) resolve(body as SavedAttachment);
      else reject(new ApiError(xhr.status, "upload", uploadError(xhr.status, body)));
    };
    xhr.onerror = () => reject(new ApiError(0, "network", "Can't reach Autumn. Check your connection."));
    xhr.onabort = () => reject(new DOMException("Aborted", "AbortError"));
    signal.addEventListener("abort", () => xhr.abort());
    xhr.send(form);
  });
}

function discard(saved: SavedAttachment) {
  void fetch(saved.url, {
    method: "DELETE",
    credentials: "same-origin",
    headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
  }).catch(() => {
    /* best effort: the server sweeps unsent files after a day */
  });
}

let nextKey = 1;

export function useAttachmentDrafts(onRejected: (message: string) => void) {
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const live = useRef(new Map<string, AbortController>());
  const latest = useRef(drafts);
  latest.current = drafts;

  const patch = useCallback((key: string, change: Partial<Draft>) => {
    setDrafts((list) => list.map((d) => (d.key === key ? { ...d, ...change } : d)));
  }, []);

  const add = useCallback(
    (files: File[]) => {
      const room = MAX_FILES - latest.current.length;
      if (files.length > room) onRejected(room > 0 ? `Up to ${MAX_FILES} files per message: ${files.length - room} not added.` : `Up to ${MAX_FILES} files per message.`);
      const added: Draft[] = [];
      for (const file of files.slice(0, Math.max(room, 0))) {
        const key = `draft-${nextKey++}`;
        const kind = kindOf(file);
        const name = nameFor(file);
        const draft: Draft = { key, name, size: file.size, kind, preview: kind === "image" ? URL.createObjectURL(file) : null, status: "uploading", progress: 0 };
        if (file.size > MAX_FILE_BYTES) {
          added.push({ ...draft, status: "error", error: `${formatSize(file.size)} is over the 10 MB limit.` });
          continue;
        }
        added.push(draft);
        const abort = new AbortController();
        live.current.set(key, abort);
        uploadAttachment(file, name, (progress) => patch(key, { progress }), abort.signal)
          .then((saved) => patch(key, { status: "ready", progress: 1, saved, name: saved.name, size: saved.size }))
          .catch((error: unknown) => {
            if (abort.signal.aborted) return;
            patch(key, { status: "error", error: error instanceof Error ? error.message : "Upload failed." });
          })
          .finally(() => live.current.delete(key));
      }
      if (added.length) setDrafts((list) => [...list, ...added]);
    },
    [onRejected, patch],
  );

  const remove = useCallback((key: string) => {
    const draft = latest.current.find((d) => d.key === key);
    if (!draft) return;
    live.current.get(key)?.abort();
    if (draft.saved) discard(draft.saved);
    if (draft.preview) URL.revokeObjectURL(draft.preview);
    setDrafts((list) => list.filter((d) => d.key !== key));
  }, []);

  /* After Send: the files now belong to the message, so nothing is deleted. */
  const clear = useCallback(() => {
    for (const draft of latest.current) if (draft.preview) URL.revokeObjectURL(draft.preview);
    setDrafts([]);
  }, []);

  /* Leaving the page with unsent uploads: stop them and drop what was stored. */
  useEffect(
    () => () => {
      for (const abort of live.current.values()) abort.abort();
      for (const draft of latest.current) {
        if (draft.saved) discard(draft.saved);
        if (draft.preview) URL.revokeObjectURL(draft.preview);
      }
    },
    [],
  );

  const ready = drafts.filter((d) => d.status === "ready" && d.saved);
  return {
    drafts,
    add,
    remove,
    clear,
    uploading: drafts.some((d) => d.status === "uploading"),
    ids: ready.map((d) => d.saved!.id),
    views: ready.map((d): AttachmentView => ({ name: d.saved!.name, kind: d.saved!.kind, size: d.saved!.size, url: d.saved!.url })),
  };
}

/* Files from a paste or a drop. */
export function filesFrom(data: DataTransfer | null): File[] {
  if (!data) return [];
  return Array.from(data.files ?? []);
}
