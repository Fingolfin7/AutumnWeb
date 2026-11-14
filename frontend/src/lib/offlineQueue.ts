import { bootstrap } from "@/bootstrap";
import { errorMessage, toApiError } from "@/api/errors";
import { csrfToken } from "@/lib/csrf";

/* What you do while Autumn can't be reached (no signal at the gym, the server
   waking from sleep) is kept here and replayed in order once it answers:
   timer starts and stops, logged sessions, new projects and subprojects. Each
   carries its own instants, so the record is what you tapped, not when it
   synced, and each is safe to send twice: starts and sessions carry a client
   uuid the server deduplicates on, a create whose name already exists takes
   the existing record, and a stop of an already-stopped timer is answered
   404/409 and simply dropped.

   An op can use what an earlier op creates before the server has it. A
   queued project or subproject gets a temporary negative id (a start has its
   uuid); later ops carry that ref, and replay rewrites it to the server's id
   through the persisted `synced` map. If the server rejects a creation for
   good, everything that uses it is dropped and reported with it. */

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

export interface QueuedProject {
  kind: "project";
  key: string;
  queuedAt: string;
  /** Negative: stands for the project until the server gives it an id. */
  tempId: number;
  body: { name: string; description: string; status: string; context_id: number | null; tag_ids: number[] };
  display: { context: { id: number; name: string } | null; tags: { id: number; name: string }[] };
}

export interface QueuedSubproject {
  kind: "subproject";
  key: string;
  queuedAt: string;
  tempId: number;
  /** The parent: a server id or a queued project's temporary id. */
  project_id: number;
  body: { name: string; description: string };
  display: { projectName: string };
}

/** A past session (Log past session): the POST /api/v2/sessions/ body. */
export interface QueuedSession {
  kind: "session";
  key: string;
  queuedAt: string;
  body: { uuid: string; project_id: number; start: string; end: string; [field: string]: unknown };
  display: { projectName: string };
}

export type QueuedOp = QueuedStart | QueuedStop | QueuedProject | QueuedSubproject | QueuedSession;
type Fresh<T> = T extends QueuedOp ? Omit<T, "key" | "queuedAt"> : never;
export type NewOp = Fresh<QueuedOp>;

interface QueueState {
  ops: QueuedOp[];
  /** Ref -> server id for creations that synced (a start's uuid, a
      project's or subproject's temporary id), so later ops can find them. */
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

/* Creators before what uses them, should two ever share an instant. */
const RANK: Record<QueuedOp["kind"], number> = { project: 0, subproject: 1, start: 2, session: 3, stop: 4 };

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
  result.ops.sort((a, b) => a.queuedAt.localeCompare(b.queuedAt) || (RANK[a.kind] ?? 9) - (RANK[b.kind] ?? 9) || a.key.localeCompare(b.key));
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

/* ------------------------------------------------- refs between queued ops */

/* Ids of projects and subprojects sit in these fields of an op. */
const REF_FIELDS = new Set(["project_id", "subproject_id", "subproject_ids"]);

/** A temporary id for a project or subproject created on this device. */
export const newTempId = () => -1 - Math.floor(Math.random() * 2 ** 52);

/** What an op creates that later ops can use. */
function createdRef(op: QueuedOp): string | null {
  if (op.kind === "project" || op.kind === "subproject") return String(op.tempId);
  return op.kind === "start" ? op.uuid : null;
}

/** The temporary ids (and, for a stop, the start uuid) an op uses. */
function refsOf(op: QueuedOp): string[] {
  const refs: string[] = [];
  const walk = (value: unknown, field?: string) => {
    if (typeof value === "number") {
      if (value < 0 && field && REF_FIELDS.has(field)) refs.push(String(value));
    } else if (Array.isArray(value)) for (const item of value) walk(item, field);
    else if (value && typeof value === "object") for (const [key, inner] of Object.entries(value)) walk(inner, key);
  };
  walk(op);
  if (op.kind === "stop" && "uuid" in op.target) refs.push(op.target.uuid);
  return refs;
}

/** `value` with each temporary id the server has an id for replaced by it. */
function rewrite<T>(value: T, synced: Record<string, number>, field?: string): T {
  if (typeof value === "number") return (value < 0 && field && REF_FIELDS.has(field) ? (synced[String(value)] ?? value) : value) as T;
  if (Array.isArray(value)) return value.map((item) => rewrite(item, synced, field)) as T;
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, inner]) => [key, rewrite(inner, synced, key)])) as T;
  }
  return value;
}

