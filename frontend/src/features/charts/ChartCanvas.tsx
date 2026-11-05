import { useEffect, useRef, useState } from "react";
import type { ScaleOptions } from "chart.js";
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
        scale.title = { ...scale.title, display: false };
        scale.ticks = { ...scale.ticks, maxTicksLimit: 6, padding: 10 };
      });
      const chart = new Chart(element, config);
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

  const series = built.type === "chart" ? (built.config.type === "doughnut" ? (built.config.data.labels ?? []).map(String) : built.config.data.datasets.map((dataset) => dataset.label ?? "").filter(Boolean)) : [];
  return <><canvas id="chart" ref={canvas} role="img" aria-label={built.type === "wordcloud" ? "Word cloud of session notes" : "Chart of tracked time"} />{series.length > 1 ? <details className="chart-series"><summary>{series.length} series Â· Show legend</summary><ul>{series.map((name, index) => <li key={`${name}-${index}`}><button type="button" aria-pressed={!hidden.includes(index)} onClick={() => { const chart = canvas.current ? Chart.getChart(canvas.current) : undefined; if (!chart) return; if (built.type === "chart" && built.config.type === "doughnut") chart.toggleDataVisibility(index); else chart.setDatasetVisibility(index, hidden.includes(index)); chart.update(); setHidden((items) => items.includes(index) ? items.filter((item) => item !== index) : [...items, index]); }}><span className={`chart-series-dot chart-series-dot--${index % 12}`} />{name}</button></li>)}</ul></details> : null}</>;

}

