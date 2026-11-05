import { formatDuration } from "@/lib/format";
import { seriesColor, seriesColors, withAlpha } from "./data";
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
  const colorFor = (project: string) => (colors[project] ??= seriesColor(project));

  if (!Array.isArray(data)) {
    for (const context of data.children ?? []) {
      for (const project of context.children ?? []) {
        if (!((project.total_time ?? 0) > 0)) continue;
        colorFor(project.name);
        const subprojects = (project.children ?? []).filter((child) => (child.total_time ?? 0) > 0);
        if (project.children?.length) {
          for (const child of subprojects) leaves.push({ name: child.name, project: project.name, value: child.total_time! / 60 });
          const unallocated = (project.total_time ?? 0) - subprojects.reduce((sum, child) => sum + (child.total_time ?? 0), 0);
          if (unallocated > 0.000001) leaves.push({ name: "No subproject", project: project.name, value: unallocated / 60 });
        } else {
          leaves.push({ name: project.name, project: project.name, value: project.total_time! / 60 });
        }
      }
    }
  }

  /* No hierarchy: fall back to flat project rows. */
  if (!leaves.length && Array.isArray(data)) {
    data.forEach((row) => {
      if (row.total_time > 0) {
        leaves.push({ name: row.name, project: row.name, value: row.total_time / 60 });
        colors[row.name] ??= seriesColor(row.name);
      }
    });
  }
  return { leaves, colors: Object.fromEntries(seriesColors(Object.keys(colors))) };
}

interface TreemapRaw {
  v?: number;
  value?: number;
  g?: string;
  w?: number;
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
          borderWidth: 0.75,
          borderColor: "rgba(240,236,229,.16)",
          captions: { display: false, color: "#f0ece5", font: { size: 13, weight: "500" }, padding: 8 },
          backgroundColor(context: TreemapContext) {
            if (context.type !== "data") return "transparent";
            const project = projectOf(context.raw);
            return project ? withAlpha(colors[project] ?? seriesColor(project), 0.32) : "transparent";
          },
          labels: {
            display: true,
            align: "center",
            position: "middle",
            overflow: "fit",
            padding: 8,
            formatter(context: TreemapContext) {
              if (context.type !== "data") return "";
              const item = context.raw;
              const value = item.v || item.value || 0;
              if (value < 0.5) return ""; // no labels on tiny boxes
              /* A leaf carries its record in _data; a project container only
                 has its group name in g. */
              if (item._data?.name) {
                const amount = formatDuration(value * 60);
                if ((item.w ?? 100) < 85) return "";
                if ((item.w ?? 100) < item._data.name.length * 7 + 16) return "";
                return [item._data.name, amount];
              }
              if (item.g) return item.g;
              return "";
            },
            color: "#e6dfd5",
            font: { size: 13, weight: "500" },
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
              return `${item._data?.name || item.g || ""}: ${formatDuration(value * 60)}`;
            },
          },
        },
      },
    },
  };
}
