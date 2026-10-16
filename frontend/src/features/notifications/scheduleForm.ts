import type { components } from "@/api/schema";
import { clockText } from "./dates";

export type Schedule = components["schemas"]["Schedule"];
export type ScheduleWrite = components["schemas"]["ScheduleWrite"];
export type Target = ScheduleWrite["target"];
export type Cadence = ScheduleWrite["cadence"];

export const TARGET_OPTIONS: { value: Target; label: string }[] = [
  { value: "project", label: "A project" },
  { value: "context", label: "A context" },
  { value: "tag", label: "A tag" },
];

export const CADENCE_OPTIONS: { value: Cadence; label: string }[] = [
  { value: "once", label: "Once" },
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
];

export const CADENCE_LABEL: Record<string, string> = { once: "Once", daily: "Daily", weekly: "Weekly" };

/* What the schedule editor holds while it is open. Ids are strings because
   they come from <select> values; "" means nothing chosen yet. */
export interface ScheduleForm {
  target: Target;
  project: string;
  context: string;
  tag: string;
  subprojects: number[];
  date: string;
  time: string;
  cadence: Cadence;
  message: string;
}

export function emptyForm(slot: { date: string; time: string }): ScheduleForm {
  return { target: "project", project: "", context: "", tag: "", subprojects: [], ...slot, cadence: "once", message: "" };
}

export function formFromSchedule(schedule: Schedule): ScheduleForm {
  const target = (schedule.target as Target) ?? "project";
  const id = String(schedule.target_resource.id);
  return {
    target,
    project: target === "project" ? id : "",
    context: target === "context" ? id : "",
    tag: target === "tag" ? id : "",
    subprojects: schedule.subprojects.map((sub) => sub.id),
    date: schedule.local_date,
    time: clockText(schedule.local_time),
    cadence: (schedule.cadence as Cadence) ?? "once",
    message: schedule.message,
  };
}

/** The id the form's current target points at, or null when none is chosen. */
export function targetId(form: ScheduleForm): number | null {
  const raw = form[form.target];
  const id = Number(raw);
  return raw !== "" && Number.isInteger(id) && id > 0 ? id : null;
}

/** Local problems worth catching before a round trip; the server stays the authority. */
export function validateForm(form: ScheduleForm): Record<string, string> {
  const problems: Record<string, string> = {};
  if (targetId(form) === null) problems[form.target] = `Choose a ${form.target}.`;
  if (!form.date) problems.local_date = "Choose a date.";
  if (!form.time) problems.local_time = "Choose a time.";
  if (form.message.length > 240) problems.message = "Keep the message to 240 characters.";
  return problems;
}

/** The request body: only the chosen target carries an id, and subprojects only belong to a project. */
export function toPayload(form: ScheduleForm, version?: number): ScheduleWrite {
  const id = targetId(form);
  return {
    target: form.target,
    project: form.target === "project" ? id : null,
    context: form.target === "context" ? id : null,
    tag: form.target === "tag" ? id : null,
    subprojects: form.target === "project" ? form.subprojects : [],
    local_date: form.date,
    local_time: form.time,
    cadence: form.cadence,
    message: form.message.trim(),
    ...(version === undefined ? {} : { version }),
  };
}

/** Switching project drops subprojects that belong to the old one. */
export function keepSubprojects(selected: number[], available: { id: number }[]): number[] {
  const ids = new Set(available.map((item) => item.id));
  return selected.filter((id) => ids.has(id));
}

export function toggleId(list: number[], id: number): number[] {
  return list.includes(id) ? list.filter((item) => item !== id) : [...list, id];
}
