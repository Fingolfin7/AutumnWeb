import {
  ArcElement,
  BarController,
  BarElement,
  BubbleController,
  CategoryScale,
  Chart,
  DoughnutController,
  Filler,
  Legend,
  LineController,
  LineElement,
  LinearScale,
  PointElement,
  RadarController,
  RadialLinearScale,
  ScatterController,
  TimeScale,
  Title,
  Tooltip,
} from "chart.js";
import "chartjs-adapter-date-fns";
import { token } from "./theme";
import { MatrixController, MatrixElement } from "chartjs-chart-matrix";
import { TreemapController, TreemapElement } from "chartjs-chart-treemap";

/* Only what the charts use, so the rest of Chart.js is tree-shaken away. */
Chart.register(
  ArcElement,
  BarController,
  BarElement,
  BubbleController,
  CategoryScale,
  DoughnutController,
  Filler,
  Legend,
  LineController,
  LineElement,
  LinearScale,
  MatrixController,
  MatrixElement,
  PointElement,
  RadarController,
  RadialLinearScale,
  ScatterController,
  TimeScale,
  Title,
  Tooltip,
  TreemapController,
  TreemapElement,
);

/* The one Night Ledger theme every kind draws with; builders only add what
   is particular to their chart. Quiet hairline grids and no axis lines, ticks
   in muted ink, round dot legends, rounded bars, 2px monotone lines with
   points only on hover (ringed in the surface colour), doughnut slices
   separated by real gaps so a background photo shows through, and tooltips
   on the solid slab. */
const ink = token("--ink");
const ink2 = token("--ink-2");
const muted = token("--muted");
const hairline = token("--hairline");
const surface = token("--slab-solid");
const font = token("--font-ui");
const d = Chart.defaults;

d.color = ink2;
d.borderColor = hairline;
d.font.family = font;
d.font.size = 12;
/* Fill #canvas_container's height rather than a 2:1 box of its width: on a
   phone that box is ~180px tall and a long legend leaves the plot a sliver.
   The calendar opts back in to its own ratio. */
d.maintainAspectRatio = false;

/* Gridlines take d.borderColor (the hairline). */
d.set("scale", { border: { display: false }, grid: { tickLength: 0 }, ticks: { color: muted, padding: 8 }, title: { color: muted } });
d.set("scales.time", { grid: { display: false }, time: { displayFormats: { day: "d MMM", week: "d MMM", month: "MMM", quarter: "MMM yyyy", year: "yyyy" } } });

d.plugins.title.align = "start";
d.plugins.title.color = ink2;
d.plugins.title.font = { size: 12, weight: "normal" };
d.plugins.title.padding = { top: 0, bottom: 12 };

Object.assign(d.plugins.legend.labels, { usePointStyle: true, pointStyle: "circle", boxWidth: 7, boxHeight: 7, padding: 14, color: ink2 });

Object.assign(d.plugins.tooltip, {
  backgroundColor: surface,
  borderColor: token("--hairline-2"),
  borderWidth: 1,
  titleColor: ink,
  bodyColor: ink2,
  titleFont: { weight: "600" },
  padding: 10,
  cornerRadius: 10,
  caretSize: 0,
  boxPadding: 5,
  usePointStyle: true,
});

d.elements.bar.borderRadius = 4;
d.elements.bar.borderWidth = 0;
d.datasets.bar.categoryPercentage = 0.72;
d.datasets.bar.barPercentage = 0.88;
d.datasets.bar.maxBarThickness = 32;
d.elements.line.borderWidth = 2;
d.elements.line.cubicInterpolationMode = "monotone";
d.elements.point.radius = 0;
d.elements.point.hoverRadius = 5;
d.elements.point.hitRadius = 8;
d.elements.point.hoverBorderWidth = 2;
d.elements.point.hoverBorderColor = surface;
d.elements.arc.borderWidth = 0;
d.elements.arc.borderRadius = 4;
d.datasets.doughnut.spacing = 3;
Chart.overrides.doughnut.cutout = "60%";
Chart.overrides.doughnut.plugins.legend.position = "top";

export { Chart };
