import { describe, expect, it } from "vitest";
import type { Timer } from "@/api/types";
import type { Timeline } from "./api";
import { ledgerEntries } from "./DayTimeline";

const project = { id: 1, name: "Project" };
const now = new Date("2026-11-04T12:00:00").getTime();
const block = { session_id: 10, start: "2026-11-04T10:00:00", end: null, is_live: true, minutes: 120 };
const report = { start_date: "2026-11-04", end_date: "2026-11-04", lanes: [{ project, blocks: [block] }] } as Timeline;

describe("timeline live state", () => {
  it("drops a cached live block as soon as the timer list is empty", () => {
    expect(ledgerEntries(report, [], now)).toEqual([]);
  });
  it("replaces a stale live project with the current timer and counts its actual time", () => {
    const timer = {
      id: 20,
      project: { id: 2, name: "Current project" },
      start: "2026-11-04T11:30:00",
      subproject_allocations: [],
    } as unknown as Timer;
    const entries = ledgerEntries(report, [timer], now);
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({ session_id: 20, project: timer.project, minutes: 30, is_live: true });
  });
});

it("counts only the local-day portion of a saved midnight crossing", () => {
  const start = new Date(2026, 10, 3, 21, 53).toISOString(), end = new Date(2026, 10, 4, 0, 28).toISOString();
  const crossing = { ...report, lanes: [{ project, blocks: [{ ...block, start, end, minutes: 155, is_live: false }] }] } as Timeline;
  expect(ledgerEntries(crossing, [], now)[0]?.minutes).toBe(28);
});
