import type { Commitment, Project, ProjectStatus } from "@/api/types";

/* ---------------------------------------------------------------- filters */

/* The Projects page keeps its filters in the URL with the same parameter names
   the server-rendered page used, so old bookmarks still open the same view. */
export interface ProjectFilters {
  search: string;
  start_date: string;
  end_date: string;
  /** "" = the header's active context, "all", or a context id. */
  context: string;
  tags: number[];
  projects: number[];
  projectMode: "include" | "exclude";
}

export const emptyFilters: ProjectFilters = {
  search: "",
  start_date: "",
  end_date: "",
  context: "",
  tags: [],
  projects: [],
  projectMode: "exclude",
};

export function readFilters(params: URLSearchParams): ProjectFilters {
  const ids = (name: string) =>
    params
      .getAll(name)
      .flatMap((value) => value.split(","))
      .map(Number)
      .filter((n) => Number.isInteger(n) && n > 0);
  const include = ids("include_projects");
  const exclude = ids("exclude_projects");
  return {
    search: (params.get("search") ?? "").trim(),
    start_date: params.get("start_date") ?? "",
    end_date: params.get("end_date") ?? "",
    context: params.get("context") ?? "",
    tags: ids("tags"),
    projects: include.length ? include : exclude,
    projectMode: include.length ? "include" : "exclude",
  };
}

export function writeFilters(state: ProjectFilters): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of ["search", "start_date", "end_date", "context"] as const) {
    if (state[key]) params.set(key, state[key]);
  }
  if (state.tags.length) params.set("tags", state.tags.join(","));
  if (state.projects.length) {
    params.set(state.projectMode === "include" ? "include_projects" : "exclude_projects", state.projects.join(","));
  }
  return params;
}

/** Filters the API applies itself; the rest are applied by applyClientFilters. */
export function serverQuery(filters: ProjectFilters, activeContextParam: string | undefined) {
  const query: Record<string, string | boolean> = {};
  if (filters.search) query.search = filters.search;
  const context = filters.context === "all" ? undefined : filters.context || activeContextParam;
  if (context) query.context_ids = context;
  if (filters.tags.length) query.tag_ids = filters.tags.join(",");
  if (filters.projectMode === "exclude" && filters.projects.length) query.exclude_project_ids = filters.projects.join(",");
  return query;
}

/* The API has no "created between" or "only these projects" filters, so they
   narrow the fetched list here. Same semantics as the old view: the end date
   only counts together with a start date, and is inclusive. */
export function applyClientFilters(projects: Project[], filters: ProjectFilters): Project[] {
  let result = projects;
  if (filters.projectMode === "include" && filters.projects.length) {
    const wanted = new Set(filters.projects);
    result = result.filter((project) => wanted.has(project.id));
  }
  if (filters.start_date) {
    const start = filters.start_date;
    const end = filters.end_date;
    result = result.filter((project) => project.start_date >= start && (!end || project.start_date <= end));
  }
  return result;
}

/** Most recently active first, like the old list (`-derived_last_updated`). */
export function sortByActivity(projects: Project[]): Project[] {
  return [...projects].sort((a, b) => {
    const left = a.last_activity ?? a.start_date;
    const right = b.last_activity ?? b.start_date;
    if (left !== right) return left < right ? 1 : -1;
    return a.name.localeCompare(b.name);
  });
}

export const STATUS_ORDER: { status: ProjectStatus; label: string }[] = [
  { status: "active", label: "Active" },
  { status: "paused", label: "Paused" },
  { status: "complete", label: "Complete" },
  { status: "archived", label: "Archived" },
];

export function groupByStatus(projects: Project[]) {
  return STATUS_ORDER.map(({ status, label }) => ({
    status,
    label,
    projects: projects.filter((project) => project.status === status),
  })).filter((group) => group.projects.length > 0);
}

/* Related = the meaning-based matches the keyword search missed. The API
   answers related=true with keyword matches plus related ones, unlabelled, so
   the related ones are whatever the keyword-only answer lacks. */
export function relatedOnly(withRelated: Project[], direct: Project[]): Project[] {
  const seen = new Set(direct.map((project) => project.id));
  return withRelated.filter((project) => !seen.has(project.id));
}

