import type { Chart } from "chart.js";
import { differenceInCalendarWeeks, startOfWeek, subDays } from "date-fns";
import { dayKey, dateExtent, fillDates, fmtHours, parseDay, withAlpha, type ChartOptions } from "./data";
import { token } from "./theme";
import type { AnyConfig, DailyTotalRow, HeatmapRow } from "./payloads";

/* Calendar and weekday x hour heatmap: matrix charts
   (core/static/core/js/charts/time.js). Both run Monday to Sunday and
   share one ramp: more time, more of the app's duration green. A shared
   `extent` tops the ramp, so two periods' panels colour alike. */

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const mondayFirst = (sundayFirst: number) => (sundayFirst + 6) % 7;

function ramp(max: number) {
  const green = token("--duration");
  const empty = token("--raised-2");
  return (value: number) => (value > 0 && max > 0 ? withAlpha(green, 0.2 + 0.8 * (value / max)) : empty);
}

/* A cell's side: its share of the plot along `axis`, less a gap. */
function slot(chart: Chart, axis: "x" | "y", count: number): number {
  const area = chart.chartArea;
  const full = area ? (axis === "x" ? area.right - area.left : area.bottom - area.top) : axis === "x" ? chart.width : chart.height;
  return Math.max(2, full / count - 3);
}

const CELL = { borderRadius: 3, borderWidth: 0, hoverBorderWidth: 1.5 };

/* One cell per day of the selected range (at most its last year), in week
   columns. The canvas keeps the grid's own proportions, so the squares fill
   the width instead of floating in a fixed-height box. */
export function calendarConfig(data: DailyTotalRow[], { range, extent: shared }: ChartOptions): AnyConfig {
  const totals = new Map<string, number>();
  for (const row of data) totals.set(row.date, (totals.get(row.date) ?? 0) + Number(row.hours));
  const extent = range ? { min: parseDay(range.start), max: parseDay(range.end) } : dateExtent([...totals.keys()].map(parseDay));
  const first = new Date(Math.max(extent.min.getTime(), subDays(extent.max, 370).getTime()));
  const weekOf = (date: Date) => startOfWeek(date, { weekStartsOn: 1 });
  const cells = fillDates(first, extent.max).map((date) => {
    const key = dayKey(date);
    return { x: weekOf(date).getTime(), y: mondayFirst(date.getDay()), d: key, v: totals.get(key) ?? 0 };
  });
  const color = ramp(shared?.[1] ?? Math.max(...cells.map((cell) => cell.v)));
  const weeks = differenceInCalendarWeeks(extent.max, first, { weekStartsOn: 1 }) + 1;
  const side = ({ chart }: { chart: Chart }) => Math.min(slot(chart, "x", weeks), slot(chart, "y", 7));

  return {
    type: "matrix",
    data: {
      datasets: [
        {
          data: cells,
          width: side,
          height: side,
          backgroundColor: (context: { raw?: { v: number } }) => color(context.raw?.v ?? 0),
          hoverBorderColor: token("--ink"),
          ...CELL,
        },
      ],
    },
    options: {
      maintainAspectRatio: true,
      aspectRatio: Math.min(7, Math.max(1.4, (weeks / 7) * 1.15)),
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items: { raw: { d: string } }[]) => (items[0] ? parseDay(items[0].raw.d).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" }) : ""),
            label: (context: { raw: { v: number } }) => fmtHours(context.raw.v),
          },
        },
      },
      scales: {
        x: {
          type: "time",
          offset: true,
          min: weekOf(first).getTime(),
          max: weekOf(extent.max).getTime(),
          time: { unit: weeks > 10 ? "month" : "week", isoWeekday: true },
          ticks: { maxRotation: 0, autoSkipPadding: 12 },
          grid: { display: false },
        },
        y: {
          type: "linear",
          offset: true,
          min: 0,
          max: 6,
          reverse: true,
          ticks: { stepSize: 1, callback: (value: number | string) => WEEKDAYS[Number(value)] },
          grid: { display: false },
        },
      },
    },
  };
}

export function heatmapConfig(data: HeatmapRow[], { extent }: Pick<ChartOptions, "extent"> = {}): AnyConfig {
  const averages = new Map(data.map((row) => [`${mondayFirst(row.weekday)}:${row.hour}`, Number(row.average_hours)] as const));
  const cells: { x: number; y: number; v: number }[] = [];
  for (let weekday = 0; weekday < 7; weekday++) {
    for (let hour = 0; hour < 24; hour++) cells.push({ x: weekday, y: hour, v: averages.get(`${weekday}:${hour}`) ?? 0 });
  }
  const color = ramp(extent?.[1] ?? Math.max(...cells.map((cell) => cell.v)));

  return {
    type: "matrix",
    data: {
      datasets: [
        {
          data: cells,
          width: ({ chart }: { chart: Chart }) => slot(chart, "x", 7),
          height: ({ chart }: { chart: Chart }) => slot(chart, "y", 24),
          backgroundColor: (context: { raw?: { v: number } }) => color(context.raw?.v ?? 0),
          hoverBorderColor: token("--ink"),
          ...CELL,
        },
      ],
    },
    options: {
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: () => "",
            label: (context: { raw: { x: number; y: number; v: number } }) => {
              const { x, y, v } = context.raw;
              return `${WEEKDAYS[x]} ${y}:00 · ${fmtHours(v || 0)} avg`;
            },
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          offset: true,
          min: 0,
          max: 6,
          position: "top",
          ticks: { stepSize: 1, callback: (value: number | string) => WEEKDAYS[Number(value)] },
          grid: { display: false },
        },
        y: {
          type: "linear",
          offset: true,
          min: 0,
          max: 23,
          reverse: true,
          ticks: { stepSize: 3, callback: (value: number | string) => `${String(value).padStart(2, "0")}:00` },
          grid: { display: false },
        },
      },
    },
  };
}
