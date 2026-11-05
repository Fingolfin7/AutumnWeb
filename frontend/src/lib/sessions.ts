import { localDateKey, parseInstant } from "./format";

interface Groupable {
  start: string;
  end: string | null;
  duration_minutes: number | null;
}

export interface DayGroup<T> {
  /** Local calendar date "YYYY-MM-DD" of the session portion. */
  date: string;
  totalMinutes: number;
  sessions: T[];
}

/** Split at local midnights (including DST), retaining the stored duration. */
export function dayPortions(session: Groupable): { date: string; minutes: number }[] {
  const start = parseInstant(session.start), end = parseInstant(session.end);
  if (!start || !end || end <= start) return end ? [{ date: localDateKey(end), minutes: session.duration_minutes ?? 0 }] : [];
  const duration = session.duration_minutes ?? (end.getTime() - start.getTime()) / 60000;
  const portions: { date: string; minutes: number }[] = [];
  let cursor = start.getTime();
  while (cursor < end.getTime()) {
    const date = new Date(cursor), next = new Date(date);
    next.setHours(24, 0, 0, 0);
    const stop = Math.min(next.getTime(), end.getTime());
    portions.push({ date: localDateKey(date), minutes: duration * (stop - cursor) / (end.getTime() - start.getTime()) });
    cursor = stop;
  }
  return portions;
}

/** Local-day overlap, newest first; the full session remains accessible in each day. */
export function groupByDay<T extends Groupable>(sessions: T[]): DayGroup<T>[] {
  const groups = new Map<string, DayGroup<T>>();
  for (const session of sessions) {
    for (const part of dayPortions(session)) {
      let group = groups.get(part.date);
      if (!group) { group = { date: part.date, totalMinutes: 0, sessions: [] }; groups.set(part.date, group); }
      group.sessions.push(session);
      group.totalMinutes += part.minutes;
    }
  }
  return [...groups.values()].sort((a, b) => b.date.localeCompare(a.date));
}
