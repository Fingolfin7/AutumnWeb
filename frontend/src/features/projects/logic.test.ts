import type { Commitment, Project } from "@/api/types";
import {
  applyClientFilters,
  changedFields,
  commitmentAppliesToProject,
  commitmentAppliesToSubproject,
  commitmentRuleLines,
  completionMessage,
  describeFilters,
  emptyFilters,
  formatSigned,
  groupByStatus,
  isCompletionTransition,
  readFilters,
  relatedOnly,
  serverQuery,
  sortByActivity,
  sortCommitments,
  writeFilters,
  type NameLookup,
} from "./logic";

const project = (over: Partial<Project> & { id: number }): Project => ({
  name: `P${over.id}`,
  status: "active",
  description: "",
  context: null,
  tags: [],
  start_date: "2026-10-01",
  last_activity: null,
  total_minutes: 0,
  session_count: 0,
  ...over,
});

const noFilters = {
  include_project_ids: [],
  exclude_project_ids: [],
  include_subproject_ids: [],
  exclude_subproject_ids: [],
  include_context_ids: [],
  exclude_context_ids: [],
  include_tag_ids: [],
  exclude_tag_ids: [],
};

const commitment = (over: Partial<Commitment> & { id: number }): Commitment =>
  ({
    active: true,
    aggregation_type: "project",
    target: { kind: "project", id: 1, name: "P1" },
    filters: noFilters,
    ...over,
  }) as Commitment;

describe("filters <-> URL", () => {
  it("round-trips every filter, keeping the old parameter names", () => {
    const state = {
      ...emptyFilters,
      search: "czech",
      start_date: "2026-10-01",
      end_date: "2026-10-31",
      context: "5",
      tags: [1, 2],
      projects: [7],
      projectMode: "include" as const,
    };
    const params = writeFilters(state);
    expect(params.get("include_projects")).toBe("7");
    expect(params.get("tags")).toBe("1,2");
    expect(readFilters(params)).toEqual(state);
  });

  it("reads repeated and comma-separated ids and falls back to exclude mode", () => {
    const state = readFilters(new URLSearchParams("tags=1&tags=2,3&exclude_projects=4&tags=x"));
    expect(state.tags).toEqual([1, 2, 3]);
    expect(state.projects).toEqual([4]);
    expect(state.projectMode).toBe("exclude");
  });

  it("sends only what the API can filter, with the header context as the default", () => {
    const filters = { ...emptyFilters, search: "a", tags: [2], projects: [9], projectMode: "include" as const };
    expect(serverQuery(filters, "3")).toEqual({ search: "a", context_ids: "3", tag_ids: "2" });
    expect(serverQuery({ ...filters, context: "all" }, "3").context_ids).toBeUndefined();
    expect(serverQuery({ ...filters, context: "8", projectMode: "exclude" }, "3")).toMatchObject({
      context_ids: "8",
      exclude_project_ids: "9",
    });
  });

  it("describes the applied filters as pills with names", () => {
    const pills = describeFilters(
      { ...emptyFilters, search: "x", context: "all", tags: [1], projects: [2] },
      { projects: [{ id: 2, name: "Gym" }], tags: [{ id: 1, name: "fitness" }], contexts: [] },
    );
    expect(pills).toEqual([
      { label: "Search", value: "x" },
      { label: "Context", value: "All" },
      { label: "Tags", value: "fitness" },
      { label: "Excluding", value: "Gym" },
    ]);
  });
});

describe("list shaping", () => {
  const list = [
    project({ id: 1, start_date: "2026-10-01" }),
    project({ id: 2, start_date: "2026-10-10" }),
    project({ id: 3, start_date: "2026-10-20" }),
  ];

  it("narrows by creation date range (end inclusive, only with a start)", () => {
    expect(applyClientFilters(list, { ...emptyFilters, start_date: "2026-10-05" }).map((p) => p.id)).toEqual([2, 3]);
    expect(applyClientFilters(list, { ...emptyFilters, start_date: "2026-10-05", end_date: "2026-10-10" }).map((p) => p.id)).toEqual([2]);
    expect(applyClientFilters(list, { ...emptyFilters, end_date: "2026-10-05" })).toHaveLength(3);
  });

  it("keeps only the included projects", () => {
    expect(applyClientFilters(list, { ...emptyFilters, projects: [3], projectMode: "include" }).map((p) => p.id)).toEqual([3]);
    expect(applyClientFilters(list, { ...emptyFilters, projects: [3], projectMode: "exclude" })).toHaveLength(3);
  });

  it("sorts by latest activity, falling back to the start date", () => {
    const sorted = sortByActivity([
      project({ id: 1, last_activity: "2026-10-12" }),
      project({ id: 2, last_activity: null, start_date: "2026-10-14" }),
      project({ id: 3, last_activity: "2026-10-12", name: "A" }),
    ]);
    expect(sorted.map((p) => p.id)).toEqual([2, 3, 1]);
  });

  it("groups by status in display order and drops empty groups", () => {
    const groups = groupByStatus([project({ id: 1, status: "archived" }), project({ id: 2 }), project({ id: 3, status: "paused" })]);
    expect(groups.map((g) => g.status)).toEqual(["active", "paused", "archived"]);
  });

  it("derives related matches as the extra rows of the related query", () => {
    const direct = [project({ id: 1 })];
    expect(relatedOnly([project({ id: 1 }), project({ id: 4 })], direct).map((p) => p.id)).toEqual([4]);
    expect(relatedOnly(direct, direct)).toEqual([]);
  });
});

