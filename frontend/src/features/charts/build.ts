import { barConfig, contextConfig, lineProjectsConfig, lineSubprojectsConfig, pieConfig, scatterProjectsConfig, scatterSubprojectsConfig, statusConfig } from "./basic";
import { calendarConfig, heatmapConfig } from "./time";
import { cumulativeConfig, stackedAreaProjectsConfig, stackedAreaSubprojectsConfig } from "./trends";
import { treemapConfig } from "./hierarchy";
import { bubbleConfig, histogramConfig, radarConfig } from "./analysis";
import type { ChartOptions } from "./data";
import type { AnyConfig, BubbleRow, ChartKind, DailyTotalRow, HeatmapRow, HierarchyNode, HistogramRow, RadarRow, ScatterRow, StatusRow, TallyRow, WordRow } from "./payloads";
import type { DailySeriesRow } from "./data";

/* The chart picker's groups, in the old page's order. */
export const CHART_GROUPS: { label: string; kinds: { value: ChartKind; label: string }[] }[] = [
  { label: "Basic", kinds: [{ value: "pie", label: "Pie" }, { value: "bar", label: "Bar" }, { value: "scatter", label: "Scatter" }, { value: "line", label: "Line" }] },
  { label: "Time", kinds: [{ value: "calendar", label: "Calendar" }, { value: "heatmap", label: "Heatmap" }] },
  { label: "Trends", kinds: [{ value: "stacked_area", label: "Stacked Area" }, { value: "cumulative", label: "Cumulative" }] },
  { label: "Hierarchy", kinds: [{ value: "treemap", label: "Treemap" }] },
  { label: "Summary", kinds: [{ value: "status", label: "Status" }, { value: "context", label: "Context" }] },
  { label: "Analysis", kinds: [{ value: "histogram", label: "Session Histogram" }, { value: "radar", label: "Radar" }, { value: "bubble", label: "Tag Bubble" }] },
  { label: "Other", kinds: [{ value: "wordcloud", label: "Wordcloud" }] },
];

export const CHART_KINDS: ChartKind[] = CHART_GROUPS.flatMap((group) => group.kinds.map((kind) => kind.value));
export const DEFAULT_KIND: ChartKind = "pie";

export function parseKind(value: string | null | undefined): ChartKind {
  return CHART_KINDS.includes(value as ChartKind) ? (value as ChartKind) : DEFAULT_KIND;
}

/* Square charts get a square box; everything else the full-width one. */
export const CIRCULAR_KINDS: ChartKind[] = ["pie", "status", "radar"];

export type Built = { type: "chart"; config: AnyConfig } | { type: "wordcloud"; words: WordRow[]; extent?: [number, number] };

/* True when there is nothing worth drawing for this payload. */
export function isEmptyPayload(kind: ChartKind, data: unknown): boolean {
  if (!data) return true;
  if (Array.isArray(data) && !data.length) return true;
  if (kind === "histogram" && Array.isArray(data)) return (data as HistogramRow[]).every((row) => !Number(row.count));
  return false;
}

/* How each kind shows the previous period when comparing, and the key the
   summary gives for reading it. "series" draws it inside the same chart
   (a ring, a faded bar, a dashed line); "panels" draws a second chart beside
   this one, on one shared scale. The other kinds have no honest comparison,
   so the toggle is off for them, with the reason as its hint. */
export const COMPARE: Partial<Record<ChartKind, { draw: "series" | "panels"; key: string }>> = {
  pie: { draw: "series", key: "outer ring this period, inner ring the previous" },
  status: { draw: "series", key: "outer ring this period, inner ring the previous" },
  bar: { draw: "series", key: "solid bars this period, faded bars the previous" },
  context: { draw: "series", key: "solid bars this period, faded bars the previous" },
  histogram: { draw: "series", key: "solid bars this period, faded bars the previous" },
  stacked_area: { draw: "series", key: "the dashed line is the previous period's total, laid over the same weeks" },
  cumulative: { draw: "series", key: "the dashed line is the previous period's running total" },
  scatter: { draw: "series", key: "grey rings are the previous period's sessions, laid over the same days" },
  calendar: { draw: "panels", key: "both calendars share one colour scale" },
  heatmap: { draw: "panels", key: "both heatmaps share one colour scale" },
  wordcloud: { draw: "panels", key: "a word the same size is as frequent in both" },
};

export const NO_COMPARE: Partial<Record<ChartKind, string>> = {
  line: "A previous line for every project would double a busy chart; Stacked Area and Cumulative compare the total over time.",
  treemap: "Tile areas cannot be laid against another treemap's; Pie and Bar compare where the time went.",
  radar: "Subprojects and recency are counted to today, not per period, so a previous outline would mislead.",
  bubble: "A tag moves on both axes, and its old bubble cannot be matched to it at a glance; Bar and Pie compare the time.",
};

/* The smallest and largest value a panel kind colours or sizes by, so both
   periods' panels can share one scale. */
export function valueExtent(kind: ChartKind, data: unknown): [number, number] {
  const values = !Array.isArray(data)
    ? []
    : kind === "calendar"
      ? (data as DailyTotalRow[]).map((row) => Number(row.hours))
      : kind === "heatmap"
        ? (data as HeatmapRow[]).map((row) => Number(row.average_hours))
        : (data as WordRow[]).map((row) => Number(row.weight));
  return values.length ? [Math.min(...values), Math.max(...values)] : [0, 0];
}

/* Turn a payload into something drawable, or null when it has no data.
   `subprojects` (an explicit project-name filter) swaps scatter, line and
   stacked area for their subproject breakdowns. */
export function buildChart(kind: ChartKind, data: unknown, options: ChartOptions & { subprojects: boolean }): Built | null {
  if (isEmptyPayload(kind, data)) return null;
  const chart = (config: AnyConfig | null): Built | null => (config ? { type: "chart", config } : null);
  const sub = options.subprojects;
  switch (kind) {
    case "pie":
      return chart(pieConfig(data as TallyRow[], options));
    case "bar":
      return chart(barConfig(data as TallyRow[], options));
    case "scatter":
      return chart((sub ? scatterSubprojectsConfig : scatterProjectsConfig)(data as ScatterRow[], options));
    case "line":
      return chart((sub ? lineSubprojectsConfig : lineProjectsConfig)(data as DailySeriesRow[], options));
    case "calendar":
      return chart(calendarConfig(data as DailyTotalRow[], options));
    case "heatmap":
      return chart(heatmapConfig(data as HeatmapRow[], options));
    case "stacked_area":
      return chart((sub ? stackedAreaSubprojectsConfig : stackedAreaProjectsConfig)(data as DailySeriesRow[], options));
    case "cumulative":
      return chart(cumulativeConfig(data as DailyTotalRow[], options));
    case "treemap":
      return chart(treemapConfig(data as HierarchyNode | TallyRow[]));
    case "status":
      return chart(statusConfig(data as StatusRow[], options));
    case "context":
      return chart(contextConfig(data as TallyRow[], options));
    case "histogram":
      return chart(histogramConfig(data as HistogramRow[], options));
    case "radar":
      return chart(radarConfig(data as RadarRow[]));
    case "bubble":
      return chart(bubbleConfig(data as BubbleRow[]));
    case "wordcloud":
      return { type: "wordcloud", words: data as WordRow[], extent: options.extent };
  }
}