export interface FilterNames {
  projects: { id: number; name: string }[];
  tags: { id: number; name: string }[];
  contexts: { id: number; name: string }[];
}

export function describeFilters(state: ProjectFilters, lookup: FilterNames) {
  const names = (ids: number[], items: { id: number; name: string }[]) =>
    ids.map((id) => items.find((item) => item.id === id)?.name ?? `#${id}`).join(", ");
  const pills: { label: string; value: string }[] = [];
  if (state.search) pills.push({ label: "Search", value: state.search });
  if (state.start_date) pills.push({ label: "From", value: state.start_date });
  if (state.end_date) pills.push({ label: "To", value: state.end_date });
  if (state.context) {
    pills.push({
      label: "Context",
      value: state.context === "all" ? "All" : (lookup.contexts.find((c) => String(c.id) === state.context)?.name ?? state.context),
    });
  }
  if (state.tags.length) pills.push({ label: "Tags", value: names(state.tags, lookup.tags) });
  if (state.projects.length) {
    pills.push({ label: state.projectMode === "include" ? "Only" : "Excluding", value: names(state.projects, lookup.projects) });
  }
  return pills;
}

/* ------------------------------------------------------------ commitments */

export interface ProjectScope {
  id: number;
  contextId: number | null;
  tagIds: number[];
  /** Ids of the project's own subprojects. */
  subprojectIds: number[];
}

const has = (ids: number[], id: number) => ids.includes(id);

/* Whether a commitment is relevant to a project: the client twin of
   core.commitments.commitment_applies_to_project, working from the ids the
   API exposes on each commitment. */
export function commitmentAppliesToProject(commitment: Commitment, project: ProjectScope): boolean {
  const { target, filters } = commitment;
  switch (commitment.aggregation_type) {
    case "context":
      if (target.id !== project.contextId) return false;
      break;
    case "tag":
      if (!has(project.tagIds, target.id)) return false;
      break;
    case "project":
      if (target.id !== project.id) return false;
      break;
    case "subproject":
      return has(project.subprojectIds, target.id);
    default:
      return false;
  }
  if (filters.include_tag_ids.length && !filters.include_tag_ids.some((id) => has(project.tagIds, id))) return false;
  if (filters.exclude_tag_ids.some((id) => has(project.tagIds, id))) return false;
  if (filters.include_project_ids.length && !has(filters.include_project_ids, project.id)) return false;
  if (has(filters.exclude_project_ids, project.id)) return false;
  if (filters.include_subproject_ids.length && !filters.include_subproject_ids.some((id) => has(project.subprojectIds, id))) {
    return false;
  }
  return true;
}

/* Twin of commitment_applies_to_subproject. */
export function commitmentAppliesToSubproject(commitment: Commitment, project: ProjectScope, subprojectId: number): boolean {
  const { target, filters } = commitment;
  switch (commitment.aggregation_type) {
    case "context":
      if (target.id !== project.contextId) return false;
      break;
    case "tag":
      if (!has(project.tagIds, target.id)) return false;
      break;
    case "project":
      if (target.id !== project.id) return false;
      break;
    case "subproject":
      if (target.id !== subprojectId) return false;
      break;
    default:
      return false;
  }
  if (filters.include_tag_ids.length && !filters.include_tag_ids.some((id) => has(project.tagIds, id))) return false;
  if (filters.exclude_tag_ids.some((id) => has(project.tagIds, id))) return false;
  if (filters.include_project_ids.length && !has(filters.include_project_ids, project.id)) return false;
  if (has(filters.exclude_project_ids, project.id)) return false;
  if (filters.include_subproject_ids.length && !has(filters.include_subproject_ids, subprojectId)) return false;
  if (has(filters.exclude_subproject_ids, subprojectId)) return false;
  return true;
}

/** Active first, then by scope, then oldest first (the panel's order). */
export function sortCommitments(commitments: Commitment[]): Commitment[] {
  return [...commitments].sort((a, b) => {
    if (a.active !== b.active) return a.active ? -1 : 1;
    if (a.aggregation_type !== b.aggregation_type) return a.aggregation_type < b.aggregation_type ? -1 : 1;
    return a.id - b.id;
  });
}

