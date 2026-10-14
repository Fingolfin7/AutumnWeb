import type { Commitment, Project, Subproject } from "@/api/types";

/* Which commitments a context/tag/project/subproject page lists. Mirrors
   core.commitments.commitment_applies_to_* so the panel shows the same set
   the Django page did, but over data the client already has. */

export interface AppliesData {
  projects: Project[];
  /** subproject id -> parent project id; only needed when a rule or target names subprojects. */
  subprojectParents: Map<number, number>;
}

export function needsSubprojects(commitments: Commitment[]): boolean {
  return commitments.some(
    (c) =>
      c.aggregation_type === "subproject" ||
      c.filters.include_subproject_ids.length > 0 ||
      c.filters.exclude_subproject_ids.length > 0,
  );
}

export function subprojectParentMap(subprojects: Subproject[]): Map<number, number> {
  return new Map(subprojects.map((sub) => [sub.id, sub.project_id]));
}

export function commitmentAppliesToProject(c: Commitment, project: Project, data: AppliesData): boolean {
  const projectTagIds = project.tags.map((tag) => tag.id);
  switch (c.aggregation_type) {
    case "context":
      if (c.target.id !== project.context?.id) return false;
      break;
    case "tag":
      if (!projectTagIds.includes(c.target.id)) return false;
      break;
    case "project":
      if (c.target.id !== project.id) return false;
      break;
    case "subproject":
      return data.subprojectParents.get(c.target.id) === project.id;
    default:
      return false;
  }
  const f = c.filters;
  if (f.include_tag_ids.length && !f.include_tag_ids.some((id) => projectTagIds.includes(id))) return false;
  if (f.exclude_tag_ids.length && f.exclude_tag_ids.some((id) => projectTagIds.includes(id))) return false;
  if (f.include_project_ids.length && !f.include_project_ids.includes(project.id)) return false;
  if (f.exclude_project_ids.includes(project.id)) return false;
  if (f.include_subproject_ids.length && !f.include_subproject_ids.some((id) => data.subprojectParents.get(id) === project.id)) {
    return false;
  }
  return true;
}

export function commitmentAppliesToSubproject(c: Commitment, subproject: Subproject, data: AppliesData): boolean {
  const project = data.projects.find((p) => p.id === subproject.project_id);
  if (!project) return false;
  const projectTagIds = project.tags.map((tag) => tag.id);
  switch (c.aggregation_type) {
    case "context":
      if (c.target.id !== project.context?.id) return false;
      break;
    case "tag":
      if (!projectTagIds.includes(c.target.id)) return false;
      break;
    case "project":
      if (c.target.id !== project.id) return false;
      break;
    case "subproject":
      if (c.target.id !== subproject.id) return false;
      break;
    default:
      return false;
  }
  const f = c.filters;
  if (f.include_tag_ids.length && !f.include_tag_ids.some((id) => projectTagIds.includes(id))) return false;
  if (f.exclude_tag_ids.length && f.exclude_tag_ids.some((id) => projectTagIds.includes(id))) return false;
  if (f.include_project_ids.length && !f.include_project_ids.includes(project.id)) return false;
  if (f.exclude_project_ids.includes(project.id)) return false;
  if (f.include_subproject_ids.length && !f.include_subproject_ids.includes(subproject.id)) return false;
  if (f.exclude_subproject_ids.includes(subproject.id)) return false;
  return true;
}

export type EntityKind = "context" | "tag" | "project" | "subproject";

export function commitmentsFor(
  kind: EntityKind,
  id: number,
  commitments: Commitment[],
  data: AppliesData,
  subproject?: Subproject,
): Commitment[] {
  const matches = commitments.filter((c) => {
    if (kind === "subproject") return subproject ? commitmentAppliesToSubproject(c, subproject, data) : false;
    const candidates =
      kind === "context"
        ? data.projects.filter((p) => p.context?.id === id)
        : kind === "tag"
          ? data.projects.filter((p) => p.tags.some((t) => t.id === id))
          : data.projects.filter((p) => p.id === id);
    return candidates.some((project) => commitmentAppliesToProject(c, project, data));
  });
  /* Active first, then by scope kind; the server list order (id) breaks ties. */
  return matches
    .map((c, index) => ({ c, index }))
    .sort(
      (a, b) =>
        Number(b.c.active) - Number(a.c.active) ||
        a.c.aggregation_type.localeCompare(b.c.aggregation_type) ||
        a.index - b.index,
    )
    .map(({ c }) => c);
}

export interface RuleLookup {
  tags: Map<number, string>;
  projects: Map<number, string>;
  subprojects: Map<number, string>;
  contexts: Map<number, string>;
}

/* "Include Tags: a, b" lines, in the order the server composes them. */
export function ruleLines(c: Commitment, names: RuleLookup): string[] {
  const f = c.filters;
  const name = (map: Map<number, string>, id: number) => map.get(id) ?? `#${id}`;
  const groups: [string, number[], number[], Map<number, string>][] = [
    ["Tags", f.include_tag_ids, f.exclude_tag_ids, names.tags],
    ["Projects", f.include_project_ids, f.exclude_project_ids, names.projects],
    ["Subprojects", f.include_subproject_ids, f.exclude_subproject_ids, names.subprojects],
    ["Contexts", f.include_context_ids, f.exclude_context_ids, names.contexts],
  ];
  const lines: string[] = [];
  for (const [label, include, exclude, map] of groups) {
    if (include.length) lines.push(`Include ${label}: ${include.map((id) => name(map, id)).join(", ")}`);
    if (exclude.length) lines.push(`Exclude ${label}: ${exclude.map((id) => name(map, id)).join(", ")}`);
  }
  return lines;
}
