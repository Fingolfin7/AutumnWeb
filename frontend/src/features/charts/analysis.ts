import { EMBER_RAMP } from "./data";
import type { AnyConfig, TT, HistogramRow } from "./payloads";

/* Session length distribution, in ember pigments. */

export function histogramConfig(data: HistogramRow[]): AnyConfig {
  data = data.filter(row => Number(row.count) > 0);
  const labels = data.map((row) => row.label);
  const counts = data.map((row) => Number(row.count));
  const total = counts.reduce((a, b) => a + b, 0);
  /* Longer sessions glow more warmly. */
  const colors = labels.map(() => EMBER_RAMP[4]!);

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
      indexAxis: "y",
      plugins: {
        title: { display: true, text: "Session Duration Distribution" },
        legend: { display: false },
        tooltip: {
          callbacks: {
            label(context: TT) {
              const count = context.parsed.x!;
              const pct = total > 0 ? ((count / total) * 100).toFixed(1) : "0";
              return `${count} sessions (${pct}%)`;
            },
          },
        },
      },
      scales: {
        y: { ticks: { autoSkip: false, maxRotation: 0 } },
        x: {
          beginAtZero: true,
          ticks: { stepSize: 1, callback: (value: number | string) => (Number.isInteger(value) ? value : undefined) },
        },
      },
    },
  };
}

