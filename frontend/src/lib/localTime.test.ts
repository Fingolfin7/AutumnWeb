import {
  localTimeCandidates,
  nonexistentTimeMessage,
  occurrenceLabel,
  utcOffsetLabel,
} from "./format";

/* Europe/Prague in 2026: clocks go forward 02:00 -> 03:00 on 29 March and back
   03:00 -> 02:00 on 25 October. jsdom reads the zone from TZ, which Node
   applies as soon as it is set, so set it before any Date is built. */
const ZONE = "Europe/Prague";
const previousZone = process.env.TZ;
beforeAll(() => {
  process.env.TZ = ZONE;
});
afterAll(() => {
  if (previousZone === undefined) delete process.env.TZ;
  else process.env.TZ = previousZone;
});

it("runs in Europe/Prague (otherwise the cases below prove nothing)", () => {
  expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe(ZONE);
  expect(new Date("2026-01-15T12:00:00Z").getTimezoneOffset()).toBe(-60);
  expect(new Date("2026-07-15T12:00:00Z").getTimezoneOffset()).toBe(-120);
  /* The skipped hour really is skipped by the browser. */
  expect(new Date("2026-03-29T02:30:00").getHours()).toBe(3);
});

describe("ordinary times", () => {
  it("resolve to one instant with the local offset", () => {
    expect(localTimeCandidates("2026-10-14T09:30:05")).toEqual({ kind: "ok", instants: ["2026-10-14T09:30:05+02:00"] });
    expect(localTimeCandidates("2026-01-14T09:30")).toEqual({ kind: "ok", instants: ["2026-01-14T09:30:00+01:00"] });
  });

  it("treat empty or malformed values as ok with nothing to submit", () => {
    expect(localTimeCandidates("")).toEqual({ kind: "ok", instants: [] });
    expect(localTimeCandidates("not a time")).toEqual({ kind: "ok", instants: [] });
  });
});

describe("the night clocks go back (25 Oct)", () => {
  it("offers both occurrences, first one first", () => {
    expect(localTimeCandidates("2026-10-25T02:30:00")).toEqual({
      kind: "ambiguous",
      instants: ["2026-10-25T02:30:00+02:00", "2026-10-25T02:30:00+01:00"],
    });
  });

  it("works for values without seconds", () => {
    expect(localTimeCandidates("2026-10-25T02:30")).toEqual({
      kind: "ambiguous",
      instants: ["2026-10-25T02:30:00+02:00", "2026-10-25T02:30:00+01:00"],
    });
  });

  it("covers exactly the repeated hour", () => {
    expect(localTimeCandidates("2026-10-25T01:59:59").kind).toBe("ok");
    expect(localTimeCandidates("2026-10-25T02:00:00").kind).toBe("ambiguous");
    expect(localTimeCandidates("2026-10-25T02:59:59").kind).toBe("ambiguous");
    expect(localTimeCandidates("2026-10-25T03:00:00").kind).toBe("ok");
  });

  it("returns instants one hour apart", () => {
    const [first, second] = localTimeCandidates("2026-10-25T02:15:00").instants;
    expect(Date.parse(second!) - Date.parse(first!)).toBe(3_600_000);
  });
});

describe("the night clocks go forward (29 Mar)", () => {
  it("flags the skipped hour and offers no instant", () => {
    expect(localTimeCandidates("2026-03-29T02:30")).toEqual({ kind: "nonexistent", instants: [] });
    expect(localTimeCandidates("2026-03-29T02:00:00").kind).toBe("nonexistent");
    expect(localTimeCandidates("2026-03-29T02:59:59").kind).toBe("nonexistent");
  });

  it("leaves the neighbouring times alone", () => {
    expect(localTimeCandidates("2026-03-29T01:59:59").kind).toBe("ok");
    expect(localTimeCandidates("2026-03-29T03:00:00")).toEqual({ kind: "ok", instants: ["2026-03-29T03:00:00+02:00"] });
  });

  it("words the field error", () => {
    expect(nonexistentTimeMessage("2026-03-29T02:30")).toBe("Clocks go forward at this time, so 02:30 doesn't exist on 29 Mar.");
    expect(nonexistentTimeMessage("2026-03-29T02:30:15")).toBe("Clocks go forward at this time, so 02:30:15 doesn't exist on 29 Mar.");
    expect(nonexistentTimeMessage("2026-03-29T03:30")).toBeNull();
    expect(nonexistentTimeMessage("")).toBeNull();
  });
});

describe("labels", () => {
  it("name the offset of each occurrence", () => {
    const [first, second] = localTimeCandidates("2026-10-25T02:30").instants as [string, string];
    expect(utcOffsetLabel(first)).toBe("UTC+02:00");
    expect(utcOffsetLabel(second)).toBe("UTC+01:00");
    expect(occurrenceLabel(0, first)).toBe("first, UTC+02:00");
    expect(occurrenceLabel(1, second)).toBe("second, UTC+01:00");
  });

  it("handles negative and half-hour offsets", () => {
    process.env.TZ = "Asia/Kolkata";
    try {
      expect(utcOffsetLabel(new Date("2026-01-01T00:00:00Z"))).toBe("UTC+05:30");
      process.env.TZ = "America/New_York";
      expect(utcOffsetLabel(new Date("2026-01-01T00:00:00Z"))).toBe("UTC-05:00");
    } finally {
      process.env.TZ = ZONE;
    }
  });
});

it("handles a 30 minute change (Lord Howe, 5 Apr 2026: 02:00 back to 01:30)", () => {
  process.env.TZ = "Australia/Lord_Howe";
  try {
    expect(localTimeCandidates("2026-04-05T01:45:00")).toEqual({
      kind: "ambiguous",
      instants: ["2026-04-05T01:45:00+11:00", "2026-04-05T01:45:00+10:30"],
    });
    expect(localTimeCandidates("2026-04-05T01:15:00").kind).toBe("ok");
    expect(localTimeCandidates("2026-04-05T02:00:00").kind).toBe("ok");
  } finally {
    process.env.TZ = ZONE;
  }
});
