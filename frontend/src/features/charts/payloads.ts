import type { ChartConfiguration, TooltipItem } from "chart.js";

/* Row shapes of GET /api/v2/reports/charts/. The schema types every row as a
   generic ChartPayloadRow, and the legacy chart kinds (pie, bar, context,
   status, bubble, treemap, radar) are not in its chart_type enum, so the
   shapes the server really sends are spelled out here
   (core/api_v2/reports.py, core/chart_reports.py). */

export interface TallyRow {
  name: string;
  /** Minutes. */
  total_time: number;
}
export interface StatusRow {
  status: string;
  count: number;
  total_time: number;
}
export interface BubbleRow {
  name: string;
  tag_id: number;
  total_time: number;
  project_count: number;
  color: string | null;
}
export interface ScatterRow {
  /** End-of-session instant, ISO 8601. */
  x: string;
  /** Hours. */
  y: number;
  series: string;
}
export interface DailyTotalRow {
  date: string;
  hours: number | string;
}
export interface HeatmapRow {
  weekday: number;
  hour: number;
  average_hours: number | string;
}
export interface HistogramRow {
  label: string;
  count: number | string;
}
export interface WordRow {
  text: string;
  weight: number | string;
}
export interface RadarRow {
  name: string;
  total_time: number;
  session_count: number;
  subproject_count: number;
  days_since_update?: number;
}
export interface HierarchyNode {
  name: string;
  total_time?: number;
  children?: HierarchyNode[];
}

/* Chart.js configurations are built for several controller types (some from
   plugins), so a builder's result is deliberately loosely typed. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AnyConfig = ChartConfiguration<any, any, any>;

export type ChartKind =
  | "pie"
  | "bar"
  | "scatter"
  | "line"
  | "calendar"
  | "heatmap"
  | "stacked_area"
  | "cumulative"
  | "treemap"
  | "status"
  | "context"
  | "histogram"
  | "radar"
  | "bubble"
  | "wordcloud";

/* A tooltip callback's argument. Configs are loosely typed (see AnyConfig), so
   there is no contextual type to infer it from; `parsed` is whatever the
   controller produced. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type TT = TooltipItem<any>;
