import {
  formatClock,
  formatDayDate,
  formatDuration,
  formatDurationWords,
  fromDateTimeLocal,
  heroParts,
  parseDateish,
  toDateTimeLocal,
} from "./format";

describe("formatDuration mirrors the duration_formatter filter", () => {
  it.each([
    [0, "00m 00s"],
    [0.5, "00m 30s"],
    [45.5, "45m 30s"],
    [125, "02h 05m"],
    [60 * 24 + 61, "01d 01h 01m"],
    [59.99999999, "01h 00m"],
  ])("%s minutes -> %s", (minutes, expected) => {
    expect(formatDuration(minutes)).toBe(expected);
  });
});

it("formatDurationWords keeps two units", () => {
  expect(formatDurationWords(60 * 26 + 10)).toBe("1 day 2 hours");
  expect(formatDurationWords(190)).toBe("3 hours 10 minutes");
  expect(formatDurationWords(0)).toBe("0 seconds");
  expect(formatDurationWords(1)).toBe("1 minute");
});

it("heroParts steps units up with magnitude", () => {
  expect(heroParts(65)).toEqual([
    { value: 1, unit: "minute" },
    { value: 5, unit: "seconds" },
  ]);
  expect(heroParts(3600 * 2 + 60)).toEqual([
    { value: 2, unit: "hours" },
    { value: 1, unit: "minute" },
  ]);
  expect(heroParts(86400 + 3600)).toEqual([
    { value: 1, unit: "day" },
    { value: 1, unit: "hour" },
  ]);
});

it("formatClock pads hours", () => {
  expect(formatClock(3725)).toBe("01:02:05");
});

it("treats bare dates as local calendar days", () => {
  const date = parseDateish("2021-06-12")!;
  expect(date.getDate()).toBe(12);
  expect(formatDayDate("2021-06-12")).toBe("Saturday 12 Jun 2021");
});

it("round-trips datetime-local values through offset ISO", () => {
  const iso = fromDateTimeLocal("2026-10-14T09:30:05")!;
  expect(toDateTimeLocal(iso)).toBe("2026-10-14T09:30:05");
});
