import { bootstrap } from "@/bootstrap";
import { csrfToken } from "@/lib/csrf";

/* Timer starts and stops made while Autumn can't be reached (no signal at the
   gym, the server waking from sleep) are kept here and replayed in order once
   it answers. Both carry their own instants, so the record is what you tapped,
   not when it synced. A start carries a client uuid the server deduplicates
   on, so replaying it twice (two tabs, a retry after a lost response) never
   makes two timers; a stop of an already-stopped timer is answered 404/409
   and simply dropped. */

export interface QueuedStart {
  kind: "start";
  key: string;
  uuid: string;
  queuedAt: string;
  /** The POST /api/v2/timers/ body, with its own start instant and uuid. */
  body: { project_id: number; start: string; uuid: string; [field: string]: unknown };
  /** For showing the card before the server knows about it. */
  display: { projectName: string; subprojects: { id: number; name: string }[] };
}

export interface QueuedStop {
  kind: "stop";
  key: string;
  queuedAt: string;
  /** A server id, or the uuid of a start still in this queue. */
  target: { id: number } | { uuid: string };
  end: string;
  note?: string | null;
  subproject_allocations?: { subproject_id: number; allocation_bp: number }[];
}

export type QueuedOp = QueuedStart | QueuedStop;

interface QueueState {
  ops: QueuedOp[];
  /** uuid -> server id for starts that synced, so later stops can find them. */
  synced: Record<string, number>;
}

export interface FlushReport {
  synced: number;
  dropped: { op: QueuedOp; status: number; message: string }[];
  /** Still waiting: the server couldn't be reached. */
  remaining: number;
}

const storageKey = () => `autumn:offline-queue:${bootstrap().user.id}`;

// Each operation has its own key: concurrent tabs never replace a shared
// array when enqueueing. Failed writes stay overlaid in memory until saved.
const entryPrefix = () => `${storageKey()}:entry:`;
const pendingWrites = new Map<string, string | null>();
let storageFailed = false;
let migratedLegacy: string | null = null;
let state: QueueState | null = null;
const listeners = new Set<() => void>();

function persist(key: string, value: string | null) {
  pendingWrites.set(key, value);
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
    pendingWrites.delete(key);
  } catch {
    storageFailed = true;
  }
}

function entries(s: QueueState): Map<string, string> {
  return new Map([
    ...s.ops.map((op): [string, string] => [`${entryPrefix()}op:${op.key}`, JSON.stringify(op)]),
    ...Object.entries(s.synced).map(([uuid, id]): [string, string] => [`${entryPrefix()}id:${uuid}`, JSON.stringify(id)]),
  ]);
}

function read(): QueueState {
  const values = new Map<string, string>();
  try {
    // Upgrade existing queues without changing operation keys. Delete the old
    // value only after every new entry was durably written.
    const legacy = window.localStorage.getItem(storageKey());
    if (legacy && legacy !== migratedLegacy) {
      const parsed = JSON.parse(legacy) as QueueState;
      if (Array.isArray(parsed.ops)) {
        for (const [key, value] of entries({ ops: parsed.ops, synced: parsed.synced ?? {} })) {
          if (window.localStorage.getItem(key) === null) persist(key, value);
        }
        migratedLegacy = legacy;
      }
    }
    for (const [key, value] of pendingWrites) persist(key, value);
    if (legacy && migratedLegacy === legacy && !pendingWrites.size) persist(storageKey(), null);
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (key?.startsWith(entryPrefix())) {
        const value = window.localStorage.getItem(key);
        if (value !== null) values.set(key, value);
      }
    }
    storageFailed = pendingWrites.size > 0;
  } catch {
    storageFailed = true;
    // Keep the last known queue if even reading storage is unavailable.
    if (state) for (const [key, value] of entries(state)) values.set(key, value);
  }
  for (const [key, value] of pendingWrites) {
    if (value === null) values.delete(key);
    else values.set(key, value);
  }
  const result: QueueState = { ops: [], synced: {} };
  for (const [key, value] of values) {
    try {
      if (key.startsWith(`${entryPrefix()}op:`)) result.ops.push(JSON.parse(value) as QueuedOp);
      else if (key.startsWith(`${entryPrefix()}id:`)) result.synced[key.slice(`${entryPrefix()}id:`.length)] = JSON.parse(value) as number;
    } catch { /* Ignore an individually corrupt entry, preserving the rest. */ }
  }
  result.ops.sort((a, b) => a.queuedAt.localeCompare(b.queuedAt) ||
    (a.kind === b.kind ? a.key.localeCompare(b.key) : a.kind === "start" ? -1 : 1));
  return result;
}