export interface NameLookup {
  tags: Map<number, string>;
  projects: Map<number, string>;
  subprojects: Map<number, string>;
  contexts: Map<number, string>;
}

/* "Include Tags: a, b" lines (core.commitments.build_commitment_rule_lines).
   Empty when the whole scope counts. */
export function commitmentRuleLines(commitment: Commitment, names: NameLookup): string[] {
  const f = commitment.filters;
  const label = (map: Map<number, string>, ids: number[], fallback: string) =>
    ids.map((id) => map.get(id) ?? `${fallback} #${id}`).join(", ");
  const groups: [string, number[], number[], Map<number, string>, string][] = [
    ["Tags", f.include_tag_ids, f.exclude_tag_ids, names.tags, "Tag"],
    ["Projects", f.include_project_ids, f.exclude_project_ids, names.projects, "Project"],
    ["Subprojects", f.include_subproject_ids, f.exclude_subproject_ids, names.subprojects, "Subproject"],
    ["Contexts", f.include_context_ids, f.exclude_context_ids, names.contexts, "Context"],
  ];
  const lines: string[] = [];
  for (const [title, include, exclude, map, fallback] of groups) {
    if (include.length) lines.push(`Include ${title}: ${label(map, include, fallback)}`);
    if (exclude.length) lines.push(`Exclude ${title}: ${label(map, exclude, fallback)}`);
  }
  return lines;
}

/** Subproject ids a commitment's rules mention that are not yet named. */
export function unnamedSubprojectIds(commitments: Commitment[], known: Map<number, string>): number[] {
  const ids = new Set<number>();
  for (const commitment of commitments) {
    for (const id of [...commitment.filters.include_subproject_ids, ...commitment.filters.exclude_subproject_ids]) {
      if (!known.has(id)) ids.add(id);
    }
  }
  return [...ids].sort((a, b) => a - b);
}

/** 3, 3.5, 180 (never "180.0"). */
export function formatNumber(value: number): string {
  return String(Math.round(value * 100) / 100);
}

/** "+12m" / "-180m" / "+3" for bank figures. */
export function formatSigned(value: number, timeBased: boolean): string {
  const rounded = Math.round(value * 100) / 100;
  return `${rounded >= 0 ? "+" : ""}${formatNumber(rounded)}${timeBased ? "m" : ""}`;
}

/* "Project complete — 3h 20m tracked across 4 sessions."
   (core.celebrations.format_tracked_time) */
export function formatTracked(minutes: number): string {
  const total = Math.max(0, Math.round(minutes || 0));
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  if (hours && rest) return `${hours}h ${rest}m`;
  if (hours) return `${hours}h`;
  return `${rest}m`;
}

export function completionMessage(totalMinutes: number, sessionCount: number): string {
  if (!sessionCount) return "Project complete — no sessions logged yet.";
  return `Project complete — ${formatTracked(totalMinutes)} tracked across ${sessionCount} ${sessionCount === 1 ? "session" : "sessions"}.`;
}

/** An edit moved a live project into its completed state. */
export function isCompletionTransition(previous: ProjectStatus, next: ProjectStatus): boolean {
  return (previous === "active" || previous === "paused") && next === "complete";
}

/* ------------------------------------------------------------------ edits */

export interface ProjectValues {
  name: string;
  description: string;
  status: ProjectStatus;
  context_id: number | null;
  tag_ids: number[];
}

/* Only what changed goes to the server, like the old form's changed_data. */
export function changedFields(original: ProjectValues, next: ProjectValues): Partial<ProjectValues> {
  const patch: Partial<ProjectValues> = {};
  if (next.name !== original.name) patch.name = next.name;
  if (next.description !== original.description) patch.description = next.description;
  if (next.status !== original.status) patch.status = next.status;
  if (next.context_id !== original.context_id) patch.context_id = next.context_id;
  const before = [...original.tag_ids].sort((a, b) => a - b);
  const after = [...next.tag_ids].sort((a, b) => a - b);
  if (before.length !== after.length || before.some((id, index) => id !== after[index])) patch.tag_ids = next.tag_ids;
  return patch;
}
