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

export type Built = { type: "chart"; config: AnyConfig } | { type: "wordcloud"; words: WordRow[] };

/* True when there is nothing worth drawing for this payload. */
export function isEmptyPayload(kind: ChartKind, data: unknown): boolean {
  if (!data) return true;
  if (Array.isArray(data) && !data.length) return true;
  if (kind === "histogram" && Array.isArray(data)) return (data as HistogramRow[]).every((row) => !Number(row.count));
  return false;
}

/* Turn a payload into something drawable, or null when it has no data.
   `subprojects` (an explicit project-name filter) swaps scatter, line and
   stacked area for their subproject breakdowns. */
export function buildChart(kind: ChartKind, data: unknown, options: ChartOptions & { subprojects: boolean }): Built | null {
  if (isEmptyPayload(kind, data)) return null;
  const chart = (config: AnyConfig | null): Built | null => (config ? { type: "chart", config } : null);
  switch (kind) {
    case "pie":
      return chart(pieConfig(data as TallyRow[], options));
    case "bar":
      return chart(barConfig(data as TallyRow[], options));
    case "scatter":
      return chart(options.subprojects ? scatterSubprojectsConfig(data as ScatterRow[]) : scatterProjectsConfig(data as ScatterRow[], options));
    case "line":
      return chart(options.subprojects ? lineSubprojectsConfig(data as DailySeriesRow[]) : lineProjectsConfig(data as DailySeriesRow[], options));
    case "calendar":
      return chart(calendarConfig(data as DailyTotalRow[]));
    case "heatmap":
      return chart(heatmapConfig(data as HeatmapRow[]));
    case "stacked_area":
      return chart(options.subprojects ? stackedAreaSubprojectsConfig(data as DailySeriesRow[]) : stackedAreaProjectsConfig(data as DailySeriesRow[], options));
    case "cumulative":
      return chart(cumulativeConfig(data as DailyTotalRow[]));
    case "treemap":
      return chart(treemapConfig(data as HierarchyNode | TallyRow[]));
    case "status":
      return chart(statusConfig(data as StatusRow[]));
    case "context":
      return chart(contextConfig(data as TallyRow[]));
    case "histogram":
      return chart(histogramConfig(data as HistogramRow[]));
    case "radar":
      return chart(radarConfig(data as RadarRow[]));
    case "bubble":
      return chart(bubbleConfig(data as BubbleRow[]));
    case "wordcloud":
      return { type: "wordcloud", words: data as WordRow[] };
  }
}
