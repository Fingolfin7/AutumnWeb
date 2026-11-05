import { formatDuration } from "@/lib/format";
import { buildSeries, OTHER_COLOR, seriesColors, dayLabel, hourLabel, observedDates, periodDates, withAlpha, EMBER_RAMP, type ChartOptions, type DailySeriesRow } from "./data";
import type { AnyConfig, TT, DailyTotalRow } from "./payloads";
export function dailyBarsConfig(rows: DailySeriesRow[], options: ChartOptions, subprojects: boolean): AnyConfig {
  const set = buildSeries(rows, subprojects ? undefined : options.projectLimit);
  const days = periodDates(set.days, options);
  const colors = seriesColors(set.names);
  const oldByDay = new Map((options.previous ?? []).map(row => [row.date, Number(row.hours)]));
  const previousStart = new Date(`${days[0]}T12:00Z`); previousStart.setUTCDate(previousStart.getUTCDate() - days.length);
  const oldDays = days.map((_,index) => { const day = new Date(previousStart); day.setUTCDate(day.getUTCDate()+index); return day.toISOString().slice(0,10); });
  return { type: "bar", data: { labels: days, datasets: [...(options.previous ? [{ label: "Previous period", data: days.map((_,index) => oldByDay.get(oldDays[index]!) ?? 0), backgroundColor: withAlpha(OTHER_COLOR,.15), borderColor: withAlpha(OTHER_COLOR,.5), borderWidth: 1, borderRadius: 3, stack: "previous", maxBarThickness: 28 }] : []), ...set.names.map(name => ({ label: name, data: days.map(day => set.byDay[name]![day] ?? 0), backgroundColor: name === set.other ? OTHER_COLOR : colors.get(name), borderRadius: 3, borderSkipped: false, stack: "selected", maxBarThickness: 28 }))] }, options: { scales: { x: { stacked: true, grid: { display: false }, ticks: { maxRotation: 0, callback: (value: string | number) => dayLabel(days[Number(value)]!) } }, y: { stacked: true, beginAtZero: true, ticks: { callback: hourLabel } } }, plugins: { title: { text: subprojects ? "Daily time by subproject" : "Daily time by project" }, tooltip: { mode: "index", callbacks: { title: (items: TT[]) => items[0]?.label ? dayLabel(items[0].label) : "", label: (c: TT) => `${c.dataset.label}: ${formatDuration(c.parsed.y! * 60)}` } } }, interaction: { mode: "index", intersect: false } } };
}
export function cumulativeConfig(rows: DailyTotalRow[], options: ChartOptions): AnyConfig {
  const selectedDays = periodDates(rows.map(row => row.date), options);
  const days = observedDates(rows.map(row => row.date), options);
  const daily = new Map(rows.map(row => [row.date, Number(row.hours)])); let running = 0; let old = 0;
  const previous = [...(options.previous ?? [])].sort((a,b) => a.date.localeCompare(b.date));
  const priorMap = new Map(previous.map(row => [row.date, Number(row.hours)]));
  const priorDays = options.start && options.end ? periodDates([], { start: new Date(new Date(options.start + "T12:00Z").getTime() - selectedDays.length * 86400000).toISOString().slice(0,10), end: new Date(new Date(options.start + "T12:00Z").getTime() - 86400000).toISOString().slice(0,10) }) : previous.map(row => row.date);
  return { type: "line", data: { labels: days, datasets: [{ label: "Selected period", data: days.map(day => running += daily.get(day) ?? 0), borderColor: EMBER_RAMP[4], backgroundColor: withAlpha(EMBER_RAMP[3]!, .16), fill: true, tension: 0, pointRadius: 2 }, ...(options.previous ? [{ label: "Previous period", data: days.map((_, i) => old += priorMap.get(priorDays[i] ?? "") ?? 0), borderColor: OTHER_COLOR, backgroundColor: OTHER_COLOR, borderDash: [5,5], fill: false, tension: 0, pointRadius: 0 }] : [])] }, options: { scales: { x: { ticks: { callback: (value: string | number) => dayLabel(days[Number(value)]!) } }, y: { min: 0, ticks: { callback: hourLabel } } }, plugins: { tooltip: { callbacks: { label: (c: TT) => `${c.dataset.label}: ${formatDuration(c.parsed.y! * 60)}` } } } } };
}
