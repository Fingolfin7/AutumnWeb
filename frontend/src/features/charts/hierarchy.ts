import { paletteColor } from "./data";
import type { AnyConfig, HierarchyNode, TallyRow } from "./payloads";

/* Treemap (core/static/core/js/charts/hierarchy.js). The server sends
   All -> context -> project -> subproject; the chart groups by project, then
   subproject, so the context level is skipped. */

export interface TreemapLeaf {
  name: string;
  project: string;
  /** Hours. */
  value: number;
}

export function flattenHierarchy(data: HierarchyNode | TallyRow[]): { leaves: TreemapLeaf[]; colors: Record<string, string> } {
  const leaves: TreemapLeaf[] = [];
  const colors: Record<string, string> = {};
  let colorIndex = 0;
  const colorFor = (project: string) => (colors[project] ??= paletteColor(colorIndex++));

  if (!Array.isArray(data)) {
    for (const context of data.children ?? []) {
      for (const project of context.children ?? []) {
        if (!((project.total_time ?? 0) > 0)) continue;
        colorFor(project.name);
        const subprojects = (project.children ?? []).filter((child) => (child.total_time ?? 0) > 0);
        if (project.children?.length) {
          for (const child of subprojects) leaves.push({ name: child.name, project: project.name, value: child.total_time! / 60 });
        } else {
          leaves.push({ name: project.name, project: project.name, value: project.total_time! / 60 });
        }
      }
    }
  }

  /* No hierarchy: fall back to flat project rows. */
  if (!leaves.length && Array.isArray(data)) {
    data.forEach((row, index) => {
      if (row.total_time > 0) {
        leaves.push({ name: row.name, project: row.name, value: row.total_time / 60 });
        colors[row.name] ??= paletteColor(index);
      }
    });
  }
  return { leaves, colors };
}

interface TreemapRaw {
  v?: number;
  value?: number;
  g?: string;
  _data?: { name?: string; project?: string; children?: { project?: string }[] };
}
interface TreemapContext {
  type: string;
  raw: TreemapRaw;
}

/* A project container carries its project in _data; a leaf (subproject) only
   keeps the names it was grouped by, so its project comes from the source row
   it was built from. */
export function projectOf(raw: TreemapRaw): string | undefined {
  return raw._data?.project || raw._data?.children?.[0]?.project || raw.g;
}

export function treemapConfig(data: HierarchyNode | TallyRow[]): AnyConfig | null {
  const { leaves, colors } = flattenHierarchy(data);
  if (!leaves.length) return null;

  return {
    type: "treemap",
    data: {
      datasets: [
        {
          tree: leaves,
          key: "value",
          groups: ["project", "name"],
          spacing: 1,
          borderWidth: 2,
          borderColor: "rgba(255,255,255,0.8)",
          backgroundColor(context: TreemapContext) {
            if (context.type !== "data") return "transparent";
            const project = projectOf(context.raw);
            return project ? (colors[project] ?? "hsl(200, 70%, 60%)") : "transparent";
          },
          labels: {
            display: true,
            align: "center",
            position: "middle",
            formatter(context: TreemapContext) {
              if (context.type !== "data") return "";
              const item = context.raw;
              const value = item.v || item.value || 0;
              if (value < 0.5) return ""; // no labels on tiny boxes
              /* A leaf carries its record in _data; a project container only
                 has its group name in g. */
              if (item._data?.name) return `${item._data.name}\n${value.toFixed(1)}h`;
              if (item.g) return item.g;
              return "";
            },
            color: "white",
            font: { size: 11, weight: "bold" },
          },
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        title: { display: true, text: "Time Distribution (Treemap)" },
        legend: { display: false },
        tooltip: {
          callbacks: {
            title(items: { raw: TreemapRaw }[]) {
              if (!items.length) return "";
              const item = items[0]!.raw;
              return projectOf(item) || "";
            },
            label(context: TreemapContext) {
              const item = context.raw;
              const value = item.v || item.value || 0;
              return `${item._data?.name || item.g || ""}: ${value.toFixed(2)} hours`;
            },
          },
        },
      },
    },
  };
}
