/* Duration and time formatting. These mirror core/templatetags/time_formats.py
   so server-rendered pages and the app read the same; durations from the API
   are minutes (float). */

interface Parts {
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
}

/* Python's timedelta(minutes=x) keeps microseconds and the filters then read
   whole seconds. Rounding to the millisecond first stops 59.99999 float dust
   from showing a second short. */
export function splitMinutes(totalMinutes: number): Parts {
  const totalSeconds = Math.max(0, Math.floor(Math.round(totalMinutes * 60 * 1000) / 1000));
  return splitSeconds(totalSeconds);
}

export function splitSeconds(totalSeconds: number): Parts {
  const s = Math.max(0, Math.floor(totalSeconds));
  return {
    days: Math.floor(s / 86400),
    hours: Math.floor((s % 86400) / 3600),
    minutes: Math.floor((s % 3600) / 60),
    seconds: s % 60,
  };
}

const pad = (n: number) => String(n).padStart(2, "0");
const plural = (n: number, word: string) => (n === 1 ? word : word + "s");

/** "01d 02h 30m", "02h 05m" or "45m 30s" (the `duration_formatter` filter). */
export function formatDuration(minutes: number | null | undefined): string {
  const { days, hours, minutes: m, seconds } = splitMinutes(minutes ?? 0);
  if (days > 0) return `${pad(days)}d ${pad(hours)}h ${pad(m)}m`;
  if (hours > 0) return `${pad(hours)}h ${pad(m)}m`;
  return `${pad(m)}m ${pad(seconds)}s`;
}

/** Compact "2h 05m" / "45m" for chips and totals where seconds are noise. */
export function formatDurationShort(minutes: number | null | undefined): string {
  const { days, hours, minutes: m } = splitMinutes(minutes ?? 0);
  if (days > 0) return `${days}d ${pad(hours)}h`;
  if (hours > 0) return `${hours}h ${pad(m)}m`;
  return `${m}m`;
}

/** "3 hours 10 minutes": at most two non-zero units (`min_formatter_two`). */
export function formatDurationWords(minutes: number | null | undefined): string {
  const { days, hours, minutes: m, seconds } = splitMinutes(minutes ?? 0);
  const parts: string[] = [];
  if (days > 0) parts.push(`${days} ${plural(days, "day")}`);
  if (hours > 0) parts.push(`${hours} ${plural(hours, "hour")}`);
  if (m > 0) parts.push(`${m} ${plural(m, "minute")}`);
  if (seconds > 0) parts.push(`${seconds} ${plural(seconds, "second")}`);
  return parts.length ? parts.slice(0, 2).join(" ") : "0 seconds";
}

/** The two-unit hero split used by the focus cards (`hero_duration`). */
export function heroParts(totalSeconds: number): { value: number; unit: string }[] {
  const { days, hours, minutes, seconds } = splitSeconds(totalSeconds);
  const pairs: [number, string][] =
    days > 0
      ? [[days, "day"], [hours, "hour"]]
      : hours > 0
        ? [[hours, "hour"], [minutes, "minute"]]
        : [[minutes, "minute"], [seconds, "second"]];
  return pairs.map(([value, unit]) => ({ value, unit: plural(value, unit) }));
}

/** "HH:MM:SS" countdown. */
export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}

export function parseInstant(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** 24-hour local clock time, "14:05:09" (`time_formatter` + local_times.js). */
export function formatTime(value: string | Date | null | undefined, withSeconds = true): string {
  const date = value instanceof Date ? value : parseInstant(value);
  if (!date) return "";
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" } : {}),
    hour12: false,
  });
}

/** "Saturday 12 Jun 2021" (`day_date_formatter`). */
export function formatDayDate(value: string | Date | null | undefined): string {
  const date = value instanceof Date ? value : parseDateish(value);
  if (!date) return "";
  const weekday = date.toLocaleDateString("en-GB", { weekday: "long" });
  const month = date.toLocaleDateString("en-GB", { month: "short" });
  return `${weekday} ${pad(date.getDate())} ${month} ${date.getFullYear()}`;
}

/** "12 June 2021" (`date_formatter`). */
export function formatDate(value: string | Date | null | undefined): string {
  const date = value instanceof Date ? value : parseDateish(value);
  if (!date) return "";
  const month = date.toLocaleDateString("en-GB", { month: "long" });
  return `${pad(date.getDate())} ${month} ${date.getFullYear()}`;
}

/** "13 Aug" this year, "13 Aug 2025" otherwise. */
export function formatShortDate(value: string | Date | null | undefined, now = new Date()): string {
  const date = value instanceof Date ? value : parseDateish(value);
  if (!date) return "";
  const base = `${date.getDate()} ${date.toLocaleDateString("en-GB", { month: "short" })}`;
  return date.getFullYear() === now.getFullYear() ? base : `${base} ${date.getFullYear()}`;
}

/* "2026-10-14" is a calendar date, not midnight UTC: parse it as local. */
export function parseDateish(value: string | null | undefined): Date | null {
  if (!value) return null;
  const plain = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (plain) return new Date(Number(plain[1]), Number(plain[2]) - 1, Number(plain[3]));
  return parseInstant(value);
}

/** Local calendar date key, "2026-10-14". */
export function localDateKey(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Value for <input type="datetime-local"> in the browser's zone. */
export function toDateTimeLocal(value: string | Date | null | undefined, withSeconds = true): string {
  const date = value instanceof Date ? value : parseInstant(value);
  if (!date) return "";
  const base = `${localDateKey(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  return withSeconds ? `${base}:${pad(date.getSeconds())}` : base;
}

/** <input type="datetime-local"> value → ISO instant with the local offset. */
export function fromDateTimeLocal(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return toOffsetIso(date);
}

/** ISO 8601 with the browser's own offset, e.g. 2026-10-14T09:30:00+02:00. */
export function toOffsetIso(date: Date): string {
  const offset = -date.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const abs = Math.abs(offset);
  return (
    `${localDateKey(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
    `${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`
  );
}

export function elapsedSeconds(start: string | null | undefined, now = Date.now()): number {
  const date = parseInstant(start);
  if (!date) return 0;
  return Math.max(0, Math.floor((now - date.getTime()) / 1000));
}

export function pluralize(count: number, word: string, pluralWord = word + "s"): string {
  return `${count} ${count === 1 ? word : pluralWord}`;
}
