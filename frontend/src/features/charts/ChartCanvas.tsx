import { useEffect, useRef } from "react";
import { Chart } from "./register";
import { drawWordcloud, stopWordcloud } from "./wordcloud";
import type { Built } from "./build";

/* Owns one canvas and the one Chart.js instance (or word cloud) drawn on it.
   The effect's cleanup destroys the chart, so a type change, new data or an
   unmount never leaves an instance behind or draws twice on a canvas. */
export function ChartCanvas({ built }: { built: Built }) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const element = canvas.current;
    if (!element) return;

    if (built.type === "chart") {
      const chart = new Chart(element, built.config);
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

  return <canvas id="chart" ref={canvas} role="img" aria-label={built.type === "wordcloud" ? "Word cloud of session notes" : "Chart of tracked time"} />;
}
