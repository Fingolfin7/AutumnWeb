import { groupByDay } from "./sessions";

const at = (iso: string, minutes: number) => ({ end: iso, duration_minutes: minutes });

it("groups by local end date, newest day first, summing durations", () => {
  const a = at(new Date(2026, 9, 14, 18, 0).toISOString(), 30);
  const b = at(new Date(2026, 9, 14, 9, 0).toISOString(), 15);
  const c = at(new Date(2026, 9, 12, 23, 59).toISOString(), 60);
  const groups = groupByDay([c, a, b]);
  expect(groups.map((g) => g.date)).toEqual(["2026-10-14", "2026-10-12"]);
  expect(groups[0]!.totalMinutes).toBe(45);
  expect(groups[0]!.sessions).toEqual([a, b]);
});

it("skips sessions that have not ended", () => {
  expect(groupByDay([{ end: null, duration_minutes: null }])).toEqual([]);
});