/** The server's id for a temporary one that synced (else the id itself). */
export function resolveId(id: number): number {
  return id < 0 ? (current().synced[String(id)] ?? id) : id;
}

/** A request body with synced temporary ids rewritten. `waiting` when it
    still uses a creation queued here: then it has to be queued behind it. */
export function resolveRefs<T extends object>(body: T): { body: T; waiting: boolean } {
  const s = current();
  const resolved = rewrite(body, s.synced);
  const left = refsOf(resolved as unknown as QueuedOp);
  const queued = new Set(s.ops.map(createdRef));
  if (left.some((ref) => !queued.has(ref))) throw new Error("A project or subproject it uses was discarded before it synced.");
  return { body: resolved, waiting: left.length > 0 };
}

/** `root` and every queued op that uses what it creates, directly or not
    (ops are in creation order, so one pass finds them all). */
function withDependents(ops: QueuedOp[], root: QueuedOp): QueuedOp[] {
  const gone = new Set<string>();
  const out: QueuedOp[] = [];
  for (const op of ops) {
    if (op.key !== root.key && !refsOf(op).some((ref) => gone.has(ref))) continue;
    out.push(op);
    const ref = createdRef(op);
    if (ref) gone.add(ref);
  }
  return out;
}

/** What discarding the creation of `ref` would take with it. */
export function dependentsOf(ref: string): QueuedOp[] {
  const ops = current().ops;
  const root = ops.find((op) => createdRef(op) === ref);
  return root ? withDependents(ops, root).filter((op) => op !== root) : [];
}

/** An op in words, for reports and confirmations. */
export function describeOp(op: QueuedOp): string {
  switch (op.kind) {
    case "project":
      return `project ${op.body.name}`;
    case "subproject":
      return `subproject ${op.body.name} of ${op.display.projectName}`;
    case "start":
      return `timer on ${op.display.projectName}`;
    case "session":
      return `logged session on ${op.display.projectName}`;
    default:
      return "timer stop";
  }
}

/* ------------------------------------------------------------- the queue */

export function enqueue<T extends NewOp>(op: T): T & { key: string; queuedAt: string } {
  const s = refresh();
  /* After everything already queued, even if the clock stepped back: replay
     order is the order things were done. */
  const last = Math.max(0, ...s.ops.map((o) => Date.parse(o.queuedAt) || 0));
  const item = { ...op, key: crypto.randomUUID(), queuedAt: new Date(Math.max(Date.now(), last + 1)).toISOString() };
  write({ ...s, ops: [...s.ops, item as unknown as QueuedOp] });
  return item;
}

/** Forget something that never reached the server (a timer removed, a
    creation discarded), with everything queued that uses it. */
