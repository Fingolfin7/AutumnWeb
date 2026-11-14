import { fmtHours, HOURS_AXIS, paletteColor, withAlpha, type ChartOptions } from "./data";
import { token } from "./theme";
import type { AnyConfig, TT, BubbleRow, HistogramRow, RadarRow } from "./payloads";

/* Session histogram, project radar and tag bubble
   (core/static/core/js/charts/analysis.js). */

/* One hue: the bars differ by height, not identity. A previous period is a
   faded twin beside each bar. */
export function histogramConfig(data: HistogramRow[], { previous }: ChartOptions): AnyConfig {
  const labels = data.map((row) => row.label);
  const counts = data.map((row) => Number(row.count));
  const total = counts.reduce((a, b) => a + b, 0);
  const brand = token("--brand");
  const datasets = [{ label: "This period", data: counts, backgroundColor: brand }];
  if (previous) {
    const before = new Map((previous as HistogramRow[]).map((row) => [row.label, Number(row.count)] as const));
    datasets.push({ label: "Previous period", data: labels.map((label) => before.get(label) ?? 0), backgroundColor: withAlpha(brand, 0.3) });
  }

  return {
    type: "bar",
    data: { labels, datasets },
    options: {
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label(context: TT) {
              const count = context.parsed.y!;
              if (context.datasetIndex) return `Previous period: ${count} sessions`;
              const pct = total > 0 ? Math.round((count / total) * 100) : 0;
              return `${count} sessions (${pct}%)`;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: "Sessions" } },
      },
    },
  };
}

export const RADAR_TOP = 6;
export const RADAR_AXES = ["Total Time", "Sessions", "Avg Length", "Subprojects", "Recency"];

export interface RadarMetric {
  name: string;
  totalTime: number;
  sessionCount: number;
  avgSessionLength: number;
  subprojectCount: number;
  recency: number;
}

/* The six biggest projects with time, with the five axes' raw values. */
export function radarMetrics(data: RadarRow[]): RadarMetric[] {
  return [...data]
    .filter((project) => project.total_time > 0)
    .sort((a, b) => b.total_time - a.total_time)
    .slice(0, RADAR_TOP)
    .map((project) => ({
      name: project.name,
      totalTime: project.total_time / 60,
      sessionCount: project.session_count || 0,
      avgSessionLength: project.session_count > 0 ? project.total_time / 60 / project.session_count : 0,
      subprojectCount: project.subproject_count || 0,
      /* Days since the last activity, inverted: 30 is today, 0 a month ago. */
      recency: project.days_since_update !== undefined ? Math.max(0, 30 - project.days_since_update) : 15,
    }));
}

export function radarConfig(data: RadarRow[]): AnyConfig | null {
  const metrics = radarMetrics(data);
  if (!metrics.length) return null;
  const max = {
    totalTime: Math.max(...metrics.map((m) => m.totalTime), 1),
    sessionCount: Math.max(...metrics.map((m) => m.sessionCount), 1),
    avgSessionLength: Math.max(...metrics.map((m) => m.avgSessionLength), 1),
    subprojectCount: Math.max(...metrics.map((m) => m.subprojectCount), 1),
    recency: 30,
  };

  return {
    type: "radar",
    data: {
      labels: RADAR_AXES,
      datasets: metrics.map((m, i) => ({
        label: m.name,
        data: [
          (m.totalTime / max.totalTime) * 100,
          (m.sessionCount / max.sessionCount) * 100,
          (m.avgSessionLength / max.avgSessionLength) * 100,
          (m.subprojectCount / max.subprojectCount) * 100,
          (m.recency / max.recency) * 100,
        ],
        borderColor: paletteColor(i),
        backgroundColor: withAlpha(paletteColor(i), 0.1),
        pointBackgroundColor: paletteColor(i),
        pointRadius: 2.5,
        /* Monotone smoothing (the line default) needs points in x order,
           which a radial scale has not got. */
        cubicInterpolationMode: "default",
      })),
    },
    options: {
      responsive: true,
      plugins: {
        title: { display: true, align: "center", text: `Top ${metrics.length} projects, each axis scaled to the largest` },
        tooltip: {
          callbacks: {
            label(context: TT) {
              const m = metrics[context.datasetIndex]!;
              const lines = [
                `Total: ${m.totalTime.toFixed(1)}h`,
                `Sessions: ${m.sessionCount}`,
                `Avg: ${m.avgSessionLength.toFixed(1)}h`,
                `Subprojects: ${m.subprojectCount}`,
                `Recency: ${m.recency.toFixed(0)}/30`,
              ];
              return `${m.name}: ${lines[context.dataIndex]}`;
            },
          },
        },
      },
      scales: {
        r: { beginAtZero: true, max: 100, ticks: { stepSize: 25, display: false }, angleLines: { color: token("--hairline") }, pointLabels: { color: token("--ink-2"), font: { size: 12 } } },
      },
    },
  };
}

export function bubbleConfig(data: BubbleRow[]): AnyConfig | null {
  if (!data.length) return null;
  const bubbles = data.map((tag, i) => ({
    x: tag.project_count,
    y: tag.total_time / 60,
    r: Math.max(5, Math.sqrt(tag.total_time / 60) * 3),
    name: tag.name,
    color: tag.color || paletteColor(i),
  }));

  return {
    type: "bubble",
    data: {
      datasets: [
        {
          label: "Tags",
          data: bubbles,
          backgroundColor: bubbles.map((b) => withAlpha(b.color, 0.55)),
          borderColor: bubbles.map((b) => b.color),
          borderWidth: 1.5,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label(context: TT) {
              const point = context.raw as { name: string; x: number; y: number };
              return [point.name, `${point.x} ${point.x === 1 ? "project" : "projects"}`, fmtHours(point.y)];
            },
          },
        },
      },
      scales: {
        x: {
          title: { display: true, text: "Projects with the tag" },
          beginAtZero: true,
          ticks: { precision: 0 },
        },
        y: HOURS_AXIS,
      },
    },
  };
}
