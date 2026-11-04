import { calendarWeek, comparisonPeriod, legacyReviewTarget, presetPeriod, readPeriod } from "./periods";

it("uses Monday–Sunday weeks across year boundaries", () => {
  expect(calendarWeek("2027-01-03")).toEqual({ start: "2026-12-28", end: "2027-01-03" });
  expect(presetPeriod("last", "2027-01-04")).toEqual({ start: "2026-12-28", end: "2027-01-03" });
});

it("compares the complete preceding calendar week or equal custom period", () => {
  expect(comparisonPeriod(calendarWeek("2026-11-04"))).toEqual({ start: "2026-10-26", end: "2026-11-01" });
  expect(comparisonPeriod({ start: "2026-02-01", end: "2026-02-28" })).toEqual({ start: "2026-01-04", end: "2026-01-31" });
});

it("validates custom dates and keeps a reversed range safe", () => {
  expect(readPeriod(new URLSearchParams("start_date=2026-02-31"), "2026-11-04")).toEqual(calendarWeek("2026-11-04"));
  expect(readPeriod(new URLSearchParams("start_date=2026-11-01&end_date=2026-10-01"), "2026-11-04")).toEqual({ start: "2026-11-01", end: "2026-11-01" });
});

it("keeps chart bookmarks and the weekly notification's exact window", () => {
  const charts = legacyReviewTarget("/charts/", "?search=notes&related=on&tags=2&tags=3&chart_type=heatmap", "2026-11-04");
  expect(charts).toBe("/review/?search=notes&related=on&tags=2&tags=3&chart_type=heatmap");
  expect(legacyReviewTarget("/charts/", "", "2026-11-04")).toBe("/review/?chart_type=pie");
  expect(legacyReviewTarget("/review/weekly/", "?week=2026-10-21&context=2", "2026-11-04")).toBe("/review/?context=2&start_date=2026-10-21&end_date=2026-10-27");
  expect(legacyReviewTarget("/review/weekly/", "", "2026-11-04")).toBe("/review/?start_date=2026-10-28&end_date=2026-11-03");
});
