import { addDays, differenceInCalendarDays, endOfDay, format, startOfMonth, startOfWeek, subDays } from "date-fns";
import { seriesColor, token } from "./theme";

/* Shared helpers for the chart builders: palette, "top N + Other" folding,
   day parsing and the axis unit. Pure, so the data shaping is unit-tested
   without a canvas. Ported from core/static/core/js/charts/core.js. */

export function paletteColor(index: number): string {
  return seriesColor(index);
}

/* "Other (n)" is a remainder, not an entity: it stays grey. */
export function otherColor(): string {
  return token("--muted");
}

export function rowColor(row: object, index: number): string {
  return "_isOther" in row ? otherColor() : paletteColor(index);
}

/* One hours format for ticks and tooltips. */
export function fmtHours(hours: number): string {
  return `${hours < 10 ? hours.toFixed(1) : Math.round(hours)} h`;
}

/* The value axis of every hours chart: from zero, ticks in hours. */
export const HOURS_AXIS = { beginAtZero: true, ticks: { callback: (value: number | string) => `${value} h` } };

/* The same colour with an alpha channel. The old code did string surgery on
   "hsl(...)" values, which silently did nothing to the hex palette (so the
   radar fills came out opaque); this handles both forms. */
export function withAlpha(color: string, alpha: number): string {
  const hex = /^#([0-9a-f]{6})$/i.exec(color);
  if (hex) {
    const n = parseInt(hex[1]!, 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
  }
  const hsl = /^hsl\((.+)\)$/i.exec(color);
  if (hsl) return `hsla(${hsl[1]}, ${alpha})`;
  return color;
}

export interface ChartOptions {
  /** profile.default_chart_project_count: how many series before "Other". */
  projectLimit: number;
  /** The selected range (inclusive days), when known: it pins the time axis. */
  range?: Range;
  /** The previous period's payload, for the kinds that draw it in the same chart. */
  previous?: unknown;
  /** [smallest, largest] value across both periods' panels, so they share a scale. */
  extent?: [number, number];
}

/* ---- periods ------------------------------------------------------------ */

export interface Range {
  start: string;
  end: string;
}

export function periodDays({ start, end }: Range): number {
  return differenceInCalendarDays(parseDay(end), parseDay(start)) + 1;
}

/* The window of equal length that ends the day before `range` starts, or
   null when the range is backwards. */
export function previousRange(range: Range): Range | null {
  const days = periodDays(range);
  if (days < 1) return null;
  const start = parseDay(range.start);
  return { start: dayKey(subDays(start, days)), end: dayKey(subDays(start, 1)) };
}

export function otherLabel(count: number): string {
  return `Other (${count})`;
}

/* The top N rows by time, biggest first, with the rest folded into one
   "Other (n)" row. */
export function consolidateTopN<T extends { name: string; total_time: number }>(
  rows: T[],
  topN: number,
): (T | { name: string; total_time: number; _isOther: true })[] {
  /* Always by time, so a project wears the same colour on every kind. */
  const sorted = [...rows].sort((a, b) => (b.total_time || 0) - (a.total_time || 0));
  const top: (T | { name: string; total_time: number; _isOther: true })[] = sorted.slice(0, topN);
  const rest = sorted.slice(topN);
  if (rest.length) {
    top.push({ name: otherLabel(rest.length), total_time: rest.reduce((sum, r) => sum + (r.total_time || 0), 0), _isOther: true });
  }
  return top;
}

/* "YYYY-MM-DD" as a local-midnight Date. new Date("2026-10-14") is UTC
   midnight, which the time axis then draws on the previous day anywhere west
   of Greenwich. */
export function parseDay(day: string): Date {
  const [y, m, d] = day.slice(0, 10).split("-").map(Number);
  return new Date(y!, (m ?? 1) - 1, d ?? 1);
}

export function dayKey(date: Date): string {
  return format(date, "yyyy-MM-dd");
}

export function fillDates(min: Date, max: Date): Date[] {
  const days: Date[] = [];
  for (let day = new Date(min); day <= max; day.setDate(day.getDate() + 1)) days.push(new Date(day));
  return days;
}

export type TimeUnit = "day" | "week" | "month" | "year";

/* Axis unit for a span of dates. */
export function getChartUnit(end: Date, start: Date): TimeUnit {
  const days = Math.round((end.getTime() - start.getTime()) / 86_400_000);
  const months = (end.getFullYear() - start.getFullYear()) * 12 + end.getMonth() - start.getMonth();
  if (days <= 21) return "day";
  if (days <= 90) return "week";
  if (months <= 18) return "month";
  return "year";
}

export function dateExtent(dates: Date[]): { min: Date; max: Date } {
  let min = dates[0]!;
  let max = dates[0]!;
  for (const date of dates) {
    if (date < min) min = date;
    if (date > max) max = date;
  }
  return { min, max };
}

/* ---- daily series (line + stacked area) --------------------------------- */

export interface DailySeriesRow {
  date: string;
  series: string;
  hours: number | string;
}

export interface SeriesSet {
  /** Series names in draw order; the folded "Other (n)" series is last. */
  names: string[];
  /** Name of the folded series, if there is one. */
  other: string | null;
  /** series -> day -> hours */
  byDay: Record<string, Record<string, number>>;
}

/* Group rows by series and day. With `topN`, series beyond the N biggest
   (by total hours) fold into one "Other (n)" series, drawn last. Without it
   (subproject breakdowns) every series stays, sorted by name. */
export function buildSeries(rows: DailySeriesRow[], topN?: number): SeriesSet {
  const byDay: Record<string, Record<string, number>> = {};
  const totals: Record<string, number> = {};
  for (const row of rows) {
    const hours = Number(row.hours);
    const days = (byDay[row.series] ??= {});
    days[row.date] = (days[row.date] ?? 0) + hours;
    totals[row.series] = (totals[row.series] ?? 0) + hours;
  }

  let other: string | null = null;
  let names: string[];
  if (topN === undefined) {
    names = Object.keys(byDay).sort((a, b) => a.localeCompare(b));
  } else {
    const ranked = Object.entries(totals).sort((a, b) => b[1] - a[1]);
    const folded = ranked.slice(topN);
    names = ranked.slice(0, topN).map(([name]) => name);
    if (folded.length) {
      other = otherLabel(folded.length);
      const merged: Record<string, number> = {};
      for (const [name] of folded) {
        for (const [day, hours] of Object.entries(byDay[name]!)) merged[day] = (merged[day] ?? 0) + hours;
        delete byDay[name];
      }
      byDay[other] = merged;
      names.push(other);
    }
  }
  return { names, other, byDay };
}

/* ---- time axis ---------------------------------------------------------- */

export type Bucket = "day" | "week" | "month";

const TOOLTIP_FORMAT: Record<Bucket, string> = { day: "EEE d MMM", week: "'Week of' d MMM", month: "MMMM yyyy" };

export function bucketOf(day: Date, bucket: Bucket): Date {
  if (bucket === "week") return startOfWeek(day, { weekStartsOn: 1 });
  if (bucket === "month") return startOfMonth(day);
  return day;
}

/* The x axis of the time-series kinds. It spans the selected range when there
   is one (else the data), and names the bucket daily values are summed into:
   the axis unit, so a quarter reads as weekly totals rather than daily
   spikes. `buckets` lists every bucket on the axis, empty ones included. */
export function timeAxis(dates: Date[], range?: Range) {
  const { min, max } = range ? { min: parseDay(range.start), max: parseDay(range.end) } : dateExtent(dates);
  const unit = getChartUnit(max, min);
  const bucket: Bucket = unit === "day" || unit === "week" ? unit : "month";
  const buckets = [...new Set(fillDates(min, max).map((day) => dayKey(bucketOf(day, bucket))))];
  return {
    bucket,
    buckets,
    scale: {
      type: "time" as const,
      min: bucketOf(min, bucket).getTime(),
      max: endOfDay(max).getTime(),
      time: { unit, isoWeekday: true, tooltipFormat: TOOLTIP_FORMAT[bucket] },
      ticks: { maxRotation: 0, autoSkipPadding: 16 },
    },
  };
}

/* Hours per bucket of dated rows, each day first moved `shift` days on (to
   lay the previous period over this one). */
export function bucketTotals(rows: { date: string; hours: number | string }[], bucket: Bucket, shift = 0): Map<string, number> {
  const totals = new Map<string, number>();
  for (const row of rows) {
    const key = dayKey(bucketOf(addDays(parseDay(row.date), shift), bucket));
    totals.set(key, (totals.get(key) ?? 0) + Number(row.hours));
  }
  return totals;
}
