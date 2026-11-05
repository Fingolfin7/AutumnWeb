import { formatDuration } from "@/lib/format";
import type { Chart } from "chart.js";
import { emberColor } from "./data";
import type { AnyConfig, HeatmapRow } from "./payloads";
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
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
            label: (context: { raw: { x: number; y: number; v: number } }) => {
              const { x, y, v } = context.raw;
              return `${WEEKDAYS[x]} ${y}:00 → ${formatDuration((v || 0) * 60)} avg`;
            },
          },
        },
        legend: { display: false },
      },
      scales: {
        x: {
          type: "linear",
          min: -.5,
          max: 6.5,
          ticks: { stepSize: 1, callback: (value: number | string) => Number.isInteger(Number(value)) ? WEEKDAYS[Number(value)] : "" },
          title: { display: true, text: "Weekday" },
          grid: { display: false },
        },
        y: {
          type: "linear",
          min: -.5,
          max: 23.5,
          reverse: true,
          ticks: { stepSize: 1, callback: (value: number | string) => Number.isInteger(Number(value)) ? `${String(value).padStart(2, "0")}:00` : "" },
          title: { display: true, text: "Time of Day" },
          grid: { display: false },
        },
      },
    },
  };
}
