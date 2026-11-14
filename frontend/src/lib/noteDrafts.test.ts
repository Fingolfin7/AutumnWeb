import { afterEach, expect, it, vi } from "vitest";
import { clearNoteDraft, holdNoteDraft, mergeNote, readNoteDraft, resetNoteDraftsForTests, syncNoteDrafts, waitingNoteDrafts, writeNoteDraft } from "./noteDrafts";

const UUID = "1b6d8a54-0c7e-4e2a-9a52-0d6b1f3f7c11";
const draft = (note: string, base = "") => ({ uuid: UUID, project: "Piano", note, base });

/** A server holding one session, running or stopped; records the notes it is asked to save. */
function server(session: { id: number; version: number; note: string } | null, running = false) {
  const saved: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        saved.push((JSON.parse(String(init.body)) as { note: string }).note);
        return new Response("{}", { status: 200 });
      }
      const here = session && running === url.startsWith("/api/v2/timers/") ? [{ ...session, uuid: UUID }] : [];
      return new Response(JSON.stringify(running === url.startsWith("/api/v2/timers/") ? { timers: here, sessions: here } : { timers: [], sessions: [] }), { status: 200 });
    }),
  );
  return saved;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  resetNoteDraftsForTests();
});

it("joins a draft with a note that changed elsewhere, losing neither", () => {
  expect(mergeNote("warm-up", "warm-up", "warm-up\nscales")).toBe("warm-up\nscales");
  expect(mergeNote("warm-up\nfrom the CLI", "warm-up", "warm-up\nscales")).toBe("warm-up\nfrom the CLI\n\nscales");
  expect(mergeNote("rewritten elsewhere", "warm-up", "my own rewrite")).toBe("rewritten elsewhere\n\nmy own rewrite");
  /* Already there (a save whose reply was lost): not added twice. */
  expect(mergeNote("warm-up\n\nscales", "warm-up", "warm-up\nscales")).toBe("warm-up\n\nscales");
});

it("keeps a draft across a reload and sends it once nobody is editing it", async () => {
  const release = holdNoteDraft(UUID);
  writeNoteDraft(draft("typed with no signal"));
  resetNoteDraftsForTests(); // the tab was closed
  expect(readNoteDraft(UUID)?.note).toBe("typed with no signal");
  expect(waitingNoteDrafts()).toBe(1);
  release();

  const saved = server({ id: 7, version: 3, note: "" });
  const report = await syncNoteDrafts();
  expect(saved).toEqual(["typed with no signal"]);
  expect(report.saved).toHaveLength(1);
  expect(readNoteDraft(UUID)).toBeNull();
});

it("finds the session whether its timer is still running or has stopped, and never drops text it can't place", async () => {
  writeNoteDraft(draft("typed, then left the page"));
  let saved = server({ id: 7, version: 3, note: "" }, true);
  await syncNoteDrafts();
  expect(saved).toEqual(["typed, then left the page"]);

  writeNoteDraft(draft("the timer auto-stopped meanwhile"));
  saved = server({ id: 7, version: 4, note: "" }, false);
  await syncNoteDrafts();
  expect(saved).toEqual(["the timer auto-stopped meanwhile"]);

  writeNoteDraft(draft("its session was deleted"));
  server(null);
  await syncNoteDrafts();
  expect(readNoteDraft(UUID)?.note).toBe("its session was deleted");
  expect(waitingNoteDrafts()).toBe(0);
});

it("leaves a draft alone while its editor is open or the server can't be reached", async () => {
  writeNoteDraft(draft("still typing"));
  const release = holdNoteDraft(UUID);
  const saved = server({ id: 7, version: 3, note: "" });
  await syncNoteDrafts();
  expect(saved).toEqual([]);
  release();

  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  await syncNoteDrafts();
  expect(readNoteDraft(UUID)?.note).toBe("still typing");
  clearNoteDraft(UUID);
});