function current(): QueueState {
  if (!state) state = read();
  return state;
}

function refresh(): QueueState {
  state = read();
  return state;
}

function write(next: QueueState) {
  const before = entries(current());
  const after = entries(next);
  // Write only changed entries. Never remove another tab's newly added op.
  for (const [key, value] of after) if (before.get(key) !== value) persist(key, value);
  for (const key of before.keys()) if (!after.has(key)) persist(key, null);
  state = next;
  storageFailed = pendingWrites.size > 0;
  for (const listener of listeners) listener();
}

export function hasUnsavedChanges(): boolean {
  return storageFailed && current().ops.length > 0;
}

if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key === null || event.key === storageKey() || event.key.startsWith(entryPrefix())) {
      refresh();
      for (const listener of listeners) listener();
    }
  });
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function queuedOps(): QueuedOp[] {
  return current().ops;
}

const newKey = () => crypto.randomUUID();

export function enqueueStart(op: Omit<QueuedStart, "kind" | "key" | "queuedAt">): QueuedStart {
  const item: QueuedStart = { ...op, kind: "start", key: newKey(), queuedAt: new Date().toISOString() };
  const s = refresh();
  write({ ...s, ops: [...s.ops, item] });
  return item;
}

export function enqueueStop(op: Omit<QueuedStop, "kind" | "key" | "queuedAt">): QueuedStop {
  const item: QueuedStop = { ...op, kind: "stop", key: newKey(), queuedAt: new Date().toISOString() };
  const s = refresh();
  write({ ...s, ops: [...s.ops, item] });
  return item;
}

/** Drop a start that never reached the server (the user removed the timer),
    with any stop queued for it. */
export function cancelStart(uuid: string) {
  const s = refresh();
  write({
    ...s,
    ops: s.ops.filter((op) => !(op.kind === "start" && op.uuid === uuid) && !(op.kind === "stop" && "uuid" in op.target && op.target.uuid === uuid)),
  });
}

/** Correct the start instant of a start that hasn't synced yet. */
export function updateQueuedStart(uuid: string, start: string) {
  const s = refresh();
  write({
    ...s,
    ops: s.ops.map((op) => (op.kind === "start" && op.uuid === uuid ? { ...op, body: { ...op.body, start } } : op)),
  });
}

/** Timers as the server reported them, adjusted for what's still queued:
    queued starts appear (marked pending_sync), queued stops disappear. */
export function overlayTimers<T extends { id: number; uuid?: string | null }>(
  timers: T[],
  makePending: (op: QueuedStart) => T,
): T[] {
  const { ops, synced } = current();
  const stoppedIds = new Set<number>();
  const stoppedUuids = new Set<string>();
  for (const op of ops) {
    if (op.kind !== "stop") continue;
    if ("id" in op.target) stoppedIds.add(op.target.id);
    else {
      stoppedUuids.add(op.target.uuid);
      if (synced[op.target.uuid]) stoppedIds.add(synced[op.target.uuid]!);
    }
  }
  const known = new Set(timers.map((t) => t.uuid).filter(Boolean));
  const out = timers.filter((t) => !stoppedIds.has(t.id) && !(t.uuid && stoppedUuids.has(t.uuid)));
  for (const op of ops) {
    if (op.kind === "start" && !known.has(op.uuid) && !stoppedUuids.has(op.uuid)) out.push(makePending(op));
  }
  return out;
}

