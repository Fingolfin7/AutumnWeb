import { format } from "date-fns";

/* Shared helpers for the chart builders: palette, "top N + Other" folding,
   day parsing and the axis unit. Pure, so the data shaping is unit-tested
   without a canvas. Ported from core/static/core/js/charts/core.js. */

/* The Night Ledger palette (charts/core.js generateRandomColor). */
export const PALETTE = [
  "#c98245", "#4e9a8e", "#b9a66a", "#7896b8",
  "#7ca36a", "#be675f", "#9b83a7", "#8c7656",
  "#66837f", "#a87854", "#6f8465", "#596d80",
];
export const OTHER_COLOR = "hsl(0, 0%, 70%)";

export function paletteColor(index: number): string {
  return PALETTE[index % PALETTE.length]!;
}

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
}

export function otherLabel(count: number): string {
  return `Other (${count})`;
}

/* Keep the top N rows by time and fold the rest into one "Other (n)" row.
   Rows are returned untouched (not re-sorted) when there are N or fewer. */
export function consolidateTopN<T extends { name: string; total_time: number }>(
  rows: T[],
  topN: number,
): (T | { name: string; total_time: number; _isOther: true })[] {
  if (!rows || rows.length <= topN) return rows;
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
  /** Sorted unique days across every series. */
  days: string[];
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
  const days = [...new Set(Object.values(byDay).flatMap((series) => Object.keys(series)))].sort();
  return { names, other, byDay, days };
}
