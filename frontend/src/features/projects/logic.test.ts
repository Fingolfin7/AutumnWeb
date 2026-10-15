import type { Commitment, Project } from "@/api/types";
import {
  changedFields,
  commitmentRuleLines,
  describeFilters,
  emptyFilters,
  formatSigned,
  groupByStatus,
  onlyIncluded,
  readFilters,
  relatedOnly,
  serverQuery,
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

  it("sends what the API can filter and order, with the header context as the default", () => {
    const filters = { ...emptyFilters, search: "a", tags: [2], projects: [9], projectMode: "include" as const };
    expect(serverQuery(filters, "3")).toEqual({ ordering: "last_activity", search: "a", context_ids: "3", tag_ids: "2" });
    expect(serverQuery({ ...filters, context: "all" }, "3").context_ids).toBeUndefined();
    expect(serverQuery({ ...filters, context: "8", projectMode: "exclude" }, "3")).toMatchObject({
      context_ids: "8",
      exclude_project_ids: "9",
    });
  });

  it("passes the date range to the API, either end alone", () => {
    expect(serverQuery({ ...emptyFilters, start_date: "2026-10-05", end_date: "2026-10-10" }, undefined)).toEqual({
      ordering: "last_activity",
      start_date: "2026-10-05",
      end_date: "2026-10-10",
    });
    expect(serverQuery({ ...emptyFilters, end_date: "2026-10-10" }, undefined).end_date).toBe("2026-10-10");
    expect(serverQuery(emptyFilters, undefined).start_date).toBeUndefined();
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

  it("keeps only the included projects", () => {
    expect(onlyIncluded(list, { ...emptyFilters, projects: [3], projectMode: "include" }).map((p) => p.id)).toEqual([3]);
    expect(onlyIncluded(list, { ...emptyFilters, projects: [3], projectMode: "exclude" })).toHaveLength(3);
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

describe("commitment display", () => {
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

});
