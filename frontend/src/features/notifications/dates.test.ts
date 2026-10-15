import { addDays, clockText, defaultSlot, formatDateKey, formatInstant, parseDateKey, todayKey } from "./dates";

it("moves across month and year boundaries", () => {
  expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
  expect(addDays("2026-01-01", -1)).toBe("2025-12-31");
  expect(addDays("2024-02-28", 2)).toBe("2024-03-01");
});

it("rejects impossible dates", () => {
  expect(parseDateKey("2026-02-30")).toBeNull();
  expect(parseDateKey("soon")).toBeNull();
  expect(parseDateKey("2026-10-14")).toEqual({ year: 2026, month: 10, day: 14 });
});

it("formats date keys like Django's D j M", () => {
  expect(formatDateKey("2026-10-15")).toBe("Thu 15 Oct");
  expect(formatDateKey("2026-09-01", true)).toBe("Tue 1 Sep 2026");
});

it("shows an instant on the profile timezone's wall clock", () => {
  expect(formatInstant("2026-10-15T07:00:00Z", "Europe/Prague")).toBe("Thu 15 Oct, 09:00");
  expect(formatInstant("2026-10-15T07:00:00Z", "America/New_York")).toBe("Thu 15 Oct, 03:00");
  expect(formatInstant("2026-10-15T23:30:00Z", "Asia/Tokyo")).toBe("Fri 16 Oct, 08:30");
  expect(formatInstant(null, "UTC")).toBe("");
});

it("reads today in the given zone, not the machine's", () => {
  const instant = new Date("2026-10-14T23:30:00Z");
  expect(todayKey("UTC", instant)).toBe("2026-10-14");
  expect(todayKey("Asia/Tokyo", instant)).toBe("2026-10-15");
});

it("offers the next whole hour as a first slot, rolling past midnight", () => {
  expect(defaultSlot("UTC", new Date("2026-10-14T09:20:00Z"))).toEqual({ date: "2026-10-14", time: "10:00" });
  expect(defaultSlot("UTC", new Date("2026-10-14T23:20:00Z"))).toEqual({ date: "2026-10-15", time: "00:00" });
  expect(defaultSlot("Asia/Tokyo", new Date("2026-10-14T15:05:00Z"))).toEqual({ date: "2026-10-15", time: "01:00" });
});

it("trims API times to HH:MM", () => {
  expect(clockText("18:00:00")).toBe("18:00");
  expect(clockText(undefined)).toBe("");
});
