import { fmtHours, paletteColor, withAlpha } from "./data";
import { token } from "./theme";
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
    /* Biggest project first, so each wears the colour it has on every kind. */
    const projects = (data.children ?? []).flatMap((context) => context.children ?? []).sort((a, b) => (b.total_time ?? 0) - (a.total_time ?? 0));
    for (const project of projects) {
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

  /* No hierarchy: fall back to flat project rows. */
  if (!leaves.length && Array.isArray(data)) {
    [...data].sort((a, b) => b.total_time - a.total_time).forEach((row, index) => {
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

  /* Projects are quiet tinted frames with their name as a caption; their
     subprojects are solid tiles in the project's colour, with dark labels
     (light text on these mid-tone fills is hard to read). */
  return {
    type: "treemap",
    data: {
      datasets: [
        {
          tree: leaves,
          key: "value",
          groups: ["project", "name"],
          spacing: 2,
          borderWidth: 0,
          borderRadius: 4,
          backgroundColor(context: TreemapContext) {
            if (context.type !== "data") return "transparent";
            const color = colors[projectOf(context.raw) ?? ""] ?? token("--muted");
            return context.raw._data?.name ? color : withAlpha(color, 0.22);
          },
          captions: { display: true, align: "left", color: token("--ink"), font: { size: 12, weight: "600" }, padding: 4 },
          labels: {
            display: true,
            align: "left",
            position: "top",
            overflow: "hidden",
            formatter(context: TreemapContext) {
              const item = context.raw;
              const value = item.v || item.value || 0;
              return item._data?.name ? [item._data.name, fmtHours(value)] : "";
            },
            color: token("--ink-invert"),
            font: [{ size: 12, weight: "600" }, { size: 11 }],
          },
        },
      ],
    },
    options: {
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title(items: { raw: TreemapRaw }[]) {
              return items.length ? projectOf(items[0]!.raw) || "" : "";
            },
            label(context: TreemapContext) {
              const item = context.raw;
              return `${item._data?.name || item.g || ""}: ${fmtHours(item.v || item.value || 0)}`;
            },
          },
        },
      },
    },
  };
}
