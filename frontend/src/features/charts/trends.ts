import { buildSeries, dateExtent, getChartUnit, OTHER_COLOR, paletteColor, parseDay, type ChartOptions, type DailySeriesRow } from "./data";
import type { AnyConfig, TT, DailyTotalRow } from "./payloads";

/* Stacked area (projects / subprojects) and the cumulative line
   (core/static/core/js/charts/trends.js). */

function stackedAreaConfig(rows: DailySeriesRow[], topN: number | undefined): AnyConfig {
  const set = buildSeries(rows, topN);
  const { min, max } = dateExtent(set.days.map((day) => parseDay(day)));
  const subprojects = topN === undefined;
  return {
    type: "line",
    data: {
      datasets: set.names.map((name, i) => {
        const color = name === set.other ? OTHER_COLOR : paletteColor(i);
        const days = set.byDay[name]!;
        return {
          label: name,
          /* Every day, zero where missing, so the stack lines up. */
          data: set.days.map((day) => ({ x: parseDay(day), y: days[day] ?? 0 })),
          borderColor: color,
          backgroundColor: color,
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          pointHoverRadius: 4,
        };
      }),
    },
    options: {
      responsive: true,
      scales: {
        x: { type: "time", time: { unit: getChartUnit(max, min) }, title: { display: true, text: "Date" } },
        y: { stacked: true, beginAtZero: true, title: { display: true, text: "Hours" } },
      },
      plugins: {
        title: { display: true, text: subprojects ? "Daily Time by Subproject (Stacked)" : "Daily Time by Project (Stacked)" },
        tooltip: {
          mode: "index",
          callbacks: { label: (context: TT) => `${context.dataset.label}: ${context.parsed.y!.toFixed(2)} hours` },
        },
        ...(subprojects ? {} : { filler: { propagate: true } }),
      },
      interaction: { mode: "nearest", axis: "x", intersect: false },
    },
  };
}

export const stackedAreaProjectsConfig = (data: DailySeriesRow[], { projectLimit }: ChartOptions) => stackedAreaConfig(data, projectLimit);
export const stackedAreaSubprojectsConfig = (data: DailySeriesRow[]) => stackedAreaConfig(data, undefined);

export function cumulativeConfig(data: DailyTotalRow[]): AnyConfig {
  const daily = new Map(data.map((row) => [row.date, Number(row.hours)] as const));
  const days = [...daily.keys()].sort();
  let running = 0;
  const points = days.map((day) => {
    const hours = daily.get(day)!;
    running += hours;
    return { x: parseDay(day), y: running, daily: hours };
  });
  const { min, max } = dateExtent(points.map((point) => point.x));

  return {
    type: "line",
    data: {
      datasets: [
        {
          label: "Cumulative Hours",
          data: points,
          borderColor: "hsl(210, 70%, 55%)",
          backgroundColor: "hsla(210, 70%, 55%, 0.2)",
          fill: true,
          tension: 0.2,
          pointRadius: 3,
          pointHoverRadius: 6,
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        x: { type: "time", time: { unit: getChartUnit(max, min) }, title: { display: true, text: "Date" } },
        y: { beginAtZero: true, title: { display: true, text: "Total Hours" } },
      },
      plugins: {
        title: { display: true, text: "Cumulative Time Tracked" },
        tooltip: {
          callbacks: {
            label(context: TT) {
              const point = context.raw as { y: number; daily: number };
              return [`Total: ${point.y.toFixed(1)} hours`, `This day: +${point.daily.toFixed(2)} hours`];
            },
          },
        },
      },
    },
  };
}
