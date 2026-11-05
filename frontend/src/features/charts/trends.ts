import { formatDuration } from "@/lib/format";
import { buildSeries, OTHER_COLOR, seriesColor, periodDates, withAlpha, EMBER_RAMP, type ChartOptions, type DailySeriesRow } from "./data";
import type { AnyConfig, TT, DailyTotalRow } from "./payloads";
function stackedAreaConfig(rows: DailySeriesRow[], options: ChartOptions, topN?: number): AnyConfig {
  const set = buildSeries(rows, topN); const days = periodDates(set.days, options);
  return { type: "line", data: { labels: days, datasets: set.names.map(name => { const color = name === set.other ? OTHER_COLOR : seriesColor(name); return { label: name, data: days.map(day => set.byDay[name]![day] ?? 0), borderColor: color, backgroundColor: withAlpha(color, .65), fill: true, tension: 0, pointRadius: 0 }; }) }, options: { scales: { x: { ticks: { callback: (value: string | number) => days[Number(value)]?.slice(5) } }, y: { stacked: true, beginAtZero: true, min: 0, title: { display: true, text: "Hours" } } }, plugins: { title: { text: topN === undefined ? "Daily Time by Subproject (Stacked)" : "Daily Time by Project (Stacked)" }, tooltip: { mode: "index", callbacks: { label: (c: TT) => `${c.dataset.label}: ${formatDuration(c.parsed.y! * 60)}` } } }, interaction: { mode: "index", intersect: false } } };
}
export const stackedAreaProjectsConfig = (rows: DailySeriesRow[], options: ChartOptions) => stackedAreaConfig(rows, options, options.projectLimit);
export const stackedAreaSubprojectsConfig = (rows: DailySeriesRow[], options: ChartOptions) => stackedAreaConfig(rows, options);
export function cumulativeConfig(rows: DailyTotalRow[], options: ChartOptions): AnyConfig {
  const days = periodDates(rows.map(row => row.date), options);
  const daily = new Map(rows.map(row => [row.date, Number(row.hours)])); let running = 0; let old = 0;
  const previous = [...(options.previous ?? [])].sort((a,b) => a.date.localeCompare(b.date));
  const priorMap = new Map(previous.map(row => [row.date, Number(row.hours)]));
  const priorDays = options.start && options.end ? periodDates([], { start: new Date(new Date(options.start + "T12:00Z").getTime() - days.length * 86400000).toISOString().slice(0,10), end: new Date(new Date(options.start + "T12:00Z").getTime() - 86400000).toISOString().slice(0,10) }) : previous.map(row => row.date);
  return { type: "line", data: { labels: days, datasets: [{ label: "Selected period", data: days.map(day => running += daily.get(day) ?? 0), borderColor: EMBER_RAMP[4], backgroundColor: withAlpha(EMBER_RAMP[3]!, .16), fill: true, tension: 0, pointRadius: 2 }, ...(options.previous ? [{ label: "Previous period", data: days.map((_, i) => old += priorMap.get(priorDays[i] ?? "") ?? 0), borderColor: OTHER_COLOR, backgroundColor: OTHER_COLOR, borderDash: [5,5], fill: false, tension: 0, pointRadius: 0 }] : [])] }, options: { scales: { x: { ticks: { callback: (value: string | number) => days[Number(value)]?.slice(5) } }, y: { min: 0, title: { display: true, text: "Hours" } } }, plugins: { tooltip: { callbacks: { label: (c: TT) => `${c.dataset.label}: ${formatDuration(c.parsed.y! * 60)}` } } } } };
}
