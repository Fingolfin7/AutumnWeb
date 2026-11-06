import { useEffect, useRef, useState } from "react";
import type { ScaleOptions } from "chart.js";
import { formatDuration } from "@/lib/format";
import { paletteColor } from "./data";
import { Chart } from "./register";
import { topTerms } from "./terms";
import { AppLink, urls } from "@/app/links";
import { useLocation } from "react-router";
import type { Built } from "./build";

/* Owns one canvas and the one Chart.js instance (or word cloud) drawn on it.
   The effect's cleanup destroys the chart, so a type change, new data or an
   unmount never leaves an instance behind or draws twice on a canvas. */
export function ChartCanvas({ built }: { built: Built }) {
  const location = useLocation();
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
        scale.title = { display: false };
        scale.border = { display: false };

        scale.ticks = { maxTicksLimit: 8, padding: 10, ...scale.ticks };
      });
      const chart = new Chart(element, { ...config, plugins: [...(config.plugins ?? []), {
        id: "donutTotal", afterDraw(chart) {
          if (config.type === "bar" && config.data.datasets[0]?.label === "Number of Sessions") {
            const { ctx } = chart; ctx.save(); ctx.font = "600 13px Manrope, sans-serif"; ctx.fillStyle = "#f0ece5"; ctx.textBaseline = "middle";
            chart.getDatasetMeta(0).data.forEach((bar, index) => { ctx.textAlign = "left"; ctx.fillText(String(config.data.datasets[0].data[index]), bar.x + 8, bar.y); });
            ctx.restore(); return;
          }
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

  }, [built]);

  if (built.type === "wordcloud") {
    const words = topTerms(built.words);
    return <div className="chart-terms"><ol aria-label="Terms ranked by count">{words.map(row => {
      const params = new URLSearchParams(location.search); params.delete("chart_type"); params.delete("view"); params.set("search", row.text);
      return <li key={row.text}><AppLink href={`${urls.sessions()}?${params}`}><span>{row.text}</span><strong>{row.weight}</strong><svg viewBox="0 0 1000 4" preserveAspectRatio="none" aria-hidden="true"><rect width={Number(row.weight)/Math.max(Number(words[0]?.weight),1)*1000} height="4" rx="2" /></svg></AppLink></li>;
    })}</ol>{!words.length ? <p className="muted">More words will appear as your journal grows.</p> : null}</div>;
  }
  const config = built.type === "chart" ? built.config : null;
  const histogram = config?.data.datasets[0]?.label === "Number of Sessions";
  const byLabel = config && ["doughnut", "bar"].includes(config.type) && config.data.datasets.length === 1 && !config.options?.scales?.x?.stacked;
  const series = !config || config.type === "matrix" ? [] : byLabel
    ? (config.data.labels ?? []).map((name, index) => ({ name: String(name), minutes: Number(config.data.datasets[0].data[index]) * 60, color: config.data.datasets[0].backgroundColor?.[index] ?? paletteColor(index) }))
    : config.data.datasets.map(dataset => ({ name: dataset.label ?? "", minutes: (config.type === "line" && dataset.label?.includes("period") ? Number(dataset.data.at(-1)) : dataset.data.reduce((sum: number, value: number) => sum + Number(value), 0)) * 60, color: dataset.borderColor ?? dataset.backgroundColor }));
  const totalMinutes = series.reduce((sum, row) => sum + row.minutes, 0);
  const sortedSeries = series.map((row, index) => ({ ...row, index })).sort((a,b) => b.minutes - a.minutes);
  return <><div className="chart-plot"><canvas id="chart" ref={canvas} role="img" aria-label={"Chart of tracked time; values listed below"} /></div>{config?.type === "matrix" ? <p className="chart-heat-key"><span>Less time</span>{Array.from({ length: 6 }, (_, index) => <i className={`ember-cell ember-cell--${index}`} key={index} />)}<span>More time</span></p> : null}{series.length ? <ul className={`chart-series chart-series--${built.labels ?? "projects"}${histogram ? " chart-series--counts" : ""}`} aria-label="Chart values">{sortedSeries.map((row) => { const index = row.index; return <li key={`${row.name}-${index}`}><button type="button" disabled={histogram} aria-pressed={!hidden.includes(index)} onClick={() => { const chart = canvas.current ? Chart.getChart(canvas.current) : undefined; if (!chart) return; if (byLabel) chart.toggleDataVisibility(index); else chart.setDatasetVisibility(index, hidden.includes(index)); chart.update(); setHidden(items => items.includes(index) ? items.filter(item => item !== index) : [...items, index]); }}><svg className="chart-series-dot" viewBox="0 0 8 8" aria-hidden="true"><circle cx="4" cy="4" r="4" fill={typeof row.color === "string" ? row.color : paletteColor(index)} /></svg><span>{row.name}</span><strong>{histogram ? `${Math.round(row.minutes / 60)} ${Math.round(row.minutes / 60) === 1 ? "session" : "sessions"}` : <>{formatDuration(row.minutes)}{config?.type === "doughnut" && totalMinutes ? ` ? ${Math.round(row.minutes / totalMinutes * 100)}%` : ""}</>}</strong></button></li>; })}</ul> : null}</>;
}
