import { describe, expect, it } from "vitest";
import type { Commitment, Project, Subproject, Tag } from "@/api/types";
import {
  classifyChanges,
  createPayload,
  definitionPayload,
  newState,
  normalize,
  overlappingRules,
  patchPayload,
  pruneRules,
  stateFromCommitment,
  validateForm,
  type FormState,
} from "./formModel";
import { buildScopeMeta, isRuleOptionInScope, resolveTarget, targetOptions } from "./scope";
import { ruleLines, sortCommitments } from "./applies";
import { progressOf } from "./display";

const project = (id: number, name: string, contextId: number | null, tagIds: number[]): Project =>
  ({
    id,
    name,
    status: "active",
    description: "",
    context: contextId ? { id: contextId, name: `ctx${contextId}` } : null,
    tags: tagIds.map((t) => ({ id: t, name: `tag${t}` })),
    start_date: "2026-01-01",
    last_activity: null,
    total_minutes: 0,
    session_count: 0,
  }) as Project;

const projects = [project(1, "Alpha", 10, [100]), project(2, "Beta", 10, [101]), project(3, "Gamma", 11, [100, 101])];
const subprojects = [
  { id: 20, name: "Part", project_id: 1 },
  { id: 21, name: "Part", project_id: 3 },
] as Subproject[];
const tags = [
  { id: 100, name: "deep" },
  { id: 101, name: "light" },
] as Tag[];
const meta = buildScopeMeta(projects, subprojects, tags);

const filters = (over: Partial<Commitment["filters"]> = {}): Commitment["filters"] => ({
  include_project_ids: [],
  exclude_project_ids: [],
  include_subproject_ids: [],
  exclude_subproject_ids: [],
  include_context_ids: [],
  exclude_context_ids: [],
  include_tag_ids: [],
  exclude_tag_ids: [],
  ...over,
});

const commitment = (over: Partial<Commitment> = {}): Commitment =>
  ({
    id: 5,
    version: 3,
    active: true,
    aggregation_type: "project",
    target: { kind: "project", id: 1, name: "Alpha" },
    commitment_type: "time",
    period: "weekly",
    start_date: "2026-09-16",
    timezone: "UTC",
    generation: 1,
    target_value: 180,
    banking_enabled: true,
    max_balance: 360,
    min_balance: -240,
    balance: 0,
    current_surplus: 0,
    filters: filters(),
    pending_revision: null,
    ...over,
  }) as Commitment;

const ctx = { nameOf: (_d: string, id: number) => `n${id}`, mode: "create" as const };

describe("scope meta", () => {
  it("allows only descendants of a context", () => {
    expect(isRuleOptionInScope(meta, "project", 1, "context", 10)).toBe(true);
    expect(isRuleOptionInScope(meta, "project", 3, "context", 10)).toBe(false);
    expect(isRuleOptionInScope(meta, "tag", 100, "context", 10)).toBe(true);
    expect(isRuleOptionInScope(meta, "tag", 100, "context", 11)).toBe(true);
    expect(isRuleOptionInScope(meta, "tag", 101, "context", 12)).toBe(false);
    expect(isRuleOptionInScope(meta, "subproject", 21, "context", 10)).toBe(false);
  });

  it("filters by tag and by parent project", () => {
    expect(isRuleOptionInScope(meta, "project", 2, "tag", 100)).toBe(false);
    expect(isRuleOptionInScope(meta, "project", 3, "tag", 100)).toBe(true);
    expect(isRuleOptionInScope(meta, "subproject", 21, "project", 3)).toBe(true);
    expect(isRuleOptionInScope(meta, "subproject", 20, "project", 3)).toBe(false);
  });

  it("offers everything until a target is chosen", () => {
    expect(isRuleOptionInScope(meta, "project", 3, "context", null)).toBe(true);
  });

  it("labels subproject targets with their project", () => {
    const options = targetOptions("subproject", meta, []);
    expect(options.map((o) => o.label)).toEqual(["Part (Alpha)", "Part (Gamma)"]);
  });
});

describe("resolveTarget", () => {
  const options = [
    { id: 1, label: "Autumn Polish" },
    { id: 2, label: "Autumn" },
    { id: 3, label: "Czech" },
  ];
  it("prefers an exact match, then a unique prefix, then a unique substring", () => {
    expect(resolveTarget("autumn", options)?.id).toBe(2);
    expect(resolveTarget("cz", options)?.id).toBe(3);
    expect(resolveTarget("pol", options)?.id).toBe(1);
  });
  it("gives up when ambiguous or empty", () => {
    expect(resolveTarget("aut", options)).toBeNull();
    expect(resolveTarget("  ", options)).toBeNull();
    expect(resolveTarget("zzz", options)).toBeNull();
  });
});

