import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cancelStart,
  enqueueStart,
  enqueueStop,
  flushQueue,
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
afterEach(() => vi.unstubAllGlobals());

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
