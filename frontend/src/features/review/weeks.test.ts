import { canGoNext, defaultStart, nextStart, selectedStart, sessionsLink, shiftWeek, weekParamFor } from "./weeks";

it("takes any date in ?week as the window's first day", () => {
  expect(selectedStart("2026-10-14")).toBe("2026-10-14");
  expect(selectedStart(" 2026-10-08 ")).toBe("2026-10-08");
});

it("ignores a missing or malformed week", () => {
  expect(selectedStart(null)).toBeNull();
  expect(selectedStart("")).toBeNull();
  expect(selectedStart("last-week")).toBeNull();
  expect(selectedStart("2026-13-40")).toBeNull();
});

it("defaults to the seven days ending yesterday", () => {
  expect(defaultStart("2026-10-15")).toBe("2026-10-08");
  expect(defaultStart("2026-01-03")).toBe("2025-12-27");
});

it("steps whole weeks across a year boundary", () => {
  expect(shiftWeek("2026-01-05", -1)).toBe("2025-12-29");
  expect(shiftWeek("2025-12-29", 1)).toBe("2026-01-05");
});

it("keeps the default window's URL plain", () => {
  expect(weekParamFor("2026-10-08", "2026-10-08")).toBeNull();
  expect(weekParamFor("2026-10-01", "2026-10-08")).toBe("2026-10-01");
});

it("does not step past the default window", () => {
  expect(canGoNext("2026-10-01", "2026-10-08")).toBe(true);
  expect(canGoNext("2026-10-08", "2026-10-08")).toBe(false);
  expect(canGoNext("2026-10-12", "2026-10-08")).toBe(false);
  expect(nextStart("2026-10-01", "2026-10-08")).toBe("2026-10-08");
  expect(nextStart("2026-10-04", "2026-10-08")).toBe("2026-10-08");
  expect(nextStart("2026-09-20", "2026-10-08")).toBe("2026-09-27");
});

it("builds the sessions link for a week", () => {
  expect(sessionsLink("2026-10-05", "2026-10-11")).toBe("/sessions/?start_date=2026-10-05&end_date=2026-10-11");
});
