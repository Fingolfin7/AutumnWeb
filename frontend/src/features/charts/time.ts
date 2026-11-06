import { formatDuration } from "@/lib/format";
import type { Chart } from "chart.js";
import { emberColor } from "./data";
import type { AnyConfig, HeatmapRow } from "./payloads";
const HOURS = Array.from({ length:24 },(_,hour) => `${String(hour).padStart(2,"0")}:00`);
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export function heatmapConfig(data: HeatmapRow[]): AnyConfig {
  const averages = new Map(data.map((row) => [`${row.weekday}:${row.hour}`, Number(row.average_hours)] as const));
  const activeHours = data.filter(row => Number(row.average_hours) > 0).map(row => Number(row.hour));
  const firstHour = activeHours.length ? Math.max(0, Math.min(...activeHours) - 1) : 9;
  const lastHour = activeHours.length ? Math.min(23, Math.max(...activeHours) + 1) : 17;
  const hours = HOURS.slice(firstHour, lastHour + 1);
  let maxAverage = 0;
  const cells: { x: string; y: string; v: number }[] = [];
  for (let weekday = 0; weekday < 7; weekday++) {
    for (let hour = firstHour; hour <= lastHour; hour++) {
      const v = averages.get(`${(weekday + 1) % 7}:${hour}`) ?? 0;
      if (v > maxAverage) maxAverage = v;
      cells.push({ x: WEEKDAYS[weekday]!, y: HOURS[hour]!, v });
    }
  }
  const fill = (chart: Chart, axis: "x" | "y", count: number) => {
    const area = chart.chartArea;
    const full = area ? (axis === "x" ? area.right - area.left : area.bottom - area.top) : axis === "x" ? chart.width : chart.height;
    return Math.max(1, full / count - 3);
  };

  return {
    type: "matrix",
    data: {
      datasets: [
        {
          label: "Avg session length (hrs)",
          data: cells,
          width: ({ chart }: { chart: Chart }) => fill(chart, "x", 7),
          height: ({ chart }: { chart: Chart }) => fill(chart, "y", hours.length),
          backgroundColor(context: { raw: { v: number } }) {
            return context.raw.v ? emberColor(context.raw.v, maxAverage) : "#292725";
          },
          borderWidth: 0,
          borderRadius: 3,
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
            label: (context: { raw: { x: string; y: string; v: number } }) => {
              const { x, y, v } = context.raw;
              return `${x} ${y} → ${formatDuration((v || 0) * 60)} avg`;
            },
          },
        },
        legend: { display: false },
      },
      scales: {
        x: {
          type: "category", labels: WEEKDAYS, offset: true,
          ticks: { autoSkip: false, maxRotation: 0 },

          grid: { display: false },
        },
        y: {
          type: "category", labels: hours, offset: true, reverse: true,
          ticks: { autoSkip: true, maxTicksLimit: 8 },

          grid: { display: false },
        },
      },
    },
  };
}