export function isNetworkFailure(status: number) {
  return status === 0 || status === 408 || status === 429 || (status >= 500 && status < 600);
}

interface PostResult { status: number; data: unknown; retryAt?: number }

async function post(url: string, body: unknown): Promise<PostResult> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": csrfToken(),
      },
      body: JSON.stringify(body),
    });
  } catch {
    return { status: 0, data: undefined };
  }
  const data = await response.json().catch(() => undefined);
  const retryAfter = response.headers.get("Retry-After");
  const seconds = retryAfter === null ? NaN : Number(retryAfter);
  const retryAt = retryAfter === null ? undefined :
    Number.isFinite(seconds) ? Date.now() + Math.max(0, seconds) * 1000 : Date.parse(retryAfter);
  return { status: response.status, data, retryAt };
}

function messageOf(data: unknown): string {
  const error = (data as { error?: { message?: string } } | undefined)?.error;
  return error?.message ?? "The server refused it.";
}

let flushing: Promise<FlushReport> | null = null;
let retryAt = 0;

export function isFlushing(): boolean {
  return flushing !== null;
}

/** Replay the queue in order. Stops at the first op the server can't be
    reached for; drops (and reports) ops the server rejects. */
export function flushQueue(): Promise<FlushReport> {
  if (!flushing) {
    const run = async (): Promise<FlushReport> => {
      const report: FlushReport = { synced: 0, dropped: [], remaining: 0 };
      for (;;) {
        const s = refresh();
        if (Date.now() < retryAt) break;
        const op = s.ops[0];
        if (!op) break;
        let result: PostResult;
        let syncedId: number | undefined;
        if (op.kind === "start") {
          result = await post("/api/v2/timers/", op.body);
          syncedId = (result.data as { id?: number } | undefined)?.id;
        } else {
          const id = "id" in op.target ? op.target.id : s.synced[op.target.uuid];
          if (id === undefined) {
            /* Its start was rejected, so there is nothing to stop. */
            write({ ...s, ops: s.ops.slice(1) });
            continue;
          }
          result = await post(`/api/v2/timers/${id}/stop/`, {
            end: op.end,
            ...(op.note !== undefined ? { note: op.note } : {}),
            ...(op.subproject_allocations ? { subproject_allocations: op.subproject_allocations } : {}),
          });
        }
        if (isNetworkFailure(result.status) || result.status === 401 || result.status === 403) {
          /* Offline, temporary server failure, or signed out: keep everything. */
          if (result.retryAt && Number.isFinite(result.retryAt)) retryAt = result.retryAt;
          break;
        }
        const after = refresh();
        const synced = { ...after.synced };
        if (result.status >= 200 && result.status < 300) {
          report.synced += 1;
          if (op.kind === "start" && syncedId) synced[op.uuid] = syncedId;
        } else if (!(op.kind === "stop" && (result.status === 404 || result.status === 409))) {
          report.dropped.push({ op, status: result.status, message: messageOf(result.data) });
        }
        const ops = after.ops.filter((o) => o.key !== op.key);
        /* Forget uuid mappings nothing queued refers to any more. */
        const wanted = new Set(ops.flatMap((o) => (o.kind === "stop" && "uuid" in o.target ? [o.target.uuid] : [])));
        for (const uuid of Object.keys(synced)) if (!wanted.has(uuid)) delete synced[uuid];
        write({ ops, synced });
      }
      report.remaining = current().ops.length;
      for (const listener of listeners) listener();
      return report;
    };
    /* One tab replays at a time; the others wait, then find it empty. */
    const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
    const pending: Promise<FlushReport> = locks ? (locks.request("autumn-offline-queue", run) as unknown as Promise<FlushReport>) : run();
    flushing = pending.finally(() => {
      flushing = null;
    });
    return flushing;
  }
  return flushing;
}

/** Test hook: forget the in-memory copy. */
export function resetQueueForTests() {
  state = null;
  pendingWrites.clear();
  storageFailed = false;
  migratedLegacy = null;
  retryAt = 0;
  listeners.clear();
}
