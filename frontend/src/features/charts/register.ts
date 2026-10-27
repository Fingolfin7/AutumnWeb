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

/* Night Ledger defaults (charts/core.js initUIElements). */
Chart.defaults.color = "#d9dedb";
Chart.defaults.borderColor = "rgba(217, 222, 219, 0.12)";
Chart.defaults.font.family = '"Aptos", "Segoe UI", "Helvetica Neue", Arial, sans-serif';
Chart.defaults.plugins.legend.labels.boxWidth = 12;
Chart.defaults.plugins.legend.labels.boxHeight = 12;
/* Fill #canvas_container's height rather than a 2:1 box of its width: on a
   phone that box is ~180px tall and a long legend leaves the plot a sliver.
   The calendar opts back in to its own ratio. */
Chart.defaults.maintainAspectRatio = false;

export { Chart };
