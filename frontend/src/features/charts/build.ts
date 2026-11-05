import { barConfig, contextConfig, pieConfig } from "./basic";
import { heatmapConfig } from "./time";
import { cumulativeConfig, dailyBarsConfig } from "./trends";
import { treemapConfig } from "./hierarchy";
import { histogramConfig } from "./analysis";
import type { ChartOptions } from "./data";
import type { AnyConfig, ChartKind, DailyTotalRow, HeatmapRow, HierarchyNode, HistogramRow, TallyRow, WordRow } from "./payloads";
import type { DailySeriesRow } from "./data";

/* Questions first; legacy reports stay available through the API. */
export const CHART_GROUPS: { label: string; kinds: { value: ChartKind; label: string }[] }[] = [
  { label: "Where", kinds: [{ value: "bar", label: "Ranked bars" }, { value: "pie", label: "Donut" }, { value: "treemap", label: "Treemap" }, { value: "context", label: "Contexts" }] },
  { label: "Over time", kinds: [{ value: "daily_bars", label: "Daily bars" }, { value: "cumulative", label: "Cumulative" }] },
  { label: "Patterns", kinds: [{ value: "histogram", label: "Session lengths" }, { value: "heatmap", label: "Work hours" }, { value: "wordcloud", label: "Words in your notes" }] },
];
export const CHART_QUESTIONS: Partial<Record<ChartKind, string>> = {
  bar: "Where did the time go?", pie: "How did you divide your time?", daily_bars: "How is it changing?", cumulative: "How does your time add up?", treemap: "What makes up your time?",
  context: "Which parts of life got your time?", histogram: "How long are your sessions?", heatmap: "When do you work?", wordcloud: "What is in your notes?",
};

export const CHART_KINDS: ChartKind[] = CHART_GROUPS.flatMap((group) => group.kinds.map((kind) => kind.value));
export const DEFAULT_KIND: ChartKind = "bar";

export function parseKind(value: string | null | undefined): ChartKind {
  return CHART_KINDS.includes(value as ChartKind) ? (value as ChartKind) : DEFAULT_KIND;
}

/* Square charts get a square box; everything else the full-width one. */
export const CIRCULAR_KINDS: ChartKind[] = ["pie"];

export type Built = { type: "chart"; config: AnyConfig } | { type: "wordcloud"; words: WordRow[] };

/* True when there is nothing worth drawing for this payload. */
export function isEmptyPayload(kind: ChartKind, data: unknown): boolean {
  if (!data) return true;
  if (Array.isArray(data) && !data.length) return true;
  if (kind === "histogram" && Array.isArray(data)) return (data as HistogramRow[]).every((row) => !Number(row.count));
  return false;
}

/* Turn a payload into something drawable, or null when it has no data.
   `subprojects` (an explicit project-name filter) swaps line and
   stacked area for their subproject breakdowns. */
export function buildChart(kind: ChartKind, data: unknown, options: ChartOptions & { subprojects: boolean }): Built | null {
  if (isEmptyPayload(kind, data)) return null;
  const chart = (config: AnyConfig | null): Built | null => (config ? { type: "chart", config } : null);
  switch (kind) {
    case "pie":
      return chart(pieConfig(data as TallyRow[], options));
    case "bar":
      return chart(barConfig(data as TallyRow[], options));
    case "daily_bars":
      return chart(dailyBarsConfig(data as DailySeriesRow[], options, options.subprojects));
    case "heatmap":
      return chart(heatmapConfig(data as HeatmapRow[]));
    case "cumulative":
      return chart(cumulativeConfig(data as DailyTotalRow[], options));
    case "treemap":
      return chart(treemapConfig(data as HierarchyNode | TallyRow[]));
    case "context":
      return chart(contextConfig(data as TallyRow[]));
    case "histogram":
      return chart(histogramConfig(data as HistogramRow[]));
    case "wordcloud":
      return { type: "wordcloud", words: data as WordRow[] };
    default: return null;
  }
}
