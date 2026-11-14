import { bootstrap } from "@/bootstrap";
import { csrfToken } from "@/lib/csrf";
import { isNetworkFailure, queuedOps } from "@/lib/offlineQueue";

/* A note typed on a running timer is kept on this device from the first
   keystroke until the server has it, keyed by the session's uuid (the same
   before and after a timer started offline reaches the server).

   The Timers page's editor saves its own draft while it is open. Whatever is
   left when no editor is open (typed with no signal, or the page was left
   before the autosave) is sent by syncNoteDrafts, whether the timer is still
   running or has stopped since. Nothing typed is ever dropped: if the note
   changed elsewhere in the meantime, the two are joined (mergeNote). */

export interface NoteDraft {
  uuid: string;
  /** Project name, for messages. */
  project: string;
  note: string;
  /** The server's note when the draft began. */
  base: string;
  /** When the server last said it has no such session (deleted there). The
      text is kept a while longer rather than dropped on one answer. */
  gone?: number;
}

const GONE_KEPT_MS = 30 * 24 * 60 * 60_000;

const prefix = () => `autumn:note-draft:${bootstrap().user.id}:`;

let drafts: Map<string, NoteDraft> | null = null;
const open = new Set<string>();
const listeners = new Set<() => void>();

function load(): Map<string, NoteDraft> {
  const found = new Map<string, NoteDraft>();
  try {
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (!key?.startsWith(prefix())) continue;
      try {
        const draft = JSON.parse(window.localStorage.getItem(key) ?? "") as NoteDraft;
        if (!draft?.uuid || typeof draft.note !== "string") continue;
        if (draft.gone && Date.now() - draft.gone > GONE_KEPT_MS) window.localStorage.removeItem(key);
        else found.set(draft.uuid, draft);
      } catch {
        /* one unreadable entry must not hide the rest */
      }
    }
  } catch {
    /* storage unavailable: drafts live in this tab only */
  }
  return found;
}

function all(): Map<string, NoteDraft> {
  if (!drafts) drafts = load();
  return drafts;
}

function notify() {
  for (const listener of listeners) listener();
}

if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key === null || event.key.startsWith(prefix())) {
      /* Another tab wrote; keep what only this tab holds (storage failed). */
      drafts = new Map([...(drafts ?? []), ...load()]);
      if (event.key && event.newValue === null) drafts.delete(event.key.slice(prefix().length));
      notify();
    }
  });
}

export function readNoteDraft(uuid: string | null | undefined): NoteDraft | null {
  return (uuid && all().get(uuid)) || null;
}

export function writeNoteDraft(draft: NoteDraft) {
  all().set(draft.uuid, draft);
  try {
    window.localStorage.setItem(prefix() + draft.uuid, JSON.stringify(draft));
  } catch {
    /* kept in memory */
  }
  notify();
}

export function clearNoteDraft(uuid: string | null | undefined) {
  if (!uuid || !all().delete(uuid)) return;
  try {
    window.localStorage.removeItem(prefix() + uuid);
  } catch {
    /* nothing stored */
  }
  notify();
}

/** An editor showing this timer's note saves the draft itself; returns the release. */
export function holdNoteDraft(uuid: string): () => void {
  open.add(uuid);
  notify();
  return () => {
    open.delete(uuid);
    notify();
  };
}

export function subscribeNoteDrafts(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const toSend = (draft: NoteDraft) => !open.has(draft.uuid) && !draft.gone;

/** Drafts nobody is editing: what syncNoteDrafts still has to send. */
export function waitingNoteDrafts(): number {
  let count = 0;
  for (const draft of all().values()) if (toSend(draft)) count += 1;
  return count;
}

/** What to save, given the server's note now, the note the draft started from
    and the draft. Unchanged elsewhere: the draft. Changed elsewhere: the
    server's text followed by what the draft added. */
export function mergeNote(server: string, base: string, draft: string): string {
  if (server === base || server === draft) return draft;
  const added = (draft.startsWith(base) ? draft.slice(base.length) : draft).trim();
  /* Already at the end: an earlier save went through but its reply was lost. */
  if (!added || server.trimEnd().endsWith(added)) return server;
  return server.trim() ? `${server.trimEnd()}\n\n${added}` : added;
}

async function request(method: string, url: string, body?: unknown, version?: number): Promise<{ status: number; data: unknown }> {
  try {
    const response = await fetch(url, {
      method,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
        ...(body !== undefined ? { "Content-Type": "application/json", "X-CSRFToken": csrfToken() } : {}),
        ...(version !== undefined ? { "If-Match": String(version) } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    return { status: response.status, data: await response.json().catch(() => undefined) };
  } catch {
    return { status: 0, data: undefined };
  }
}

const stop = (status: number) => isNetworkFailure(status) || status === 401 || status === 403;

export interface DraftSyncReport {
  /** Sent as typed. */
  saved: NoteDraft[];
  /** The note had changed elsewhere, so the draft's text was added to it. */
  merged: NoteDraft[];
}

let syncing: Promise<DraftSyncReport> | null = null;

/** Send every draft no editor is holding. Stops at the first one the server
    can't be reached for; the rest wait for the next call. */
export function syncNoteDrafts(): Promise<DraftSyncReport> {
  syncing ??= (async () => {
    const report: DraftSyncReport = { saved: [], merged: [] };
    type Found = { id: number; uuid?: string | null; version: number; note?: string | null };
    /* Running timers are not in the sessions list, which holds stopped ones only. */
    let running: Found[] | null = null;
    for (const draft of [...all().values()]) {
      if (!toSend(draft)) continue;
      /* Its timer started offline and isn't on the server yet. */
      if (queuedOps().some((op) => op.kind === "start" && op.uuid === draft.uuid)) continue;
      if (!running) {
        const timers = await request("GET", "/api/v2/timers/");
        if (timers.status !== 200) break;
        running = (timers.data as { timers?: Found[] }).timers ?? [];
      }
      let session = running.find((timer) => timer.uuid === draft.uuid);
      if (!session) {
        const stopped = await request("GET", `/api/v2/sessions/?uuid=${draft.uuid}&include=note&limit=1`);
        if (stopped.status !== 200) break;
        session = (stopped.data as { sessions?: Found[] }).sessions?.[0];
      }
      if (!session) {
        /* Neither running nor stopped: deleted on the server. Stop sending. */
        if (readNoteDraft(draft.uuid)?.note === draft.note) writeNoteDraft({ ...draft, gone: Date.now() });
        continue;
      }
      const server = session.note ?? "";
      const next = mergeNote(server, draft.base, draft.note);
      if (next !== server) {
        const saved = await request("PATCH", `/api/v2/sessions/${session.id}`, { note: next }, session.version);
        if (stop(saved.status)) break;
        /* 409: it changed again just now; the next pass rereads it. */
        if (saved.status < 200 || saved.status >= 300) continue;
        (next === draft.note ? report.saved : report.merged).push(draft);
      }
      /* Edited again while this was in flight: that text is still to send. */
      if (readNoteDraft(draft.uuid)?.note === draft.note && !open.has(draft.uuid)) clearNoteDraft(draft.uuid);
    }
    return report;
  })().finally(() => {
    syncing = null;
  });
  return syncing;
}

/** Test hook: forget the in-memory copy. */
export function resetNoteDraftsForTests() {
  drafts = null;
  open.clear();
  listeners.clear();
  syncing = null;
}
