import { formatDuration } from "@/lib/format";
import { consolidateTopN, OTHER_COLOR, seriesColors, hourLabel, type ChartOptions } from "./data";
import type { AnyConfig, TT, TallyRow } from "./payloads";

export function pieConfig(data: TallyRow[], { projectLimit }: ChartOptions): AnyConfig {
  const rows = consolidateTopN([...data].filter(row => row.total_time > 0).sort((a,b) => b.total_time-a.total_time), projectLimit);
  const colors = seriesColors(rows.map(row => row.name));
  return { type: "doughnut", data: { labels: rows.map(row => row.name), datasets: [{ data: rows.map(row => row.total_time / 60), backgroundColor: rows.map(row => "_isOther" in row ? OTHER_COLOR : colors.get(row.name)!), borderWidth: 3, borderColor: "#191b1d", hoverOffset: 5 }] }, options: { cutout: "76%", plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c: TT) => `${c.label}: ${formatDuration(Number(c.parsed) * 60)}` } } } } };
}
export function barConfig(data: TallyRow[], { projectLimit }: ChartOptions): AnyConfig {
  const rows = consolidateTopN([...data].filter(row => row.total_time > 0).sort((a,b) => b.total_time-a.total_time), projectLimit);
  return { type: "bar", data: { labels: rows.map(row => row.name), datasets: [{ label: "Tracked time", data: rows.map(row => row.total_time / 60), backgroundColor: "#e9a35b", borderRadius: 3, maxBarThickness: 28 }] }, options: { indexAxis: "y", scales: { x: { beginAtZero: true, ticks: { callback: hourLabel } } }, plugins: { tooltip: { callbacks: { label: (c: TT) => formatDuration(c.parsed.x! * 60) } } } } };
}
export const contextConfig = (rows: TallyRow[]) => barConfig([...rows].sort((a,b) => b.total_time-a.total_time), { projectLimit: rows.length });
