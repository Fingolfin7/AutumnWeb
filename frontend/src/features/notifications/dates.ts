/* Calendar-date helpers for the reminder and weekly-review pages. Dates here
   are "YYYY-MM-DD" keys in the profile timezone (the server's frame of
   reference), never browser-local midnights, so a laptop in another zone
   still names the same days the schedules fire on. */

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const pad = (n: number) => String(n).padStart(2, "0");

interface Ymd {
  year: number;
  month: number;
  day: number;
}

export function parseDateKey(key: string): Ymd | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key);
  if (!match) return null;
  const ymd = { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
  const check = new Date(Date.UTC(ymd.year, ymd.month - 1, ymd.day));
  if (check.getUTCMonth() !== ymd.month - 1 || check.getUTCDate() !== ymd.day) return null;
  return ymd;
}

function toKey(date: Date): string {
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

export function addDays(key: string, days: number): string {
  const ymd = parseDateKey(key);
  if (!ymd) return key;
  return toKey(new Date(Date.UTC(ymd.year, ymd.month - 1, ymd.day + days)));
}

/** "Thu 15 Oct" (Django's `D j M`), or with the year ("Thu 15 Oct 2026"). */
export function formatDateKey(key: string, withYear = false): string {
  const ymd = parseDateKey(key);
  if (!ymd) return key;
  const weekday = WEEKDAYS[new Date(Date.UTC(ymd.year, ymd.month - 1, ymd.day)).getUTCDay()];
  const text = `${weekday} ${ymd.day} ${MONTHS[ymd.month - 1]}`;
  return withYear ? `${text} ${ymd.year}` : text;
}

function zonedParts(instant: Date, timeZone: string) {
  let formatter: Intl.DateTimeFormat;
  try {
    formatter = new Intl.DateTimeFormat("en-US", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    });
  } catch {
    /* An unknown zone name: fall back to the browser's own. */
    formatter = new Intl.DateTimeFormat("en-US", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    });
  }
  const parts: Record<string, string> = {};
  for (const part of formatter.formatToParts(instant)) parts[part.type] = part.value;
  const hour = Number(parts.hour) % 24;
  return {
    key: `${parts.year}-${parts.month}-${parts.day}`,
    hour,
    minute: Number(parts.minute),
  };
}

/** Today's date key in `timeZone`. */
export function todayKey(timeZone: string, now: Date = new Date()): string {
  return zonedParts(now, timeZone).key;
}

/** "Thu 15 Oct, 09:00": an instant shown on the wall clock of `timeZone`. */
export function formatInstant(iso: string | null | undefined, timeZone: string): string {
  if (!iso) return "";
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return "";
  const parts = zonedParts(instant, timeZone);
  return `${formatDateKey(parts.key)}, ${pad(parts.hour)}:${pad(parts.minute)}`;
}

/** "HH:MM" from an API time ("09:00:00"). */
export function clockText(time: string | null | undefined): string {
  return (time ?? "").slice(0, 5);
}

/** A sensible first slot for a new reminder: the next whole hour. */
export function defaultSlot(timeZone: string, now: Date = new Date()): { date: string; time: string } {
  const parts = zonedParts(now, timeZone);
  if (parts.hour >= 23) return { date: addDays(parts.key, 1), time: "00:00" };
  return { date: parts.key, time: `${pad(parts.hour + 1)}:00` };
}
