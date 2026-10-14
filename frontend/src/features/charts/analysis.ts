import { paletteColor, withAlpha } from "./data";
import type { AnyConfig, TT, BubbleRow, HistogramRow, RadarRow } from "./payloads";

/* Session histogram, project radar and tag bubble
   (core/static/core/js/charts/analysis.js). */

export function histogramConfig(data: HistogramRow[]): AnyConfig {
  const labels = data.map((row) => row.label);
  const counts = data.map((row) => Number(row.count));
  const total = counts.reduce((a, b) => a + b, 0);
  /* Short sessions cool, long ones warm. */
  const colors = labels.map((_, i) => `hsl(${Math.max(0, 200 - i * 30)}, 70%, 55%)`);

  return {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Number of Sessions",
          data: counts,
          backgroundColor: colors,
          borderWidth: 1,
          borderColor: colors.map((color) => color.replace("55%", "45%")),
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        title: { display: true, text: "Session Duration Distribution" },
        legend: { display: false },
        tooltip: {
          callbacks: {
            label(context: TT) {
              const count = context.parsed.y!;
              const pct = total > 0 ? ((count / total) * 100).toFixed(1) : "0";
              return `${count} sessions (${pct}%)`;
            },
          },
        },
      },
      scales: {
        x: { title: { display: true, text: "Session Duration" } },
        y: {
          beginAtZero: true,
          title: { display: true, text: "Number of Sessions" },
          ticks: { stepSize: 1, callback: (value: number | string) => (Number.isInteger(value) ? value : undefined) },
        },
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
        /* The old string surgery left these fills opaque, hiding every
           project behind the biggest; 0.2 is what it meant. */
        backgroundColor: withAlpha(paletteColor(i), 0.2),
        borderWidth: 2,
        pointBackgroundColor: paletteColor(i),
      })),
    },
    options: {
      responsive: true,
      plugins: {
        title: { display: true, text: `Project Comparison (Top ${metrics.length})` },
        legend: { position: "top" },
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
        r: { beginAtZero: true, max: 100, ticks: { stepSize: 20, display: false }, pointLabels: { font: { size: 12 } } },
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
          backgroundColor: bubbles.map((b) => withAlpha(b.color, 0.6)),
          borderColor: bubbles.map((b) => b.color),
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        title: { display: true, text: "Tags by Project Count vs Time" },
        legend: { display: false },
        tooltip: {
          callbacks: {
            label(context: TT) {
              const point = context.raw as { name: string; x: number; y: number };
              return [`Tag: ${point.name}`, `Projects: ${point.x}`, `Total Time: ${point.y.toFixed(1)} hours`];
            },
          },
        },
      },
      scales: {
        x: {
          title: { display: true, text: "Number of Projects" },
          beginAtZero: true,
          ticks: { stepSize: 1, callback: (value: number | string) => (Number.isInteger(value) ? value : undefined) },
        },
        y: { title: { display: true, text: "Total Hours" }, beginAtZero: true },
      },
    },
  };
}
