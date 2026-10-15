/* What a timer's reminder settings will do, for the "When this fires" rail on
   the start page (timer_reminders.js updateRail). Pure, so it is testable. */

export type ReminderMode = "none" | "after" | "interval" | "at";
export type DurationUnit = "minutes" | "hours";

export interface ReminderInputs {
  mode: ReminderMode;
  stopAfter: { amount: number | null; unit: DurationUnit } | null;
  after: { amount: number | null; unit: DurationUnit };
  interval: { amount: number | null; unit: DurationUnit };
  /** datetime-local value in the browser's zone. */
  at: string;
}

export interface RailTick {
  at: Date;
  /** 0-100 along the rail. */
  x: number;
  beyondStop: boolean;
  next: boolean;
}

export interface ReminderPlan {
  stopAt: Date | null;
  ticks: RailTick[];
  count: string;
  sentence: string;
  warning: string | null;
}

export function minutesOf(value: { amount: number | null; unit: DurationUnit } | null): number | null {
  if (!value || value.amount === null || !Number.isFinite(value.amount) || value.amount <= 0) return null;
  return value.amount * (value.unit === "hours" ? 60 : 1);
}

const clock = (date: Date) => new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(date);

export function planReminders(inputs: ReminderInputs, now = new Date()): ReminderPlan {
  const stopMinutes = minutesOf(inputs.stopAfter);
  const stopAt = stopMinutes === null ? null : new Date(now.getTime() + stopMinutes * 60000);
  const fires: Date[] = [];

  if (inputs.mode === "after") {
    const after = minutesOf(inputs.after);
    if (after !== null) fires.push(new Date(now.getTime() + after * 60000));
  } else if (inputs.mode === "interval") {
    const interval = minutesOf(inputs.interval);
    if (interval !== null) {
      const horizon = stopMinutes === null ? 120 : stopMinutes;
      const max = Math.min(8, Math.floor(horizon / interval));
      for (let i = 1; i <= max; i += 1) fires.push(new Date(now.getTime() + i * interval * 60000));
    }
  } else if (inputs.mode === "at" && inputs.at) {
    const candidate = new Date(inputs.at);
    if (!Number.isNaN(candidate.getTime())) fires.push(candidate);
  }

  const ticks = fires.map((at, index) => {
    const beyondStop = !!stopAt && at > stopAt;
    const denominator = stopAt ? stopAt.getTime() - now.getTime() : Math.max(120 * 60000, at.getTime() - now.getTime());
    const position = denominator > 0 ? ((at.getTime() - now.getTime()) / denominator) * 100 : 100;
    return { at, x: Math.max(0, Math.min(100, position)), beyondStop, next: !beyondStop && index === 0 };
  });

  const visible = fires.filter((fire) => !stopAt || fire <= stopAt);
  if (!fires.length || inputs.mode === "none") {
    return {
      stopAt,
      ticks: [],
      count: "No reminders",
      sentence: stopAt ? `No reminders. The timer stops itself at ${clock(stopAt)}.` : "No reminders. The timer runs until you stop it.",
      warning: null,
    };
  }
  const labels = visible.slice(0, 4).map(clock);
  const more = visible.length > labels.length ? " and more" : "";
  return {
    stopAt,
    ticks,
    count: visible.length === 1 ? "1 reminder" : `${visible.length} reminders`,
    sentence: visible.length
      ? `Notifies at ${labels.join(", ")}${more}${stopAt ? `, then stops itself at ${clock(stopAt)}.` : "."}`
      : `No reminder fires before the timer stops itself at ${clock(stopAt!)}.`,
    warning:
      visible.length !== fires.length
        ? "This reminder falls after the auto-stop and will not fire. Shorten the reminder or extend the timer."
        : null,
  };
}
