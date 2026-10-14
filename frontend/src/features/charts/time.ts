import type { Chart } from "chart.js";
import { dayKey, dateExtent, fillDates, getChartUnit, parseDay } from "./data";
import type { AnyConfig, DailyTotalRow, HeatmapRow } from "./payloads";

/* Calendar and weekday x hour heatmap: matrix charts
   (core/static/core/js/charts/time.js). */

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/* The cell fits its grid slot but never grows past 20px (the plugin's own
   default), so a phone-width calendar stays legible instead of overlapping. */
function slot(chart: Chart, axis: "x" | "y", count: number): number {
  const area = chart.chartArea;
  const full = area ? (axis === "x" ? area.right - area.left : area.bottom - area.top) : axis === "x" ? chart.width : chart.height;
  return Math.max(2, Math.min(20, full / count - 1));
}

export function calendarConfig(data: DailyTotalRow[]): AnyConfig {
  const totals = new Map(data.map((row) => [row.date, Number(row.hours)] as const));
  /* One calendar year: the year of the earliest day in the range. */
  const first = [...totals.keys()].sort()[0]!;
  const year = parseDay(first).getFullYear();
  const days = fillDates(new Date(year, 0, 1), new Date(year + 1, 0, 1));
  const cells = days.map((date) => {
    const key = dayKey(date);
    return { x: date, y: date.getDay(), d: key, v: totals.get(key) ?? 0 };
  });
  const maxHours = Math.max(...cells.map((cell) => cell.v));
  const { min, max } = dateExtent(days);
  const narrow = typeof window !== "undefined" && window.innerWidth < 640;

  return {
    type: "matrix",
    data: {
      datasets: [
        {
          data: cells,
          width: ({ chart }: { chart: Chart }) => slot(chart, "x", 53),
          height: ({ chart }: { chart: Chart }) => slot(chart, "y", 7),
          backgroundColor(context: { raw: { v: number } }) {
            const alpha = maxHours ? context.raw.v / maxHours : 0;
            return alpha === 0 ? "rgba(82, 76, 66, 0.37)" : `rgba(0, 128, 0, ${alpha})`;
          },
          borderWidth: 1,
          hoverBackgroundColor: "yellow",
          hoverBorderColor: "yellowgreen",
        },
      ],
    },
    options: {
      aspectRatio: narrow ? 2.5 : 5,
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          displayColors: true,
          callbacks: {
            title: () => "",
            label(context: { raw: { d: string; v: number } }) {
              const cell = context.raw;
              return [
                parseDay(cell.d).toLocaleDateString("en-US", { weekday: "short", day: "numeric", month: "short", year: "numeric" }),
                `${cell.v.toFixed(2)} hours`,
              ];
            },
          },
        },
      },
      scales: {
        x: {
          type: "time",
          position: "bottom",
          offset: true,
          time: { unit: getChartUnit(max, min), round: "week" },
          ticks: { maxRotation: 0 },
          grid: { display: false },
        },
        y: {
          type: "linear",
          min: 0,
          max: 6,
          reverse: true,
          position: "left",
          ticks: { maxRotation: 0, callback: (value: number | string) => WEEKDAYS[Number(value)] },
          grid: { display: false },
        },
      },
    },
  };
}

export function heatmapConfig(data: HeatmapRow[]): AnyConfig {
  const averages = new Map(data.map((row) => [`${row.weekday}:${row.hour}`, Number(row.average_hours)] as const));
  let maxAverage = 0;
  const cells: { x: number; y: number; v: number }[] = [];
  for (let weekday = 0; weekday < 7; weekday++) {
    for (let hour = 0; hour < 24; hour++) {
      const v = averages.get(`${weekday}:${hour}`) ?? 0;
      if (v > maxAverage) maxAverage = v;
      cells.push({ x: weekday, y: hour, v });
    }
  }
  const fill = (chart: Chart, axis: "x" | "y", count: number) => {
    const area = chart.chartArea;
    const full = area ? (axis === "x" ? area.right - area.left : area.bottom - area.top) : axis === "x" ? chart.width : chart.height;
    return full / count - 1;
  };

  return {
    type: "matrix",
    data: {
      datasets: [
        {
          label: "Avg session length (hrs)",
          data: cells,
          width: ({ chart }: { chart: Chart }) => fill(chart, "x", 7),
          height: ({ chart }: { chart: Chart }) => fill(chart, "y", 24),
          backgroundColor(context: { raw: { v: number } }) {
            return `rgba(0, 128, 0, ${maxAverage ? context.raw.v / maxAverage : 0})`;
          },
          borderWidth: 0,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        title: { display: true, text: "Weekly Hourly Heatmap" },
        tooltip: {
          callbacks: {
            title: () => "",
            label: (context: { raw: { x: number; y: number; v: number } }) => {
              const { x, y, v } = context.raw;
              return `${WEEKDAYS[x]} ${y}:00 → ${(v || 0).toFixed(2)} h avg`;
            },
          },
        },
        legend: { display: false },
      },
      scales: {
        x: {
          type: "linear",
          min: 0,
          max: 6,
          ticks: { stepSize: 1, callback: (value: number | string) => WEEKDAYS[Number(value)] },
          title: { display: true, text: "Weekday" },
          grid: { display: false },
        },
        y: {
          type: "linear",
          min: 0,
          max: 23,
          reverse: true,
          ticks: { stepSize: 1, callback: (value: number | string) => `${value}:00` },
          title: { display: true, text: "Time of Day" },
          grid: { display: false },
        },
      },
    },
  };
}
