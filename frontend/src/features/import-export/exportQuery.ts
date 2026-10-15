/* Turning the Export form into a GET /api/v2/export/ query and a filename. */

export interface ExportForm {
  startDate: string;
  endDate: string;
  context: string;
  tags: number[];
  projectName: string;
  projects: number[];
  projectMode: "include" | "exclude";
  outputFile: string;
  legacy: boolean;
  autumnCompatible: boolean;
  compress: boolean;
}

export const EMPTY_EXPORT_FORM: ExportForm = {
  startDate: "",
  endDate: "",
  context: "",
  tags: [],
  projectName: "",
  projects: [],
  projectMode: "exclude",
  outputFile: "",
  legacy: false,
  autumnCompatible: false,
  compress: false,
};

export function buildExportQuery(form: ExportForm): URLSearchParams {
  const query = new URLSearchParams();
  if (form.startDate) query.set("start_date", form.startDate);
  if (form.endDate) query.set("end_date", form.endDate);
  if (form.context) query.set("context_ids", form.context);
  if (form.tags.length) query.set("tag_ids", form.tags.join(","));
  const name = form.projectName.trim();
  if (name) query.set("project_name", name);
  if (form.projects.length) {
    query.set(form.projectMode === "include" ? "project_ids" : "exclude_project_ids", form.projects.join(","));
  }
  if (form.legacy) {
    query.set("export_format", "1");
    if (form.autumnCompatible) query.set("autumn_compatible", "true");
  }
  if (form.compress) query.set("compress", "true");
  return query;
}

/* The old view's rule: the typed name, else "<project name filter>.json", else
   "projects.json"; always ending in .json. Characters a file system rejects
   are replaced so a project name cannot make the download fail. */
export function exportFilename(form: Pick<ExportForm, "outputFile" | "projectName">): string {
  let name = form.outputFile.trim() || `${form.projectName.trim() || "projects"}.json`;
  name = name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_");
  if (!name.endsWith(".json")) name += ".json";
  return name;
}

/* Why the form cannot be submitted, by field. */
export function validateExport(form: Pick<ExportForm, "startDate" | "endDate">): Record<string, string> {
  const errors: Record<string, string> = {};
  if (form.startDate && form.endDate && form.endDate < form.startDate) {
    errors.end_date = "End date must be on or after the start date.";
  }
  return errors;
}

interface ScopeProject {
  id: number;
  context: { id: number } | null;
  tags: { id: number }[];
}

/* Which projects the picker offers: those in the chosen context and with at
   least one chosen tag (export_pickers: EXCLUDE_PROJECT_META). Ticked ones
   always stay, so a filter you can no longer see is never left applied. */
export function projectsInScope<T extends ScopeProject>(
  projects: T[],
  context: string,
  tags: number[],
  selected: number[],
): T[] {
  const ctx = context ? Number(context) : null;
  const keep = new Set(selected);
  return projects.filter((project) => {
    if (keep.has(project.id)) return true;
    if (ctx !== null && project.context?.id !== ctx) return false;
    if (tags.length && !project.tags.some((tag) => tags.includes(tag.id))) return false;
    return true;
  });
}

/* Contexts with "General" pinned first, as the old form listed them. */
export function orderContexts<T extends { name: string }>(contexts: T[]): T[] {
  const general = contexts.find((context) => context.name === "General");
  const rest = contexts.filter((context) => context !== general);
  return general ? [general, ...rest] : rest;
}

/* The old view wrote the document with 4-space indentation unless compressed. */
export function formatExport(text: string, compress: boolean): string {
  if (compress) return text;
  try {
    return JSON.stringify(JSON.parse(text), null, 4);
  } catch {
    return text;
  }
}
