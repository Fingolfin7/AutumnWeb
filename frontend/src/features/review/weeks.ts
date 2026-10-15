import { addDays, parseDateKey } from "@/features/notifications/dates";

/* The review covers seven days chosen by ?week=YYYY-MM-DD, the first day of
   the window. Without it the window is the seven days ending yesterday, the
   same week the Sunday review notification summarises. */

/** The first day a `?week=` value points at, or null when it is absent or not a date. */
export function selectedStart(param: string | null): string | null {
  const value = (param ?? "").trim();
  return parseDateKey(value) ? value : null;
}

/** The default window's first day: a week before today. */
export function defaultStart(today: string): string {
  return addDays(today, -7);
}

export function shiftWeek(start: string, weeks: number): string {
  return addDays(start, weeks * 7);
}

/** The `week` query value for a window: none for the default, so its URL stays plain. */
export function weekParamFor(start: string, latest: string): string | null {
  return start === latest ? null : start;
}

/** Windows past the default one would include days that have not finished. */
export function canGoNext(start: string, latest: string): boolean {
  return start < latest;
}

/** One week on, but never past the default window. */
export function nextStart(start: string, latest: string): string {
  const next = shiftWeek(start, 1);
  return next < latest ? next : latest;
}

/** The Sessions page filtered to one review week. */
export function sessionsLink(weekStart: string, weekEnd: string): string {
  return `/sessions/?start_date=${weekStart}&end_date=${weekEnd}`;
}
