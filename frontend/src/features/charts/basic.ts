import { addDays, format } from "date-fns";
import { bucketOf, buildSeries, consolidateTopN, dayKey, fmtHours, HOURS_AXIS, otherColor, otherLabel, paletteColor, parseDay, periodDays, rowColor, timeAxis, withAlpha, type ChartOptions, type DailySeriesRow, type Range } from "./data";
import { token } from "./theme";
import type { AnyConfig, TT, ScatterRow, StatusRow, TallyRow } from "./payloads";

/* Pie, bar, scatter, line, status and context charts
   (core/static/core/js/charts/basic.js). */

const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);
const share = (values: number[], i: number) => (sum(values) ? ` (${Math.round((values[i]! / sum(values)) * 100)}%)` : "");

/* The change from `before` to `now` in hours, arrowed like the summary. */
export function changeLabel(now: number, before: number): string {
  const change = now - before;
  return Math.abs(change) < 0.05 ? "no change" : `${change > 0 ? "▲" : "▼"} ${fmtHours(Math.abs(change))}`;
}

/* A doughnut of hours. With a previous period it nests a second ring inside,
   same colour per slice but faded, and the legend and tooltips give both
   values and the change. */
function doughnut(names: string[], values: number[], colors: string[], previous?: number[]): AnyConfig {
  const datasets = [{ label: "This period", data: values, backgroundColor: colors }];
  if (!previous) {
    return {
      type: "doughnut",
      data: { labels: names, datasets },
      options: { plugins: { tooltip: { callbacks: { label: ({ dataIndex: i }: TT) => `${names[i]}: ${fmtHours(values[i]!)}${share(values, i)}` } } } },
    };
  }
  datasets.push({ label: "Previous period", data: previous, backgroundColor: colors.map((color) => withAlpha(color, 0.4)) });
  return {
    type: "doughnut",
    data: { labels: names.map((name, i) => `${name} · ${changeLabel(values[i]!, previous[i]!)}`), datasets },
    options: {
      cutout: "38%",
      plugins: {
        tooltip: {
          displayColors: false,
          callbacks: {
            title: (items: TT[]) => names[items[0]?.dataIndex ?? 0] ?? "",
            label: ({ dataIndex: i }: TT) => [
              `This period: ${fmtHours(values[i]!)}${share(values, i)}`,
              `Previous: ${fmtHours(previous[i]!)}${share(previous, i)}`,
              `Change: ${changeLabel(values[i]!, previous[i]!)}`,
            ],
          },
        },
      },
    },
  };
}

export function pieConfig(data: TallyRow[], { projectLimit, previous }: ChartOptions): AnyConfig {
  const rows: { name: string; total_time: number; _isOther?: true }[] = consolidateTopN(data, projectLimit);
  const before = previous ? previousTallies(rows, previous as TallyRow[]) : undefined;
  /* Time the previous period spent on projects absent now gets its own
     slice, so the inner ring's shares are of its whole total. */
  const missing = before ? sum((previous as TallyRow[]).map((row) => row.total_time / 60)) - sum(before) : 0;
  if (before && missing > 0.01) {
    rows.push({ name: "Only in the previous period", total_time: 0, _isOther: true });
    before.push(missing);
  }
  return doughnut(
    rows.map((row) => row.name),
    rows.map((row) => row.total_time / 60),
    rows.map(rowColor),
    before,
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

const SCATTER_TIME = "EEE d MMM, HH:mm";

/* Sessions as dots over the range. A previous period's sessions are laid
   over the same days as hollow rings in quiet ink, drawn first so this
   period's dots stay on top; their tooltips keep their own dates. */
function scatterConfig(rows: ScatterRow[], topN: number | undefined, { range, previous }: ChartOptions): AnyConfig {
  const axis = timeAxis(rows.map((row) => new Date(row.x)), range);
  const datasets: object[] = groupScatter(rows, topN).map((group, i) => ({
    label: group.name,
    data: group.points,
    backgroundColor: withAlpha(group.other ? otherColor() : paletteColor(i), 0.85),
    pointRadius: 4,
    pointHoverRadius: 6,
  }));
  if (previous && range) {
    const shift = periodDays(range);
    datasets.unshift({
      label: "Previous period",
      data: (previous as ScatterRow[]).map((row) => ({ x: addDays(new Date(row.x), shift), y: Number(row.y), at: new Date(row.x), projectName: row.series })),
      backgroundColor: "transparent",
      borderColor: withAlpha(token("--ink-2"), 0.6),
      borderWidth: 1.5,
      pointRadius: 4.5,
      pointHoverRadius: 6,
    });
  }
  return {
    type: "scatter",
    data: { datasets },
    options: {
      scales: { x: { ...axis.scale, time: { ...axis.scale.time, tooltipFormat: SCATTER_TIME } }, y: HOURS_AXIS },
      plugins: {
        tooltip: {
          callbacks: {
            /* undefined falls back to the axis's date, which for a previous
               session would be the day it was laid over. */
            title: (items: TT[]) => {
              const at = (items[0]?.raw as { at?: Date } | undefined)?.at;
              return at ? format(at, SCATTER_TIME) : undefined;
            },
            label: (context: TT) => {
              const point = context.raw as { at?: Date; projectName: string };
              return `${point.at ? `Previous period, ${point.projectName}` : (context.dataset.label ?? "")}: ${fmtHours(context.parsed.y!)}`;
            },
          },
        },
      },
    },
  };
}

export const scatterProjectsConfig = (data: ScatterRow[], options: ChartOptions) => scatterConfig(data, options.projectLimit, options);
export const scatterSubprojectsConfig = (data: ScatterRow[], options: ChartOptions) => scatterConfig(data, undefined, options);

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

export function statusConfig(data: StatusRow[], { previous }: ChartOptions): AnyConfig {
  const before = previous as StatusRow[] | undefined;
  const hours = (rows: StatusRow[], status: string) => (rows.find((row) => row.status === status)?.total_time ?? 0) / 60;
  const statuses = STATUS_ORDER.filter((status) => [...data, ...(before ?? [])].some((row) => row.status === status));
  return doughnut(
    statuses.map((status) => `${status} (${data.find((row) => row.status === status)?.count ?? 0})`),
    statuses.map((status) => hours(data, status)),
    statuses.map((status) => token(STATUS_TOKENS[status])),
    before && statuses.map((status) => hours(before, status)),
  );
}
