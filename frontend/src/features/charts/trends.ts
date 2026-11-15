import { bucketedSeries, SERIES_TOOLTIP } from "./basic";
import { addDays } from "date-fns";
import { bucketTotals, fmtHours, HOURS_AXIS, parseDay, periodDays, timeAxis, withAlpha, type ChartOptions, type DailySeriesRow, type Range } from "./data";
import { token } from "./theme";
import type { AnyConfig, TT, DailyTotalRow } from "./payloads";

/* Stacked area (projects / subprojects) and the cumulative line
   (core/static/core/js/charts/trends.js). */

/* The previous period drawn over a time chart: a thin dashed line in quiet
   ink, never stacked or filled. */
function previousLine(data: { x: Date; y: number }[]) {
  return { label: "Previous period", data, borderColor: token("--ink-2"), backgroundColor: token("--ink-2"), borderWidth: 1.5, borderDash: [5, 4], fill: false, stack: "previous" };
}

function stackedAreaConfig(rows: DailySeriesRow[], topN: number | undefined, { range, previous }: ChartOptions): AnyConfig {
  const { axis, series } = bucketedSeries(rows, topN, range);
  const datasets: object[] = series.map(({ name, color, data }, i) => ({
    label: name,
    data,
    borderColor: color,
    backgroundColor: withAlpha(color, 0.7),
    borderWidth: 1.5,
    /* Each band fills down to the one beneath it, not to zero, so the
       translucent fills never pile up. */
    fill: i === 0 ? "origin" : "-1",
    pointRadius: data.length > 1 ? 0 : 4,
  }));
  if (previous && range) {
    const totals = bucketTotals(previous as DailySeriesRow[], axis.bucket, periodDays(range));
    datasets.push(previousLine(axis.buckets.map((day) => ({ x: parseDay(day), y: totals.get(day) ?? 0 }))));
  }
  return {
    type: "line",
    data: { datasets },
    options: {
      interaction: { mode: "index", intersect: false },
      scales: { x: axis.scale, y: { ...HOURS_AXIS, stacked: true } },
      plugins: { tooltip: SERIES_TOOLTIP },
    },
  };
}

export const stackedAreaProjectsConfig = (data: DailySeriesRow[], options: ChartOptions) => stackedAreaConfig(data, options.projectLimit, options);
export const stackedAreaSubprojectsConfig = (data: DailySeriesRow[], options: ChartOptions) => stackedAreaConfig(data, undefined, options);

/* Running total from zero at the start of the range; `shift` moves a
   previous period's days onto this one's. */
function runningTotal(rows: DailyTotalRow[], range: Range | undefined, shift = 0) {
  const daily = new Map<string, number>();
  for (const row of rows) daily.set(row.date, (daily.get(row.date) ?? 0) + Number(row.hours));
  let running = 0;
  const points = [...daily.keys()].sort().map((day) => {
    const hours = daily.get(day)!;
    running += hours;
    return { x: addDays(parseDay(day), shift), y: running, daily: hours };
  });
  if (range) points.unshift({ x: parseDay(range.start), y: 0, daily: 0 });
  return points;
}

export function cumulativeConfig(data: DailyTotalRow[], { range, previous }: ChartOptions): AnyConfig {
  const points = runningTotal(data, range);
  const axis = timeAxis(points.map((point) => point.x), range);
  const brand = token("--brand");
  const datasets: object[] = [
    { label: previous ? "This period" : "Hours tracked", data: points, borderColor: brand, backgroundColor: withAlpha(brand, 0.12), fill: "origin" },
  ];
  if (previous && range) datasets.push(previousLine(runningTotal(previous as DailyTotalRow[], range, periodDays(range))));
  return {
    type: "line",
    data: { datasets },
    options: {
      interaction: { mode: "nearest", axis: "x", intersect: false },
      scales: { x: { ...axis.scale, time: { ...axis.scale.time, tooltipFormat: "EEE d MMM" } }, y: HOURS_AXIS },
      plugins: {
        legend: { display: !!previous },
        tooltip: {
          callbacks: {
            label(context: TT) {
              const point = context.raw as { y: number; daily: number };
              const lines = [`${context.dataset.label}: ${fmtHours(point.y)}`];
              if (point.daily) lines.push(`That day: +${fmtHours(point.daily)}`);
              return lines;
            },
          },
        },
      },
    },
  };
}