export function discard(ref: string) {
  const s = refresh();
  const root = s.ops.find((op) => createdRef(op) === ref);
  if (!root) return;
  const gone = new Set(withDependents(s.ops, root).map((op) => op.key));
  write({ ...s, ops: s.ops.filter((op) => !gone.has(op.key)) });
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

interface Answer { status: number; data: unknown; retryAt?: number }

/* A GET without a body, else a POST. */
async function request(url: string, body?: unknown): Promise<Answer> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: body === undefined ? "GET" : "POST",
      credentials: "same-origin",
      headers: {
        ...(body === undefined ? {} : { "Content-Type": "application/json", "X-CSRFToken": csrfToken() }),
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
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

/* The server's reason, with its field details, as the forms show it. */
const messageOf = (answer: Answer) => errorMessage(toApiError(answer.status, answer.data));

const isNameTaken = (answer: Answer) =>
  answer.status === 409 && (answer.data as { error?: { code?: string } } | undefined)?.error?.code === "conflict";

/* The server said a create's name is taken (unique per account; a
   subproject's per project): the record with that exact name is the result.
   A replay whose first answer was lost ends up here too. */
async function existing(list: "projects" | "subprojects", url: string, name: string, taken: Answer): Promise<Answer> {
  for (let offset = 0; ; offset += 500) {
    const page = await request(list === "projects" ? `${url}?ordering=id&limit=500&offset=${offset}` : url);
    if (page.status !== 200) return page;
    const rows = (page.data as Record<string, { id: number; name: string }[] | undefined> | undefined)?.[list] ?? [];
    const found = rows.find((row) => row.name === name);
    if (found) return { status: 200, data: found };
    if (list === "subprojects" || rows.length < 500) return taken;
  }
}

/* One op, with its temporary ids already rewritten. Null: nothing to send. */
async function send(op: QueuedOp, synced: Record<string, number>): Promise<Answer | null> {
  switch (op.kind) {
    case "project": {
      const answer = await request("/api/v2/projects/", op.body);
      return isNameTaken(answer) ? existing("projects", "/api/v2/projects/", op.body.name, answer) : answer;
    }
    case "subproject": {
      const url = `/api/v2/projects/${op.project_id}/subprojects/`;
      const answer = await request(url, op.body);
      return isNameTaken(answer) ? existing("subprojects", url, op.body.name, answer) : answer;
    }
    case "start":
      return request("/api/v2/timers/", op.body);
    case "session":
      return request("/api/v2/sessions/", op.body);
    case "stop": {
      const id = "id" in op.target ? op.target.id : synced[op.target.uuid];
      /* Its start was rejected, so there is nothing to stop. */
      if (id === undefined) return null;
      return request(`/api/v2/timers/${id}/stop/`, {
        end: op.end,
        ...(op.note !== undefined ? { note: op.note } : {}),
        ...(op.subproject_allocations ? { subproject_allocations: op.subproject_allocations } : {}),
      });
    }
  }
}

type SyncedListener = (op: QueuedOp, record: unknown) => void;
const syncedListeners = new Set<SyncedListener>();

/** Told of each op the server accepted, with its answer, just before the op
    leaves the queue: a screen can put the real record in place without a
    moment where it is missing. */
export function onSynced(listener: SyncedListener): () => void {
  syncedListeners.add(listener);
  return () => syncedListeners.delete(listener);
}

let flushing: Promise<FlushReport> | null = null;
let retryAt = 0;
let pruned = false;

export function isFlushing(): boolean {
  return flushing !== null;
}

/** Replay the queue in order. Stops at the first op the server can't be
    reached for; drops (and reports) ops the server rejects, with what uses
    them. */
export function flushQueue(): Promise<FlushReport> {
  if (!flushing) {
    const run = async (): Promise<FlushReport> => {
      const report: FlushReport = { synced: 0, dropped: [], remaining: 0 };
      /* Once per page load, forget ids nothing queued uses. Until then they
         serve screens still showing a temporary id or a pending timer. */
      if (!pruned) {
        pruned = true;
        const s = refresh();
        const wanted = new Set(s.ops.flatMap(refsOf));
        write({ ...s, synced: Object.fromEntries(Object.entries(s.synced).filter(([ref]) => wanted.has(ref))) });
      }
      for (;;) {
        const s = refresh();
        if (Date.now() < retryAt) break;
        const op = s.ops[0];
        if (!op) break;
        const sent = rewrite(op, s.synced);
        const queued = new Set(s.ops.map(createdRef));
        /* Uses a creation that is no longer queued and never synced. */
        const orphan = refsOf(sent).some((ref) => ref.startsWith("-") && !queued.has(ref));
        const answer: Answer | null = orphan
          ? { status: 410, data: { error: { message: "Something it used was discarded before it synced." } } }
          : await send(sent, s.synced);
        if (answer && (isNetworkFailure(answer.status) || answer.status === 401 || answer.status === 403)) {
          /* Offline, temporary server failure, or signed out: keep everything. */
          if (answer.retryAt && Number.isFinite(answer.retryAt)) retryAt = answer.retryAt;
          break;
        }
        const after = refresh();
        const synced = { ...after.synced };
        let ops = after.ops.filter((o) => o.key !== op.key);
        if (answer && answer.status >= 200 && answer.status < 300) {
          report.synced += 1;
          const ref = createdRef(op);
          const id = (answer.data as { id?: number } | undefined)?.id;
          if (ref && id) synced[ref] = id;
          for (const listener of syncedListeners) listener(sent, answer.data);
        } else if (answer && !(op.kind === "stop" && (answer.status === 404 || answer.status === 409))) {
          report.dropped.push({ op, status: answer.status, message: messageOf(answer) });
          const gone = withDependents(after.ops, op).filter((o) => o.key !== op.key);
          for (const dependent of gone) {
            /* A stop goes with its start, which is already reported. */
            if (dependent.kind !== "stop") {
              report.dropped.push({ op: dependent, status: 0, message: `it used the ${describeOp(op)}, which couldn't sync.` });
            }
          }
          const keys = new Set(gone.map((o) => o.key));
          ops = ops.filter((o) => !keys.has(o.key));
        }
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
  pruned = false;
  listeners.clear();
  syncedListeners.clear();
}
