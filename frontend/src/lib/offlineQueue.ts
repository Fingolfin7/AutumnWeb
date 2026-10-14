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

function read(): QueueState {
  try {
    const raw = window.localStorage.getItem(storageKey());
    if (raw) {
      const parsed = JSON.parse(raw) as QueueState;
      if (Array.isArray(parsed.ops)) return { ops: parsed.ops, synced: parsed.synced ?? {} };
    }
  } catch {
    /* storage unavailable or corrupt: start empty */
  }
  return { ops: [], synced: {} };
}

let state: QueueState | null = null;
const listeners = new Set<() => void>();

function current(): QueueState {
  if (!state) state = read();
  return state;
}

function write(next: QueueState) {
  state = next;
  try {
    if (next.ops.length || Object.keys(next.synced).length) {
      window.localStorage.setItem(storageKey(), JSON.stringify(next));
    } else {
      window.localStorage.removeItem(storageKey());
    }
  } catch {
    /* quota or private mode: the queue still lives for this page */
  }
  for (const listener of listeners) listener();
}

/* Another tab changed the queue (it enqueued, or flushed it). */
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key === storageKey()) {
      state = null;
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
  const s = current();
  write({ ...s, ops: [...s.ops, item] });
  return item;
}

export function enqueueStop(op: Omit<QueuedStop, "kind" | "key" | "queuedAt">): QueuedStop {
  const item: QueuedStop = { ...op, kind: "stop", key: newKey(), queuedAt: new Date().toISOString() };
  const s = current();
  write({ ...s, ops: [...s.ops, item] });
  return item;
}

/** Drop a start that never reached the server (the user removed the timer),
    with any stop queued for it. */
export function cancelStart(uuid: string) {
  const s = current();
  write({
    ...s,
    ops: s.ops.filter((op) => !(op.kind === "start" && op.uuid === uuid) && !(op.kind === "stop" && "uuid" in op.target && op.target.uuid === uuid)),
  });
}

/** Correct the start instant of a start that hasn't synced yet. */
export function updateQueuedStart(uuid: string, start: string) {
  const s = current();
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
  return status === 0 || status === 502 || status === 503 || status === 504;
}

async function post(url: string, body: unknown): Promise<{ status: number; data: unknown }> {
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
  return { status: response.status, data };
}

function messageOf(data: unknown): string {
  const error = (data as { error?: { message?: string } } | undefined)?.error;
  return error?.message ?? "The server refused it.";
}

let flushing: Promise<FlushReport> | null = null;

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
        state = null; /* another tab may have flushed part of it */
        const s = current();
        const op = s.ops[0];
        if (!op) break;
        let result: { status: number; data: unknown };
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
          /* Offline, asleep, or signed out: keep everything for later. */
          break;
        }
        const after = current();
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
  listeners.clear();
}
