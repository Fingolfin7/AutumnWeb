import { bucketOf, buildSeries, consolidateTopN, dayKey, fmtHours, HOURS_AXIS, otherColor, otherLabel, paletteColor, parseDay, rowColor, timeAxis, withAlpha, type ChartOptions, type DailySeriesRow, type Range } from "./data";
import { token } from "./theme";
import type { AnyConfig, TT, ScatterRow, StatusRow, TallyRow } from "./payloads";

/* Pie, bar, scatter, line, status and context charts
   (core/static/core/js/charts/basic.js). */

const share = (context: TT) => {
  const total = (context.dataset.data as number[]).reduce((sum, value) => sum + value, 0);
  return total ? ` (${Math.round(((context.parsed as number) / total) * 100)}%)` : "";
};

function doughnut(labels: string[], values: number[], colors: string[]): AnyConfig {
  return {
    type: "doughnut",
    data: { labels, datasets: [{ data: values, backgroundColor: colors }] },
    options: {
      plugins: { tooltip: { callbacks: { label: (context: TT) => `${context.label}: ${fmtHours(context.parsed as number)}${share(context)}` } } },
    },
  };
}

export function pieConfig(data: TallyRow[], { projectLimit }: ChartOptions): AnyConfig {
  const rows = consolidateTopN(data, projectLimit);
  return doughnut(
    rows.map((row) => row.name),
    rows.map((row) => row.total_time / 60),
    rows.map(rowColor),
  );
}

/* The previous period's hours for each bar, matched by name; "Other (n)"
   takes whatever the named bars do not account for. */
export function previousTallies(rows: { name: string }[], previous: TallyRow[]): number[] {
  const byName = new Map(previous.map((row) => [row.name, row.total_time] as const));
  const total = previous.reduce((sum, row) => sum + row.total_time, 0);
  const named = rows.reduce((sum, row) => sum + ("_isOther" in row ? 0 : (byName.get(row.name) ?? 0)), 0);
  return rows.map((row) => ("_isOther" in row ? total - named : (byName.get(row.name) ?? 0)) / 60);
}

/* Horizontal bars of hours by name (projects or contexts); with a previous
   period, each bar gets a faded twin underneath. The axis names the bars,
   so there is no legend. */
function tallyBars(rows: (TallyRow & { _isOther?: true })[], previous: TallyRow[] | undefined): AnyConfig {
  const colors = rows.map(rowColor);
  const datasets = [{ label: "This period", data: rows.map((row) => row.total_time / 60), backgroundColor: colors }];
  if (previous) {
    datasets.push({ label: "Previous period", data: previousTallies(rows, previous), backgroundColor: colors.map((color) => withAlpha(color, 0.3)) });
  }
  return {
    type: "bar",
    data: { labels: rows.map((row) => row.name), datasets },
    options: {
      indexAxis: "y",
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (context: TT) => `${previous ? `${context.dataset.label}: ` : ""}${fmtHours(context.parsed.x!)}` } },
      },
      scales: { x: HOURS_AXIS, y: { grid: { display: false }, ticks: { color: token("--ink-2") } } },
    },
  };
}

export const barConfig = (data: TallyRow[], { projectLimit, previous }: ChartOptions) =>
  tallyBars(consolidateTopN(data, projectLimit), previous as TallyRow[] | undefined);
export const contextConfig = (data: TallyRow[], { previous }: ChartOptions) =>
  tallyBars([...data].sort((a, b) => b.total_time - a.total_time), previous as TallyRow[] | undefined);

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

function scatterConfig(rows: ScatterRow[], topN: number | undefined, range: Range | undefined): AnyConfig {
  const axis = timeAxis(rows.map((row) => new Date(row.x)), range);
  return {
    type: "scatter",
    data: {
      datasets: groupScatter(rows, topN).map((group, i) => ({
        label: group.name,
        data: group.points,
        backgroundColor: withAlpha(group.other ? otherColor() : paletteColor(i), 0.85),
        pointRadius: 4,
        pointHoverRadius: 6,
      })),
    },
    options: {
      scales: { x: { ...axis.scale, time: { ...axis.scale.time, tooltipFormat: "EEE d MMM, HH:mm" } }, y: HOURS_AXIS },
      plugins: { tooltip: { callbacks: { label: (context: TT) => `${context.dataset.label ?? ""}: ${fmtHours(context.parsed.y!)}` } } },
    },
  };
}

export const scatterProjectsConfig = (data: ScatterRow[], { projectLimit, range }: ChartOptions) => scatterConfig(data, projectLimit, range);
export const scatterSubprojectsConfig = (data: ScatterRow[], { range }: ChartOptions) => scatterConfig(data, undefined, range);

/* Index tooltips of the multi-series time charts: biggest first, empty
   series left out. */
export const SERIES_TOOLTIP = {
  itemSort: (a: TT, b: TT) => b.parsed.y! - a.parsed.y!,
  filter: (item: TT) => item.parsed.y! > 0,
  callbacks: { label: (context: TT) => `${context.dataset.label}: ${fmtHours(context.parsed.y!)}` },
};

/* Daily series summed into the axis's buckets, with every bucket on the
   axis present (zero where nothing was tracked) so lines do not bridge gaps. */
export function bucketedSeries(rows: DailySeriesRow[], topN: number | undefined, range: Range | undefined) {
  const axis = timeAxis(rows.map((row) => parseDay(row.date)), range);
  const set = buildSeries(rows.map((row) => ({ ...row, date: dayKey(bucketOf(parseDay(row.date), axis.bucket)) })), topN);
  const series = set.names.map((name, i) => ({
    name,
    color: name === set.other ? otherColor() : paletteColor(i),
    data: axis.buckets.map((day) => ({ x: parseDay(day), y: set.byDay[name]![day] ?? 0 })),
  }));
  return { axis, series };
}

function lineConfig(rows: DailySeriesRow[], topN: number | undefined, range: Range | undefined): AnyConfig {
  const { axis, series } = bucketedSeries(rows, topN, range);
  return {
    type: "line",
    data: {
      datasets: series.map(({ name, color, data }) => ({
        label: name,
        data,
        borderColor: color,
        backgroundColor: color,
        pointRadius: data.length > 1 ? 0 : 4,
      })),
    },
    options: {
      interaction: { mode: "index", intersect: false },
      scales: { x: axis.scale, y: HOURS_AXIS },
      plugins: { tooltip: SERIES_TOOLTIP },
    },
  };
}

export const lineProjectsConfig = (data: DailySeriesRow[], { projectLimit, range }: ChartOptions) => lineConfig(data, projectLimit, range);
export const lineSubprojectsConfig = (data: DailySeriesRow[], { range }: ChartOptions) => lineConfig(data, undefined, range);

/* Project status in the app's own hues: growing green, paused ochre, done
   blue, archived grey. */
const STATUS_TOKENS = { active: "--duration", paused: "--note", complete: "--sub", archived: "--muted" } as const;
const STATUS_ORDER = ["active", "paused", "complete", "archived"] as const;

export function statusConfig(data: StatusRow[]): AnyConfig {
  const rows = STATUS_ORDER.map((status) => data.find((row) => row.status === status)).filter((row): row is StatusRow => !!row);
  return doughnut(
    rows.map((row) => `${row.status} (${row.count})`),
    rows.map((row) => row.total_time / 60),
    rows.map((row) => token(STATUS_TOKENS[row.status as keyof typeof STATUS_TOKENS])),
  );
}
