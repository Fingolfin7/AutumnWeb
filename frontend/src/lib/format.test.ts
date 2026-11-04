import {
  formatClock,
  formatDayDate,
  formatDuration,
  formatDurationWords,
  formatTime,
  formatTimeRange,
  heroParts,
  localTimeCandidates,
  parseDateish,
  toDateTimeLocal,
} from "./format";

describe("formatDuration uses the shared compact saved-duration contract", () => {
  it.each([
    [0, "0m"],
    [0.5, "0m"],
    [45.5, "45m"],
    [125, "2h 5m"],
    [60 * 24 + 61, "25h 1m"],
    [59.99999999, "1h"],
  ])("%s minutes -> %s", (minutes, expected) => {
    expect(formatDuration(minutes)).toBe(expected);
  });
});

it("formatDurationWords shares the compact formatter", () => {
  expect(formatDurationWords(60 * 26 + 10)).toBe("26h 10m");
  expect(formatDurationWords(190)).toBe("3h 10m");
  expect(formatDurationWords(0)).toBe("0m");
  expect(formatDurationWords(1)).toBe("1m");
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

it("formats clock ranges without seconds and ignores invalid durations", () => {
  const start = new Date(2026, 9, 28, 8, 0, 30);
  const end = new Date(2026, 9, 28, 8, 45, 0);
  expect(formatTime(start)).toBe("08:00");
  expect(formatTimeRange(start, end)).toBe("08:00–08:45");
  expect(formatDuration(NaN)).toBe("0m");
  expect(formatDuration(-20)).toBe("0m");
});

it("treats bare dates as local calendar days", () => {
  const date = parseDateish("2021-06-12")!;
  expect(date.getDate()).toBe(12);
  expect(formatDayDate("2021-06-12")).toBe("Sat 12 Jun");
});

it("round-trips datetime-local values through offset ISO", () => {
  const iso = localTimeCandidates("2026-10-14T09:30:05").instants[0]!;
  expect(toDateTimeLocal(iso)).toBe("2026-10-14T09:30:05");
});
