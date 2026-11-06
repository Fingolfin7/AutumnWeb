import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cancelStart,
  enqueueStart,
  enqueueStop,
  flushQueue,
  hasUnsavedChanges,
  overlayTimers,
  queuedOps,
  resetQueueForTests,
  type QueuedStart,
} from "./offlineQueue";

type Call = { url: string; body: Record<string, unknown> };

function server(handler: (call: Call) => { status: number; body?: unknown } | "offline") {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      const call = { url, body: JSON.parse(String(init.body)) as Record<string, unknown> };
      calls.push(call);
      const result = handler(call);
      if (result === "offline") throw new TypeError("Failed to fetch");
      return new Response(JSON.stringify(result.body ?? {}), { status: result.status });
    }),
  );
  return calls;
}

const start = (uuid: string, projectName = "Gym") =>
  enqueueStart({
    uuid,
    body: { project_id: 3, start: "2026-10-14T07:00:00+02:00", uuid },
    display: { projectName, subprojects: [] },
  });

beforeEach(() => {
  window.localStorage.clear();
  resetQueueForTests();
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe("offline queue", () => {
  it("replays a start then its stop, resolving the stop through the new id", async () => {
    start("u-1");
    enqueueStop({ target: { uuid: "u-1" }, end: "2026-10-14T08:00:00+02:00", note: "Squats" });
    const calls = server((call) => (call.url === "/api/v2/timers/" ? { status: 201, body: { id: 41 } } : { status: 200, body: { id: 41 } }));

    const report = await flushQueue();

    expect(calls.map((c) => c.url)).toEqual(["/api/v2/timers/", "/api/v2/timers/41/stop/"]);
    expect(calls[0]!.body).toMatchObject({ uuid: "u-1", start: "2026-10-14T07:00:00+02:00" });
    expect(calls[1]!.body).toEqual({ end: "2026-10-14T08:00:00+02:00", note: "Squats" });
    expect(report).toMatchObject({ synced: 2, remaining: 0 });
    expect(queuedOps()).toEqual([]);
  });

  it("keeps everything while the server can't be reached", async () => {
    start("u-1");
    server(() => "offline");
    const report = await flushQueue();
    expect(report).toMatchObject({ synced: 0, remaining: 1 });
    expect(queuedOps()).toHaveLength(1);
  });

  it("drops and reports a start the server rejects, and its stop with it", async () => {
    start("u-1");
    enqueueStop({ target: { uuid: "u-1" }, end: "2026-10-14T08:00:00+02:00" });
    const calls = server(() => ({ status: 400, body: { error: { code: "invalid", message: "Project is archived." } } }));
    const report = await flushQueue();
    expect(calls).toHaveLength(1);
    expect(report.dropped.map((d) => d.message)).toEqual(["Project is archived."]);
    expect(queuedOps()).toEqual([]);
  });

  it("quietly drops a stop for a timer already stopped elsewhere", async () => {
    enqueueStop({ target: { id: 9 }, end: "2026-10-14T08:00:00+02:00" });
    server(() => ({ status: 404 }));
    const report = await flushQueue();
    expect(report.dropped).toEqual([]);
    expect(queuedOps()).toEqual([]);
  });

  it("survives a reload", () => {
    start("u-1");
    resetQueueForTests();
    expect(queuedOps().map((op) => op.kind)).toEqual(["start"]);
  });

  it("cancelling a queued start removes its stop too", () => {
    start("u-1");
    enqueueStop({ target: { uuid: "u-1" }, end: "2026-10-14T08:00:00+02:00" });
    cancelStart("u-1");
    expect(queuedOps()).toEqual([]);
  });

  it("overlays queued starts and hides queued stops", () => {
    start("u-new", "Reading");
    enqueueStop({ target: { id: 5 }, end: "2026-10-14T08:00:00+02:00" });
    const serverTimers = [
      { id: 5, uuid: "a" },
      { id: 6, uuid: "b" },
    ];
    const merged = overlayTimers(serverTimers, (op: QueuedStart) => ({ id: -1, uuid: op.uuid }));
    expect(merged).toEqual([
      { id: 6, uuid: "b" },
      { id: -1, uuid: "u-new" },
    ]);
  });

  it("doesn't duplicate a start the server already has", () => {
    start("u-1");
    const merged = overlayTimers([{ id: 7, uuid: "u-1" }], (op: QueuedStart) => ({ id: -1, uuid: op.uuid }));
    expect(merged).toEqual([{ id: 7, uuid: "u-1" }]);
  });
});


describe("queue reliability", () => {
  it.each([408, 429, 500, 502, 503, 504, 599, 401, 403])("retains a start and stop after HTTP %i and later replays both", async (status) => {
    start("retry");
    enqueueStop({ target: { uuid: "retry" }, end: "2026-10-14T08:00:00Z" });
    const failed = server(() => ({ status }));
    expect(await flushQueue()).toMatchObject({ synced: 0, remaining: 2, dropped: [] });
    expect(failed).toHaveLength(1);
    const recovered = server(() => ({ status: 200, body: { id: 42 } }));
    expect(await flushQueue()).toMatchObject({ synced: 2, remaining: 0 });
    expect(recovered[1]!.url).toBe("/api/v2/timers/42/stop/");
  });

  it.each(["60", "Wed, 14 Oct 2026 07:01:00 GMT"])("honors Retry-After %s", async (header) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-14T07:00:00Z"));
    start("rate-limited");
    const fetch = vi.fn().mockResolvedValueOnce(new Response("{}", { status: 429, headers: { "Retry-After": header } }))
      .mockResolvedValue(new Response('{"id":42}', { status: 201 }));
    vi.stubGlobal("fetch", fetch);
    await flushQueue();
    vi.advanceTimersByTime(59_000);
    expect((await flushQueue()).remaining).toBe(1);
    expect(fetch).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1_000);
    expect((await flushQueue()).remaining).toBe(0);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("keeps memory-only operations through flushes and storage events, then syncs", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Full", "QuotaExceededError"); });
    start("memory");
    enqueueStop({ target: { uuid: "memory" }, end: "2026-10-14T08:00:00Z" });
    expect(hasUnsavedChanges()).toBe(true);
    server(() => "offline");
    expect((await flushQueue()).remaining).toBe(2);
    window.dispatchEvent(new StorageEvent("storage", { key: null }));
    expect(queuedOps()).toHaveLength(2);
    const calls = server(() => ({ status: 200, body: { id: 42 } }));
    expect(await flushQueue()).toMatchObject({ synced: 2, remaining: 0 });
    expect(calls[1]!.url).toBe("/api/v2/timers/42/stop/");
    expect(hasUnsavedChanges()).toBe(false);
  });

  it("persists memory-only changes when storage recovers", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Unavailable"); });
    start("recover");
    expect(hasUnsavedChanges()).toBe(true);
    storage.mockRestore();
    server(() => "offline");
    await flushQueue();
    expect(hasUnsavedChanges()).toBe(false);
    resetQueueForTests();
    expect(queuedOps()).toHaveLength(1);
  });

  it("migrates a saved legacy queue including start-to-stop mappings", async () => {
    window.localStorage.setItem("autumn:offline-queue:0", JSON.stringify({
      ops: [{ kind: "stop", key: "old-stop", queuedAt: "2026-10-14T08:00:00Z", target: { uuid: "old-start" }, end: "2026-10-14T08:00:00Z" }],
      synced: { "old-start": 42 },
    }));
    expect(queuedOps()).toHaveLength(1);
    expect(window.localStorage.getItem("autumn:offline-queue:0")).toBeNull();
    resetQueueForTests();
    const calls = server(() => ({ status: 200 }));
    await flushQueue();
    expect(calls[0]!.url).toBe("/api/v2/timers/42/stop/");
  });

  it("preserves two tabs' additions before either receives a storage event", async () => {
    // Independent module instances model tab-local caches over shared storage.
    vi.resetModules();
    const otherTab = await import("./offlineQueue");
    expect(queuedOps()).toEqual([]);
    expect(otherTab.queuedOps()).toEqual([]);
    start("first-tab");
    otherTab.enqueueStart({ uuid: "second-tab", body: { project_id: 3, start: "2026-10-14T07:00:00Z", uuid: "second-tab" }, display: { projectName: "Reading", subprojects: [] } });
    resetQueueForTests();
    expect(queuedOps().map((op) => op.kind === "start" && op.uuid).sort()).toEqual(["first-tab", "second-tab"]);
    otherTab.resetQueueForTests();
  });

  it("does not erase another tab's enqueue while a request is in flight", async () => {
    vi.resetModules();
    const otherTab = await import("./offlineQueue");
    start("in-flight");
    let finish!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve; }))
      .mockRejectedValue(new TypeError("offline")));
    const flushing = flushQueue();
    otherTab.enqueueStop({ target: { id: 99 }, end: "2026-10-14T08:00:00Z" });
    finish(new Response('{"id":42}', { status: 201 }));
    expect(await flushing).toMatchObject({ synced: 1, remaining: 1 });
    resetQueueForTests();
    expect(queuedOps()[0]).toMatchObject({ kind: "stop", target: { id: 99 } });
    otherTab.resetQueueForTests();
  });
});


it("does not replay migrated operations repeatedly when storage is full", async () => {
  window.localStorage.setItem("autumn:offline-queue:0", JSON.stringify({ ops: [{ kind: "start", key: "legacy-start", uuid: "legacy", queuedAt: "2026-10-14T07:00:00Z", body: { project_id: 3, start: "2026-10-14T07:00:00Z", uuid: "legacy" }, display: { projectName: "Gym", subprojects: [] } }], synced: {} }));
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Full"); });
  const calls = server(() => ({ status: 201, body: { id: 42 } }));
  expect(await flushQueue()).toMatchObject({ synced: 1, remaining: 0 });
  expect(calls).toHaveLength(1);
  expect((await flushQueue()).synced).toBe(0);
});
