import { useEffect, useRef, useState } from "react";
import type { ScaleOptions } from "chart.js";
import { formatDuration } from "@/lib/format";
import { paletteColor } from "./data";
import { Chart } from "./register";
import { drawWordcloud, stopWordcloud } from "./wordcloud";
import type { Built } from "./build";

/* Owns one canvas and the one Chart.js instance (or word cloud) drawn on it.
   The effect's cleanup destroys the chart, so a type change, new data or an
   unmount never leaves an instance behind or draws twice on a canvas. */
export function ChartCanvas({ built }: { built: Built }) {
  const [hidden, setHidden] = useState<number[]>([]);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    setHidden([]);
    const element = canvas.current;
    if (!element) return;

    if (built.type === "chart") {
      const config = built.config;
      config.options ??= {};
      config.options.plugins ??= {};
      config.options.plugins.title = { ...config.options.plugins.title, display: false };
      config.options.plugins.legend = { ...config.options.plugins.legend, display: false };
      if (config.options.scales) Object.values(config.options.scales).forEach((value) => {
        const scale = value as Partial<ScaleOptions<"linear">> | undefined;
        if (!scale) return;
        scale.grid = { ...scale.grid, color: "rgba(228,232,229,.06)", drawTicks: false };
        scale.border = { display: false };

        scale.ticks = { maxTicksLimit: 8, padding: 10, ...scale.ticks };
      });
      const chart = new Chart(element, { ...config, plugins: [...(config.plugins ?? []), {
        id: "donutTotal", afterDraw(chart) {
          if (config.type !== "doughnut") return;
          const total = config.data.datasets[0].data.reduce((sum: number, value: number) => sum + Number(value), 0) * 60;
          const { ctx, chartArea: area } = chart;
          ctx.save(); ctx.textAlign = "center"; ctx.fillStyle = "#a5cf88";
          ctx.font = `600 ${Math.min(32, chart.width / 12)}px Manrope, sans-serif`;
          ctx.fillText(formatDuration(total), (area.left + area.right) / 2, (area.top + area.bottom) / 2);
          ctx.font = "13px Manrope, sans-serif"; ctx.fillStyle = "#aaa69f";
          ctx.fillText("tracked", (area.left + area.right) / 2, (area.top + area.bottom) / 2 + 26); ctx.restore();
        },
      }] });
      return () => chart.destroy();
    }

    /* The cloud has no responsive mode: draw at the container's size and
       again, debounced, when it changes. */
    const container = element.parentElement!;
    const draw = () => {
      const width = container.clientWidth || window.innerWidth * 0.8;
      const height = container.clientHeight || window.innerHeight * 0.6;
      drawWordcloud(element, built.words, width, height);
    };
    draw();
    let timer: number | undefined;
    let lastWidth = container.clientWidth;
    const observer = new ResizeObserver(() => {
      if (container.clientWidth === lastWidth) return;
      lastWidth = container.clientWidth;
      window.clearTimeout(timer);
      timer = window.setTimeout(draw, 150);
    });
    observer.observe(container);
    return () => {
      window.clearTimeout(timer);
      observer.disconnect();
      stopWordcloud();
    };
  }, [built]);

  const config = built.type === "chart" ? built.config : null;
  const byLabel = config && ["doughnut", "bar"].includes(config.type) && config.data.datasets.length === 1;
  const series = !config || config.type === "matrix" ? [] : byLabel
    ? (config.data.labels ?? []).map((name, index) => ({ name: String(name), minutes: Number(config.data.datasets[0].data[index]) * 60, color: config.data.datasets[0].backgroundColor?.[index] ?? paletteColor(index) }))
    : config.type === "treemap" ? [...new Set((config.data.datasets[0].tree ?? []).map((leaf: { project: string }) => leaf.project))].map(name => ({ name: String(name), minutes: (config.data.datasets[0].tree ?? []).filter((leaf: { project: string }) => leaf.project === name).reduce((sum: number, leaf: { value: number }) => sum + leaf.value * 60, 0), color: paletteColor(0) }))
    : config.data.datasets.map(dataset => ({ name: dataset.label ?? "", minutes: (config.type === "line" && dataset.label?.includes("period") ? Number(dataset.data.at(-1)) : dataset.data.reduce((sum: number, value: number) => sum + Number(value), 0)) * 60, color: dataset.borderColor ?? dataset.backgroundColor }));
  return <><div className="chart-plot"><canvas id="chart" ref={canvas} role="img" aria-label={built.type === "wordcloud" ? "Amber words from your session notes" : "Chart of tracked time; values listed below"} /></div>{series.length ? <ul className="chart-series" aria-label="Chart values">{series.map((row, index) => <li key={`${row.name}-${index}`}><button type="button" aria-pressed={!hidden.includes(index)} onClick={() => { const chart = canvas.current ? Chart.getChart(canvas.current) : undefined; if (!chart) return; if (byLabel) chart.toggleDataVisibility(index); else chart.setDatasetVisibility(index, hidden.includes(index)); chart.update(); setHidden(items => items.includes(index) ? items.filter(item => item !== index) : [...items, index]); }}><svg className="chart-series-dot" viewBox="0 0 8 8" aria-hidden="true"><circle cx="4" cy="4" r="4" fill={typeof row.color === "string" ? row.color : paletteColor(index)} /></svg><span>{row.name}</span><strong>{formatDuration(row.minutes)}</strong></button></li>)}</ul> : null}</>;
}
