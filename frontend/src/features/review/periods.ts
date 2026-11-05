import { addDays, parseDateKey } from "@/features/notifications/dates";

export type Period = { start: string; end: string };
export type Preset = "today" | "week" | "last" | "month" | "custom";

export function calendarWeek(today: string): Period {
  const weekday = new Date(`${today}T12:00:00Z`).getUTCDay();
  const start = addDays(today, -((weekday + 6) % 7));
  return { start, end: addDays(start, 6) };
}

export function presetPeriod(preset: Preset, today: string): Period {
  const week = calendarWeek(today);
  if (preset === "today") return { start: today, end: today };
  if (preset === "last") return { start: addDays(week.start, -7), end: addDays(week.end, -7) };
  if (preset === "month") return { start: addDays(today, -29), end: today };
  return week;
}

export function periodDays(period: Period): number {
  return Math.round((Date.parse(period.end) - Date.parse(period.start)) / 86400000) + 1;
}

export function readPeriod(params: URLSearchParams, today: string): Period {
  const fallback = calendarWeek(today);
  const start = params.get("start_date") || "";
  const end = params.get("end_date") || "";
  if (!parseDateKey(start) && !parseDateKey(end)) return fallback;
  const validStart = parseDateKey(start) ? start : fallback.start;
  const validEnd = parseDateKey(end) ? end : fallback.end;
  return validEnd >= validStart ? { start: validStart, end: validEnd } : { start: validStart, end: validStart };
}

/** The complete preceding period remains available as secondary context. */
export function comparisonPeriod(period: Period): Period {
  const span = periodDays(period);
  return { start: addDays(period.start, -span), end: addDays(period.end, -span) };
}

export function legacyReviewTarget(pathname: string, search: string, today: string): string {
  const params = new URLSearchParams(search);
  if (pathname.startsWith("/review/weekly")) {
    const week = params.get("week");
    const start = week && parseDateKey(week) ? week : addDays(today, -7);
    params.delete("week");
    params.set("start_date", start);
    params.set("end_date", addDays(start, 6));
  } else if (!params.has("chart_type")) {
    // Bookmarked Charts links retain their original default visualization.
    params.set("chart_type", "pie");
  }
  return `/review/${params.size ? `?${params}` : ""}`;
}

/** Compare matching elapsed calendar days, including today; never a partial week against seven days. */
export function elapsedComparison(period: Period, today: string): Period {
  const previous = comparisonPeriod(period);
  const elapsed = Math.max(1, Math.min(periodDays(period), periodDays({ start: period.start, end: today })));
  return { start: previous.start, end: addDays(previous.start, elapsed - 1) };
}
