import type { Commitment } from "@/api/types";

export function needsSubprojects(commitments: Commitment[]): boolean {
  return commitments.some(
    (c) =>
      c.aggregation_type === "subproject" ||
      c.filters.include_subproject_ids.length > 0 ||
      c.filters.exclude_subproject_ids.length > 0,
  );
}

export type EntityKind = "context" | "tag" | "project" | "subproject";

/* Which commitments reach an item is the server's call
   (GET /commitments/?applies_to=kind:id, the same rules the old pages used);
   this only orders them for display: active first, then by scope kind, with
   the server's (id) order breaking ties. */
export function sortCommitments(commitments: Commitment[]): Commitment[] {
  return commitments
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
