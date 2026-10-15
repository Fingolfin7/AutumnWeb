import type { Project, Subproject, Tag } from "@/api/types";

/* The commitment form's scope rules. The old page got these as injected JSON
   (core.commitments.build_commitment_scope_meta); here the same lookup is
   derived from /projects/, each project's subprojects and /tags/. */

export type Aggregation = "context" | "tag" | "project" | "subproject";
export type Dimension = "tag" | "project" | "subproject";

export const AGGREGATIONS: { value: Aggregation; label: string }[] = [
  { value: "context", label: "Context" },
  { value: "tag", label: "Tag" },
  { value: "project", label: "Project" },
  { value: "subproject", label: "Subproject" },
];

export const aggregationLabel = (value: string) => AGGREGATIONS.find((a) => a.value === value)?.label ?? value;

/* Rules compose only from descendants of the scope: Context > Tag > Project >
   Subproject (CommitmentForm.clean). */
export const RULE_DIMENSIONS: Record<Aggregation, Dimension[]> = {
  context: ["tag", "project", "subproject"],
  tag: ["project", "subproject"],
  project: ["subproject"],
  subproject: [],
};

/* The pickers render in this order, each as an include then an exclude list. */
export const DIMENSION_ORDER: Dimension[] = ["project", "subproject", "tag"];

export interface ScopeProject {
  id: number;
  name: string;
  contextId: number | null;
  tagIds: number[];
}

export interface ScopeSubproject {
  id: number;
  name: string;
  projectId: number;
  projectName: string;
  contextId: number | null;
  tagIds: number[];
}

export interface ScopeTag {
  id: number;
  name: string;
  contextIds: number[];
}

export interface ScopeMeta {
  projects: Map<number, ScopeProject>;
  subprojects: Map<number, ScopeSubproject>;
  tags: Map<number, ScopeTag>;
}

export function buildScopeMeta(projects: Project[], subprojects: Subproject[], tags: Tag[]): ScopeMeta {
  const projectMap = new Map<number, ScopeProject>();
  const tagContexts = new Map<number, Set<number>>();
  for (const project of projects) {
    const tagIds = project.tags.map((tag) => tag.id);
    projectMap.set(project.id, { id: project.id, name: project.name, contextId: project.context?.id ?? null, tagIds });
    for (const tagId of tagIds) {
      const set = tagContexts.get(tagId) ?? new Set<number>();
      if (project.context) set.add(project.context.id);
      tagContexts.set(tagId, set);
    }
  }
  const subprojectMap = new Map<number, ScopeSubproject>();
  for (const sub of subprojects) {
    const parent = projectMap.get(sub.project_id);
    if (!parent) continue;
    subprojectMap.set(sub.id, {
      id: sub.id,
      name: sub.name,
      projectId: parent.id,
      projectName: parent.name,
      contextId: parent.contextId,
      tagIds: parent.tagIds,
    });
  }
  const tagMap = new Map<number, ScopeTag>();
  for (const tag of tags) {
    tagMap.set(tag.id, { id: tag.id, name: tag.name, contextIds: [...(tagContexts.get(tag.id) ?? [])].sort((a, b) => a - b) });
  }
  return { projects: projectMap, subprojects: subprojectMap, tags: tagMap };
}

/* Is this rule option inside the chosen scope target? With no target chosen
   yet everything is offered (isRuleOptionInScope in the old page script). */
export function isRuleOptionInScope(
  meta: ScopeMeta,
  dimension: Dimension,
  optionId: number,
  aggregation: Aggregation,
  scopeId: number | null,
): boolean {
  if (!scopeId) return true;
  if (aggregation === "context") {
    if (dimension === "tag") return meta.tags.get(optionId)?.contextIds.includes(scopeId) ?? false;
    if (dimension === "project") return meta.projects.get(optionId)?.contextId === scopeId;
    return meta.subprojects.get(optionId)?.contextId === scopeId;
  }
  if (aggregation === "tag") {
    if (dimension === "project") return meta.projects.get(optionId)?.tagIds.includes(scopeId) ?? false;
    if (dimension === "subproject") return meta.subprojects.get(optionId)?.tagIds.includes(scopeId) ?? false;
    return true;
  }
  if (aggregation === "project" && dimension === "subproject") return meta.subprojects.get(optionId)?.projectId === scopeId;
  return true;
}

export interface TargetOption {
  id: number;
  label: string;
}

/* The scope-target search box: an exact name wins, then a unique prefix, then
   a unique substring (commitScopeSearchToSelect in the old page script). */
export function resolveTarget(text: string, options: TargetOption[]): TargetOption | null {
  const query = text.trim().toLowerCase();
  if (!query) return null;
  const exact = options.find((option) => option.label.toLowerCase() === query);
  if (exact) return exact;
  const starts = options.filter((option) => option.label.toLowerCase().startsWith(query));
  if (starts.length === 1) return starts[0]!;
  const contains = options.filter((option) => option.label.toLowerCase().includes(query));
  return contains.length === 1 ? contains[0]! : null;
}

export function targetOptions(aggregation: Aggregation, meta: ScopeMeta, contexts: { id: number; name: string }[]): TargetOption[] {
  const byLabel = (a: TargetOption, b: TargetOption) => a.label.localeCompare(b.label);
  switch (aggregation) {
    case "context":
      return contexts.map((c) => ({ id: c.id, label: c.name })).sort(byLabel);
    case "tag":
      return [...meta.tags.values()].map((t) => ({ id: t.id, label: t.name })).sort(byLabel);
    case "project":
      return [...meta.projects.values()].map((p) => ({ id: p.id, label: p.name })).sort(byLabel);
    default:
      return [...meta.subprojects.values()].map((s) => ({ id: s.id, label: `${s.name} (${s.projectName})` })).sort(byLabel);
  }
}
