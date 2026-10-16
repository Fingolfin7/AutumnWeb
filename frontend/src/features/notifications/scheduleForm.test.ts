import { emptyForm, formFromSchedule, keepSubprojects, toggleId, toPayload, validateForm, type Schedule } from "./scheduleForm";

const slot = { date: "2026-10-15", time: "09:00" };

const schedule: Schedule = {
  id: 7,
  target: "project",
  target_resource: { id: 3, name: "Reading" },
  subprojects: [{ id: 11, name: "Chapter 2" }],
  message: "Read",
  cadence: "daily",
  timezone: "UTC",
  local_date: "2026-10-15",
  local_time: "21:30:00",
  next_fire_at: null,
  snoozed_until: null,
  active: true,
  version: 4,
};

it("starts a new reminder as a one-off project reminder in the given slot", () => {
  expect(emptyForm(slot)).toMatchObject({ target: "project", cadence: "once", date: "2026-10-15", time: "09:00", subprojects: [] });
});

it("round-trips a schedule through the form", () => {
  const form = formFromSchedule(schedule);
  expect(form).toMatchObject({ target: "project", project: "3", context: "", time: "21:30", subprojects: [11], cadence: "daily" });
  expect(toPayload(form, 4)).toEqual({
    target: "project",
    project: 3,
    context: null,
    tag: null,
    subprojects: [11],
    local_date: "2026-10-15",
    local_time: "21:30",
    cadence: "daily",
    message: "Read",
    version: 4,
  });
});

it("sends only the chosen target and no subprojects for contexts and tags", () => {
  const form = { ...emptyForm(slot), target: "context" as const, context: "5", project: "3", subprojects: [1] };
  expect(toPayload(form)).toMatchObject({ target: "context", context: 5, project: null, tag: null, subprojects: [] });
  expect("version" in toPayload(form)).toBe(false);
});

it("asks for the missing pieces", () => {
  expect(validateForm(emptyForm({ date: "", time: "" }))).toEqual({
    project: "Choose a project.",
    local_date: "Choose a date.",
    local_time: "Choose a time.",
  });
  expect(validateForm({ ...emptyForm(slot), project: "3" })).toEqual({});
  expect(validateForm({ ...emptyForm(slot), target: "tag" })).toEqual({ tag: "Choose a tag." });
});

it("drops subprojects that are not in the chosen project", () => {
  expect(keepSubprojects([1, 2, 3], [{ id: 2 }, { id: 3 }])).toEqual([2, 3]);
  expect(keepSubprojects([1], [])).toEqual([]);
});

it("toggles subproject ids", () => {
  expect(toggleId([1, 2], 2)).toEqual([1]);
  expect(toggleId([1], 2)).toEqual([1, 2]);
});
