import {
  ArcElement,
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  DoughnutController,
  Filler,
  Legend,
  LineController,
  LineElement,
  LinearScale,
  PointElement,
  TimeScale,
  Title,
  Tooltip,
} from "chart.js";
import "chartjs-adapter-date-fns";
import { MatrixController, MatrixElement } from "chartjs-chart-matrix";

/* Only what the charts use, so the rest of Chart.js is tree-shaken away. */
Chart.register(
  ArcElement,
  BarController,
  BarElement,
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
  TimeScale,
  Title,
  Tooltip,
);

/* Night Ledger defaults (charts/core.js initUIElements). */
Chart.defaults.font.size = 13;
Chart.defaults.color = "#aaa69f";
Chart.defaults.borderColor = "rgba(228, 232, 229, 0.06)";
Chart.defaults.font.family = '"Aptos", "Segoe UI", "Helvetica Neue", Arial, sans-serif';
Chart.defaults.plugins.legend.labels.usePointStyle = true;
Chart.defaults.plugins.legend.labels.boxWidth = 8;
Chart.defaults.plugins.legend.labels.boxHeight = 8;
Chart.defaults.plugins.tooltip.backgroundColor = "#202326";
Chart.defaults.plugins.tooltip.padding = 12;
Chart.defaults.elements.line.borderWidth = 2;
Chart.defaults.elements.point.radius = 2;
/* Fill #canvas_container's height rather than a 2:1 box of its width: on a
   phone that box is ~180px tall and a long legend leaves the plot a sliver.
   The calendar opts back in to its own ratio. */
Chart.defaults.maintainAspectRatio = false;

export { Chart };
