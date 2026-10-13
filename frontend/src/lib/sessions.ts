import { localDateKey, parseInstant } from "./format";

interface Groupable {
  end: string | null;
  duration_minutes: number | null;
}

export interface DayGroup<T> {
  /** Local calendar date "YYYY-MM-DD" of the sessions' end. */
  date: string;
  totalMinutes: number;
  sessions: T[];
}

/* Day groups by local end date, newest first (core.utils.group_sessions_by_date).
   Input order within a day is preserved. */
export function groupByDay<T extends Groupable>(sessions: T[]): DayGroup<T>[] {
  const groups = new Map<string, DayGroup<T>>();
  for (const session of sessions) {
    const end = parseInstant(session.end);
    if (!end) continue;
    const key = localDateKey(end);
    let group = groups.get(key);
    if (!group) {
      group = { date: key, totalMinutes: 0, sessions: [] };
      groups.set(key, group);
    }
    group.sessions.push(session);
    group.totalMinutes += session.duration_minutes ?? 0;
  }
  return [...groups.values()].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
}