describe("rules follow the scope", () => {
  it("clears rule dimensions the scope cannot compose from", () => {
    const state: FormState = {
      ...newState(),
      aggregation: "project",
      rules: { ...newState().rules, include_project_ids: [1], include_subproject_ids: [20], include_tag_ids: [100] },
    };
    const clean = normalize(state);
    expect(clean.rules.include_project_ids).toEqual([]);
    expect(clean.rules.include_tag_ids).toEqual([]);
    expect(clean.rules.include_subproject_ids).toEqual([20]);
    expect(normalize({ ...state, aggregation: "subproject" }).rules.include_subproject_ids).toEqual([]);
  });

  it("drops choices outside a newly chosen scope target", () => {
    const state: FormState = {
      ...newState(),
      aggregation: "context",
      targetId: 10,
      rules: { ...newState().rules, include_project_ids: [1, 3], exclude_tag_ids: [100, 101] },
    };
    const pruned = pruneRules(state, meta);
    expect(pruned.rules.include_project_ids).toEqual([1]);
    expect(pruned.rules.exclude_tag_ids).toEqual([100, 101]);
  });

  it("reports include/exclude overlap by name", () => {
    const state = { ...newState(), aggregation: "context" as const, rules: { ...newState().rules, include_project_ids: [1, 2], exclude_project_ids: [2, 1] } };
    expect(overlappingRules(state, (_d, id) => `P${id}`)).toEqual(["Cannot both include and exclude the same projects: P1, P2."]);
  });
});

describe("validateForm", () => {
  const good: FormState = { ...newState(), aggregation: "project", targetId: 1, targetText: "Alpha", target: "120" };

  it("accepts a complete form", () => {
    expect(validateForm(good, ctx).fields).toEqual({});
  });

  it("needs a scope target and says what it could not match", () => {
    expect(validateForm({ ...good, targetId: null, targetText: "" }, ctx).fields.scope?.[0]).toMatch(/select a target/);
    expect(validateForm({ ...good, targetId: null, targetText: "zz" }, ctx).fields.scope?.[0]).toMatch(/No project matches/);
  });

  it("refuses a target that already has a commitment", () => {
    const errors = validateForm(good, { ...ctx, existingFor: () => commitment() });
    expect(errors.fields.scope).toEqual(["This project already has a commitment."]);
  });

  it("checks the target amount", () => {
    expect(validateForm({ ...good, target: "" }, ctx).fields.target).toEqual(["This field is required."]);
    expect(validateForm({ ...good, target: "0" }, ctx).fields.target?.[0]).toMatch(/at least|greater than or equal to 1/);
    expect(validateForm({ ...good, target: "1.5" }, ctx).fields.target).toEqual(["Enter a whole number."]);
  });

  it("keeps the caps in order and signed", () => {
    expect(validateForm({ ...good, minBalance: "5" }, ctx).fields.min_balance).toContain("Min balance must be zero or negative.");
    expect(validateForm({ ...good, maxBalance: "-1" }, ctx).fields.max_balance?.[0]).toMatch(/greater than or equal to 0/);
    expect(validateForm({ ...good, maxBalance: "0", minBalance: "-0" }, ctx).fields.min_balance).toBeUndefined();
    expect(validateForm({ ...good, maxBalance: "", minBalance: "" }, ctx).fields.max_balance).toEqual(["This field is required."]);
  });

  it("flags contradictory rules as a form-level error", () => {
    const state = { ...good, rules: { ...good.rules, include_subproject_ids: [20], exclude_subproject_ids: [20] } };
    expect(validateForm(state, ctx).general[0]).toMatch(/Cannot both include and exclude the same subprojects/);
  });
});

describe("request building", () => {
  it("builds a create body with only the chosen target id and non-empty rules", () => {
    const state: FormState = {
      ...newState(),
      aggregation: "context",
      targetId: 10,
      target: "300",
      startDate: "2026-10-01",
      rules: { ...newState().rules, exclude_project_ids: [2], include_tag_ids: [] },
    };
    const body = createPayload(state);
    expect(body).toMatchObject({
      aggregation_type: "context",
      context_id: 10,
      target_value: 300,
      commitment_type: "time",
      period: "weekly",
      start_date: "2026-10-01",
      banking_enabled: true,
      max_balance: 600,
      min_balance: -600,
      exclude_project_ids: [2],
    });
    expect(body).not.toHaveProperty("project_id");
    expect(body).not.toHaveProperty("include_tag_ids");
  });

  it("omits the start date when blank so the server uses today in the profile zone", () => {
    expect(createPayload({ ...newState(), aggregation: "tag", targetId: 100, target: "5" })).not.toHaveProperty("start_date");
  });

  it("sends the whole definition on a restart", () => {
    const next = { ...stateFromCommitment(commitment(), "Alpha"), period: "monthly" as const };
    const body = definitionPayload(next);
    expect(body).toMatchObject({ aggregation_type: "project", project_id: 1, period: "monthly", target_value: 180, active: true });
    expect(body.include_subproject_ids).toEqual([]);
  });
});

