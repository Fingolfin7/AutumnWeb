import { formatDuration } from "@/lib/format";
import type { Chart } from "chart.js";
import { emberColor } from "./data";
import type { AnyConfig, HeatmapRow } from "./payloads";
const HOURS = Array.from({ length:24 },(_,hour) => `${String(hour).padStart(2,"0")}:00`);
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
export function heatmapConfig(data: HeatmapRow[]): AnyConfig {
  const averages = new Map(data.map((row) => [`${row.weekday}:${row.hour}`, Number(row.average_hours)] as const));
  let maxAverage = 0;
  const cells: { x: string; y: string; v: number }[] = [];
  for (let weekday = 0; weekday < 7; weekday++) {
    for (let hour = 0; hour < 24; hour++) {
      const v = averages.get(`${weekday}:${hour}`) ?? 0;
      if (v > maxAverage) maxAverage = v;
      cells.push({ x: WEEKDAYS[weekday]!, y: HOURS[hour]!, v });
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
            return context.raw.v ? emberColor(context.raw.v, maxAverage) : "#292725";
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
          title: { display: true, text: "Weekday" },
          grid: { display: false },
        },
        y: {
          type: "category", labels: HOURS, offset: true,
          ticks: { autoSkip: true, maxTicksLimit: 8 },
          title: { display: true, text: "Time of Day" },
          grid: { display: false },
        },
      },
    },
  };
}
