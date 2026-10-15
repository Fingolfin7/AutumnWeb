import { planReminders, type ReminderInputs } from "./reminderPlan";

const now = new Date(2026, 9, 14, 9, 0, 0);
const base: ReminderInputs = {
  mode: "none",
  stopAfter: null,
  after: { amount: null, unit: "minutes" },
  interval: { amount: null, unit: "minutes" },
  at: "",
};

it("explains an open-ended timer with no reminders", () => {
  const plan = planReminders(base, now);
  expect(plan.count).toBe("No reminders");
  expect(plan.sentence).toBe("No reminders. The timer runs until you stop it.");
  expect(plan.ticks).toEqual([]);
});

it("places a once-after reminder against the auto-stop", () => {
  const plan = planReminders(
    { ...base, mode: "after", after: { amount: 30, unit: "minutes" }, stopAfter: { amount: 1, unit: "hours" } },
    now,
  );
  expect(plan.ticks).toHaveLength(1);
  expect(plan.ticks[0]!.x).toBeCloseTo(50);
  expect(plan.ticks[0]!.next).toBe(true);
  expect(plan.count).toBe("1 reminder");
  expect(plan.warning).toBeNull();
});

it("caps interval reminders at eight within a two-hour horizon", () => {
  const plan = planReminders({ ...base, mode: "interval", interval: { amount: 10, unit: "minutes" } }, now);
  expect(plan.ticks).toHaveLength(8);
  expect(plan.sentence.endsWith(" and more.")).toBe(true);
});

it("warns when the reminder lands after the auto-stop", () => {
  const plan = planReminders(
    { ...base, mode: "after", after: { amount: 2, unit: "hours" }, stopAfter: { amount: 30, unit: "minutes" } },
    now,
  );
  expect(plan.ticks[0]!.beyondStop).toBe(true);
  expect(plan.warning).toMatch(/after the auto-stop/);
  expect(plan.count).toBe("0 reminders");
});
