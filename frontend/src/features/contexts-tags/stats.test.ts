import { describe, expect, it } from "vitest";
import { formatMinutesFull, formatStatusCounts, summarizeProjects, validateName } from "./stats";

describe("summarizeProjects", () => {
  it("counts statuses and averages over sessions", () => {
    const summary = summarizeProjects([
      { status: "active", total_minutes: 60, session_count: 2 },
      { status: "active", total_minutes: 30, session_count: 1 },
      { status: "paused", total_minutes: 0, session_count: 0 },
    ]);
    expect(summary.total).toBe(3);
    expect(summary.statusCounts).toEqual({ active: 2, paused: 1, complete: 0, archived: 0 });
    expect(summary.totalMinutes).toBe(90);
    expect(summary.averageMinutes).toBe(30);
  });

  it("does not divide by zero", () => {
    expect(summarizeProjects([]).averageMinutes).toBe(0);
  });
});

describe("formatStatusCounts", () => {
  it("lists only non-zero statuses", () => {
    expect(formatStatusCounts({ active: 2, paused: 1, complete: 0, archived: 0 })).toBe("(2 active, 1 paused)");
    expect(formatStatusCounts({ active: 0, paused: 0, complete: 0, archived: 0 })).toBe("");
  });
});

describe("formatMinutesFull", () => {
  it("names every non-zero unit", () => {
    expect(formatMinutesFull(9 * 60 + 23)).toBe("9 hours 23 minutes");
    expect(formatMinutesFull(62.55)).toBe("1 hour 2 minutes 33 seconds");
    expect(formatMinutesFull(60)).toBe("1 hour");
    expect(formatMinutesFull(0)).toBe("0 seconds");
    expect(formatMinutesFull(48)).toBe("48 minutes");
  });
});

describe("validateName", () => {
  const others = [
    { id: 1, name: "Craft" },
    { id: 2, name: "Study" },
  ];
  it("requires a name", () => {
    expect(validateName("   ", "context", others)).toBe("This field is required.");
  });
  it("caps the length", () => {
    expect(validateName("x".repeat(101), "tag", others)).toMatch(/at most 100/);
    expect(validateName("x".repeat(100), "tag", others)).toBeNull();
  });
  it("rejects duplicates ignoring case, but not the record itself", () => {
    expect(validateName(" craft ", "context", others)).toBe("You already have a context with this name.");
    expect(validateName("Craft", "context", others, 1)).toBeNull();
    expect(validateName("Study", "tag", others, 1)).toBe("You already have a tag with this name.");
  });
});