describe("commitments for a project", () => {
  const scope = { id: 1, contextId: 5, tagIds: [10], subprojectIds: [20, 21] };

  it("matches by target scope", () => {
    expect(commitmentAppliesToProject(commitment({ id: 1 }), scope)).toBe(true);
    expect(commitmentAppliesToProject(commitment({ id: 1, target: { kind: "project", id: 2, name: "x" } }), scope)).toBe(false);
    expect(
      commitmentAppliesToProject(commitment({ id: 1, aggregation_type: "context", target: { kind: "context", id: 5, name: "c" } }), scope),
    ).toBe(true);
    expect(
      commitmentAppliesToProject(commitment({ id: 1, aggregation_type: "tag", target: { kind: "tag", id: 11, name: "t" } }), scope),
    ).toBe(false);
    expect(
      commitmentAppliesToProject(commitment({ id: 1, aggregation_type: "subproject", target: { kind: "subproject", id: 21, name: "s" } }), scope),
    ).toBe(true);
  });

  it("honours include and exclude rules", () => {
    const tagScoped = commitment({ id: 1, aggregation_type: "context", target: { kind: "context", id: 5, name: "c" } });
    expect(commitmentAppliesToProject({ ...tagScoped, filters: { ...noFilters, exclude_tag_ids: [10] } }, scope)).toBe(false);
    expect(commitmentAppliesToProject({ ...tagScoped, filters: { ...noFilters, include_tag_ids: [99] } }, scope)).toBe(false);
    expect(commitmentAppliesToProject({ ...tagScoped, filters: { ...noFilters, exclude_project_ids: [1] } }, scope)).toBe(false);
    expect(commitmentAppliesToProject({ ...tagScoped, filters: { ...noFilters, include_subproject_ids: [21] } }, scope)).toBe(true);
    expect(commitmentAppliesToProject({ ...tagScoped, filters: { ...noFilters, include_subproject_ids: [77] } }, scope)).toBe(false);
  });

  it("matches a subproject only for its own or its project's scope", () => {
    expect(commitmentAppliesToSubproject(commitment({ id: 1 }), scope, 20)).toBe(true);
    const own = commitment({ id: 2, aggregation_type: "subproject", target: { kind: "subproject", id: 20, name: "s" } });
    expect(commitmentAppliesToSubproject(own, scope, 20)).toBe(true);
    expect(commitmentAppliesToSubproject(own, scope, 21)).toBe(false);
    expect(commitmentAppliesToSubproject({ ...commitment({ id: 3 }), filters: { ...noFilters, exclude_subproject_ids: [20] } }, scope, 20)).toBe(false);
  });

  it("orders active first, then scope, then id", () => {
    const sorted = sortCommitments([
      commitment({ id: 3, active: false }),
      commitment({ id: 2, aggregation_type: "tag" }),
      commitment({ id: 1, aggregation_type: "project" }),
    ]);
    expect(sorted.map((c) => c.id)).toEqual([1, 2, 3]);
  });

  it("writes rule lines in the old order with a fallback for unknown names", () => {
    const names: NameLookup = {
      tags: new Map([[1, "deep-work"]]),
      projects: new Map(),
      subprojects: new Map(),
      contexts: new Map([[2, "Craft"]]),
    };
    const lines = commitmentRuleLines(
      commitment({ id: 1, filters: { ...noFilters, include_tag_ids: [1], exclude_project_ids: [8], exclude_context_ids: [2] } }),
      names,
    );
    expect(lines).toEqual(["Include Tags: deep-work", "Exclude Projects: Project #8", "Exclude Contexts: Craft"]);
    expect(commitmentRuleLines(commitment({ id: 1 }), names)).toEqual([]);
  });

  it("signs bank figures", () => {
    expect(formatSigned(-180, true)).toBe("-180m");
    expect(formatSigned(2.5, true)).toBe("+2.5m");
    expect(formatSigned(0, false)).toBe("+0");
  });
});

describe("editing", () => {
  const original = { name: "A", description: "d", status: "active" as const, context_id: 1, tag_ids: [2, 1] };

  it("patches only what changed and treats tag order as irrelevant", () => {
    expect(changedFields(original, { ...original, tag_ids: [1, 2] })).toEqual({});
    expect(changedFields(original, { ...original, name: "B", tag_ids: [1] })).toEqual({ name: "B", tag_ids: [1] });
    expect(changedFields(original, { ...original, context_id: null })).toEqual({ context_id: null });
  });

  it("celebrates only a live project becoming complete", () => {
    expect(isCompletionTransition("active", "complete")).toBe(true);
    expect(isCompletionTransition("paused", "complete")).toBe(true);
    expect(isCompletionTransition("archived", "complete")).toBe(false);
    expect(isCompletionTransition("complete", "complete")).toBe(false);
  });

  it("words the completion message like the old page", () => {
    expect(completionMessage(200, 4)).toBe("Project complete — 3h 20m tracked across 4 sessions.");
    expect(completionMessage(60, 1)).toBe("Project complete — 1h tracked across 1 session.");
    expect(completionMessage(0, 0)).toBe("Project complete — no sessions logged yet.");
  });
});
