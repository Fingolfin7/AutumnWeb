import { groupByDay } from "./sessions";

const at = (iso: string, minutes: number) => ({ start: new Date(Date.parse(iso) - minutes * 60000).toISOString(), end: iso, duration_minutes: minutes });

it("groups by local calendar overlap, newest day first, summing durations", () => {
  const a = at(new Date(2026, 9, 14, 18, 0).toISOString(), 30);
  const b = at(new Date(2026, 9, 14, 9, 0).toISOString(), 15);
  const c = at(new Date(2026, 9, 12, 23, 59).toISOString(), 60);
  const groups = groupByDay([c, a, b]);
  expect(groups.map((g) => g.date)).toEqual(["2026-10-14", "2026-10-12"]);
  expect(groups[0]!.totalMinutes).toBe(45);
  expect(groups[0]!.sessions).toEqual([a, b]);
});

it("skips sessions that have not ended", () => {
  expect(groupByDay([{ start: new Date().toISOString(), end: null, duration_minutes: null }])).toEqual([]);
});

it("splits a midnight crossing while preserving the exact saved duration", () => {
  const row = { start: new Date(2026, 10, 4, 21, 53).toISOString(), end: new Date(2026, 10, 5, 0, 28).toISOString(), duration_minutes: 155 };
  const groups = groupByDay([row]);
  expect(groups.map((group) => [group.date, group.totalMinutes])).toEqual([["2026-11-05", 28], ["2026-11-04", 127]]);
  expect(groups.reduce((sum, group) => sum + group.totalMinutes, 0)).toBe(row.duration_minutes);
  expect(groups[0]!.sessions[0]).toBe(row);
});
