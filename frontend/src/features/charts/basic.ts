import { buildSeries, consolidateTopN, dateExtent, getChartUnit, OTHER_COLOR, otherLabel, paletteColor, parseDay, type ChartOptions, type DailySeriesRow } from "./data";
import type { AnyConfig, TT, ScatterRow, StatusRow, TallyRow } from "./payloads";

/* Pie, bar, scatter, line, status and context charts
   (core/static/core/js/charts/basic.js). */

export function pieConfig(data: TallyRow[], { projectLimit }: ChartOptions): AnyConfig {
  const rows = consolidateTopN(data, projectLimit);
  return {
    type: "doughnut",
    data: {
      labels: rows.map((row) => row.name),
      datasets: [
        {
          data: rows.map((row) => row.total_time / 60),
          backgroundColor: rows.map((row, i) => ("_isOther" in row ? OTHER_COLOR : paletteColor(i))),
          borderWidth: 0.5,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        title: { display: true, text: "Project Time Distribution" },
        legend: { position: "top" },
      },
      cutout: "40%",
    },
  };
}

export function barConfig(data: TallyRow[], { projectLimit }: ChartOptions): AnyConfig {
  const rows = consolidateTopN(data, projectLimit);
  return {
    type: "bar",
    data: {
      labels: rows.map((row) => row.name),
      datasets: [
        {
          label: "Project Totals",
          data: rows.map((row) => row.total_time / 60),
          backgroundColor: rows.map((row, i) => ("_isOther" in row ? OTHER_COLOR : paletteColor(i))),
          borderWidth: 0.5,
        },
      ],
    },
    options: { responsive: true, indexAxis: "y" },
  };
}

interface ScatterGroup {
  name: string;
  other: boolean;
  points: { x: Date; y: number; projectName: string }[];
}

/* Group scatter points by series. Without `topN` (the subproject breakdown)
   series stay separate and sorted by name; with it the biggest N by total
   hours are kept and the rest fold into "Other (n)". */
export function groupScatter(rows: ScatterRow[], topN?: number): ScatterGroup[] {
  const groups = new Map<string, ScatterGroup["points"]>();
  for (const row of rows) {
    const list = groups.get(row.series) ?? [];
    list.push({ x: new Date(row.x), y: Number(row.y), projectName: row.series });
    groups.set(row.series, list);
  }
  if (topN === undefined) {
    return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([name, points]) => ({ name, other: false, points }));
  }
  const ranked = [...groups.entries()]
    .map(([name, points]) => ({ name, points, total: points.reduce((sum, p) => sum + p.y, 0) }))
    .sort((a, b) => b.total - a.total);
  const result: ScatterGroup[] = ranked.slice(0, topN).map(({ name, points }) => ({ name, other: false, points }));
  const rest = ranked.slice(topN);
  if (rest.length) {
    const name = otherLabel(rest.length);
    result.push({ name, other: true, points: rest.flatMap((group) => group.points.map((p) => ({ ...p, projectName: name }))) });
  }
  return result;
}

function scatterConfig(rows: ScatterRow[], topN: number | undefined): AnyConfig {
  const groups = groupScatter(rows, topN);
  const { min, max } = dateExtent(rows.map((row) => new Date(row.x)));
  const unit = topN === undefined ? "h" : "hours";
  return {
    type: "scatter",
    data: {
      datasets: groups.map((group, i) => ({
        label: group.name,
        data: group.points,
        backgroundColor: group.other ? OTHER_COLOR : paletteColor(i),
        pointHoverRadius: 6,
        pointStyle: "rect",
        pointRotation: 45,
      })),
    },
    options: {
      responsive: true,
      scales: {
        x: { type: "time", time: { unit: getChartUnit(max, min) }, title: { display: true, text: "Date" } },
        y: { beginAtZero: true, title: { display: true, text: "Duration (hours)" } },
      },
      plugins: {
        tooltip: {
          callbacks: { label: (context: TT) => `${context.dataset.label ?? ""}: ${context.parsed.y!.toFixed(2)} ${unit}` },
        },
      },
    },
  };
}

export const scatterProjectsConfig = (data: ScatterRow[], { projectLimit }: ChartOptions) => scatterConfig(data, projectLimit);
export const scatterSubprojectsConfig = (data: ScatterRow[]) => scatterConfig(data, undefined);

function lineConfig(rows: DailySeriesRow[], topN: number | undefined): AnyConfig {
  const set = buildSeries(rows, topN);
  const { min, max } = dateExtent(set.days.map((day) => parseDay(day)));
  return {
    type: "line",
    data: {
      datasets: set.names.map((name, i) => {
        const color = name === set.other ? OTHER_COLOR : paletteColor(i);
        const days = set.byDay[name]!;
        return {
          label: name,
          data: set.days.map((day) => ({ x: parseDay(day), y: days[day] ?? 0 })).filter((point) => point.y > 0),
          borderColor: color,
          backgroundColor: color,
          fill: false,
          tension: 0.1,
          pointRadius: 4,
          pointHoverRadius: 6,
        };
      }),
    },
    options: {
      responsive: true,
      scales: {
        x: { type: "time", time: { unit: getChartUnit(max, min) }, title: { display: true, text: "Date" } },
        y: { beginAtZero: true, title: { display: true, text: "Duration (hours)" } },
      },
      plugins: {
        tooltip: { callbacks: { label: (context: TT) => `${context.dataset.label}: ${context.parsed.y!.toFixed(2)} hours` } },
      },
    },
  };
}

export const lineProjectsConfig = (data: DailySeriesRow[], { projectLimit }: ChartOptions) => lineConfig(data, projectLimit);
export const lineSubprojectsConfig = (data: DailySeriesRow[]) => lineConfig(data, undefined);

const STATUS_COLORS: Record<string, string> = {
  active: "hsl(120, 70%, 50%)",
  paused: "hsl(45, 90%, 55%)",
  complete: "hsl(210, 70%, 55%)",
  archived: "hsl(0, 0%, 60%)",
};
const STATUS_ORDER = ["active", "paused", "complete", "archived"];

export function statusConfig(data: StatusRow[]): AnyConfig {
  const rows = STATUS_ORDER.map((status) => data.find((row) => row.status === status)).filter((row): row is StatusRow => !!row);
  return {
    type: "doughnut",
    data: {
      labels: rows.map((row) => `${row.status} (${row.count})`),
      datasets: [
        {
          data: rows.map((row) => row.total_time / 60),
          backgroundColor: rows.map((row) => STATUS_COLORS[row.status] ?? "#999"),
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        title: { display: true, text: "Time by Project Status" },
        legend: { position: "top" },
        tooltip: { callbacks: { label: (context: TT) => `${context.label}: ${(context.parsed as number).toFixed(1)} hours` } },
      },
      cutout: "50%",
    },
  };
}

export function contextConfig(data: TallyRow[]): AnyConfig {
  const rows = [...data].sort((a, b) => b.total_time - a.total_time);
  return {
    type: "bar",
    data: {
      labels: rows.map((row) => row.name),
      datasets: [
        {
          label: "Hours by Context",
          data: rows.map((row) => row.total_time / 60),
          backgroundColor: rows.map((_, i) => paletteColor(i)),
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      indexAxis: "y",
      plugins: {
        title: { display: true, text: "Time by Context" },
        legend: { display: false },
        tooltip: { callbacks: { label: (context: TT) => `${context.parsed.x!.toFixed(1)} hours` } },
      },
      scales: { x: { title: { display: true, text: "Hours" }, beginAtZero: true } },
    },
  };
}