describe("edit policy", () => {
  const base = stateFromCommitment(commitment(), "Alpha");

  it("sees no change in an untouched form", () => {
    expect(classifyChanges(base, base)).toEqual({ restart: [], nextPeriod: [], immediate: [] });
    expect(patchPayload(base, base)).toEqual({});
  });

  it("queues target, caps, banking and rules for the next period", () => {
    const next: FormState = {
      ...base,
      target: "240",
      maxBalance: "500",
      banking: false,
      rules: { ...base.rules, exclude_subproject_ids: [20] },
    };
    expect(classifyChanges(base, next).nextPeriod).toEqual(["Target", "Time banking", "Surplus cap", "Rules"]);
    expect(patchPayload(base, next)).toEqual({
      target_value: 240,
      banking_enabled: false,
      max_balance: 500,
      exclude_subproject_ids: [20],
    });
  });

  it("requires a restart for scope, measure, period, start date and reactivation", () => {
    expect(classifyChanges(base, { ...base, aggregation: "tag" }).restart).toEqual(["Applies to", "Scope target"]);
    expect(classifyChanges(base, { ...base, targetId: 2 }).restart).toEqual(["Scope target"]);
    expect(classifyChanges(base, { ...base, commitmentType: "sessions" }).restart).toEqual(["Measure"]);
    expect(classifyChanges(base, { ...base, period: "daily" }).restart).toEqual(["Period"]);
    expect(classifyChanges(base, { ...base, startDate: "2026-10-01" }).restart).toEqual(["Start date"]);
    const paused = { ...base, active: false };
    expect(classifyChanges(paused, { ...paused, active: true }).restart).toEqual(["Reactivating"]);
  });

  it("applies a pause immediately", () => {
    const changes = classifyChanges(base, { ...base, active: false });
    expect(changes.immediate).toEqual(["Paused"]);
    expect(patchPayload(base, { ...base, active: false })).toEqual({ active: false });
  });

  it("ignores a blank start date instead of reading it as a change", () => {
    expect(classifyChanges(base, { ...base, startDate: "" }).restart).toEqual([]);
  });

  it("starts from queued values so an edit builds on them", () => {
    const queued = commitment({
      pending_revision: {
        effective_from: "2026-10-19T00:00:00Z",
        changes: { target_value: 240, exclude_project_ids: [] },
      },
    });
    const state = stateFromCommitment(queued, "Alpha");
    expect(state.target).toBe("240");
    expect(state.banking).toBe(true);
  });
});

describe("related commitments", () => {
  it("lists active commitments first, then by scope, keeping the server order within a scope", () => {
    const paused = commitment({ id: 1, active: false, aggregation_type: "project" });
    const tag = commitment({ id: 2, aggregation_type: "tag", target: { kind: "tag", id: 100, name: "deep" } });
    const projectB = commitment({ id: 4, aggregation_type: "project" });
    const projectA = commitment({ id: 3, aggregation_type: "project" });
    expect(sortCommitments([paused, tag, projectB, projectA]).map((c) => c.id)).toEqual([4, 3, 2, 1]);
  });

  it("takes the unbanked surplus from the server instead of deriving it", () => {
    const period = { start: "2026-10-12T00:00:00Z", end: "2026-10-19T00:00:00Z", accrued: 100, target: 180, met: false, percentage: 55.6, status: "behind" };
    expect(progressOf(commitment({ current_period: period, current_surplus: -80 })).surplus).toBe(-80);
    expect(progressOf(commitment({ current_period: period, current_surplus: -12.5 })).surplus).toBe(-12.5);
  });

  it("writes rule lines the way the server does", () => {
    const names = {
      tags: new Map([[100, "deep"]]),
      projects: new Map([[2, "Beta"]]),
      subprojects: new Map<number, string>(),
      contexts: new Map<number, string>(),
    };
    const lines = ruleLines(commitment({ filters: filters({ include_tag_ids: [100], exclude_project_ids: [2, 9] }) }), names);
    expect(lines).toEqual(["Include Tags: deep", "Exclude Projects: Beta, #9"]);
  });
});
