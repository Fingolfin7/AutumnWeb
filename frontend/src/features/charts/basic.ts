import { formatDuration } from "@/lib/format";
import { buildSeries, consolidateTopN, OTHER_COLOR, seriesColor, periodDates, type ChartOptions, type DailySeriesRow } from "./data";
import type { AnyConfig, TT, TallyRow } from "./payloads";

export function pieConfig(data: TallyRow[], { projectLimit }: ChartOptions): AnyConfig {
  const rows = consolidateTopN(data, projectLimit);
  return { type: "doughnut", data: { labels: rows.map(row => row.name), datasets: [{ data: rows.map(row => row.total_time / 60), backgroundColor: rows.map(row => "_isOther" in row ? OTHER_COLOR : seriesColor(row.name)), borderWidth: 3, borderColor: "#191b1d", hoverOffset: 5 }] }, options: { cutout: "76%", plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c: TT) => `${c.label}: ${formatDuration(Number(c.parsed) * 60)}` } } } } };
}
export function barConfig(data: TallyRow[], { projectLimit }: ChartOptions): AnyConfig {
  const rows = consolidateTopN(data, projectLimit);
  return { type: "bar", data: { labels: rows.map(row => row.name), datasets: [{ label: "Tracked time", data: rows.map(row => row.total_time / 60), backgroundColor: rows.map(row => "_isOther" in row ? OTHER_COLOR : seriesColor(row.name)), borderRadius: 4 }] }, options: { indexAxis: "y", scales: { x: { beginAtZero: true, title: { display: true, text: "Hours" } } }, plugins: { tooltip: { callbacks: { label: (c: TT) => formatDuration(c.parsed.x! * 60) } } } } };
}
function lineConfig(rows: DailySeriesRow[], options: ChartOptions, topN?: number): AnyConfig {
  const set = buildSeries(rows, topN); const days = periodDates(set.days, options);
  return { type: "line", data: { labels: days, datasets: set.names.map(name => ({ label: name, data: days.map(day => set.byDay[name]![day] ?? 0), borderColor: name === set.other ? OTHER_COLOR : seriesColor(name), backgroundColor: name === set.other ? OTHER_COLOR : seriesColor(name), tension: 0, fill: false, pointRadius: days.length > 31 ? 0 : 3 })) }, options: { scales: { x: { type: "category", ticks: { callback: function(value: string | number) { return days[Number(value)]?.slice(5); } } }, y: { beginAtZero: true, min: 0, title: { display: true, text: "Hours" } } }, plugins: { tooltip: { callbacks: { label: (c: TT) => `${c.dataset.label}: ${formatDuration(c.parsed.y! * 60)}` } } } } };
}
export const lineProjectsConfig = (rows: DailySeriesRow[], options: ChartOptions) => lineConfig(rows, options, options.projectLimit);
export const lineSubprojectsConfig = (rows: DailySeriesRow[], options: ChartOptions) => lineConfig(rows, options);
export const contextConfig = (rows: TallyRow[]) => barConfig([...rows].sort((a,b) => b.total_time-a.total_time), { projectLimit: rows.length });
