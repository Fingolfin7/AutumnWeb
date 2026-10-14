import type { Commitment, CommitmentChanges, CommitmentCreate } from "@/api/types";
import { NO_ERRORS, type FormErrors } from "@/features/contexts-tags/formErrors";
import { RULE_DIMENSIONS, isRuleOptionInScope, type Aggregation, type Dimension, type ScopeMeta } from "./scope";

/* The commitment form's state, validation and request building, kept free of
   React so the dependent-field rules (which rules a scope allows, what an edit
   changes now, next period or only through a restart) can be tested. */

export type CommitmentType = "time" | "sessions";
export type Period = "daily" | "weekly" | "fortnightly" | "monthly" | "quarterly" | "yearly";

export const PERIODS: { value: Period; label: string }[] = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "fortnightly", label: "Fortnightly" },
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly" },
  { value: "yearly", label: "Yearly" },
];

export const MEASURES: { value: CommitmentType; label: string }[] = [
  { value: "time", label: "Time-based" },
  { value: "sessions", label: "Session-based" },
];

export const periodLabel = (value: string) => PERIODS.find((p) => p.value === value)?.label ?? value;
export const measureLabel = (value: string) => MEASURES.find((m) => m.value === value)?.label ?? value;

export const RULE_FIELDS = [
  "include_project_ids",
  "exclude_project_ids",
  "include_subproject_ids",
  "exclude_subproject_ids",
  "include_tag_ids",
  "exclude_tag_ids",
] as const;
export type RuleField = (typeof RULE_FIELDS)[number];

export const ruleField = (mode: "include" | "exclude", dimension: Dimension): RuleField =>
  `${mode}_${dimension}_ids` as RuleField;

export interface FormState {
  aggregation: Aggregation;
  targetId: number | null;
  /** What the scope-target search box shows. */
  targetText: string;
  rules: Record<RuleField, number[]>;
  commitmentType: CommitmentType;
  period: Period;
  startDate: string;
  target: string;
  banking: boolean;
  maxBalance: string;
  minBalance: string;
  active: boolean;
}

export const emptyRules = (): Record<RuleField, number[]> => ({
  include_project_ids: [],
  exclude_project_ids: [],
  include_subproject_ids: [],
  exclude_subproject_ids: [],
  include_tag_ids: [],
  exclude_tag_ids: [],
});

/** Defaults of a new commitment (the model's: weekly, time, 600 / -600 caps). */
export function newState(): FormState {
  return {
    aggregation: "context",
    targetId: null,
    targetText: "",
    rules: emptyRules(),
    commitmentType: "time",
    period: "weekly",
    startDate: "",
    target: "",
    banking: true,
    maxBalance: "600",
    minBalance: "-600",
    active: true,
  };
}

/* The state an existing commitment edits from. A queued (pending) revision is
   folded in so the form shows what will be true from the next period and an
   edit builds on it rather than silently contradicting it. */
export function stateFromCommitment(c: Commitment, targetLabel: string): FormState {
  const pending = (c.pending_revision?.changes ?? {}) as Record<string, unknown>;
  const rules = emptyRules();
  for (const field of RULE_FIELDS) {
    const queued = pending[field];
    rules[field] = Array.isArray(queued) ? (queued as number[]) : [...c.filters[field]];
  }
  const num = (key: string, live: number) => String(typeof pending[key] === "number" ? (pending[key] as number) : live);
  return normalize({
    aggregation: c.aggregation_type,
    targetId: c.target.id,
    targetText: targetLabel,
    rules,
    commitmentType: c.commitment_type,
    period: c.period,
    startDate: c.start_date,
    target: num("target_value", c.target_value),
    banking: typeof pending.banking_enabled === "boolean" ? pending.banking_enabled : c.banking_enabled,
    maxBalance: num("max_balance", c.max_balance),
    minBalance: num("min_balance", c.min_balance),
    active: c.active,
  });
}

/** Rule lists of dimensions the scope cannot compose from are always empty. */
export function normalize(state: FormState): FormState {
  const allowed = new Set<Dimension>(RULE_DIMENSIONS[state.aggregation]);
  const rules = emptyRules();
  for (const field of RULE_FIELDS) {
    const dimension = field.split("_")[1] as Dimension;
    rules[field] = allowed.has(dimension) ? [...state.rules[field]] : [];
  }
  return { ...state, rules };
}

/* Changing the scope or its target drops rule choices that fall outside it
   (applyScopeFilterToRules: they were unticked and hidden). */
export function pruneRules(state: FormState, meta: ScopeMeta): FormState {
  const next = normalize(state);
  for (const field of RULE_FIELDS) {
    const dimension = field.split("_")[1] as Dimension;
    next.rules[field] = next.rules[field].filter((id) => isRuleOptionInScope(meta, dimension, id, next.aggregation, next.targetId));
  }
  return next;
}

/* Overlap between an include and an exclude list of one dimension. */
export function overlappingRules(state: FormState, nameOf: (dimension: Dimension, id: number) => string): string[] {
  const messages: string[] = [];
  const labels: Record<Dimension, string> = { project: "projects", subproject: "subprojects", tag: "tags" };
  for (const dimension of ["project", "subproject", "tag"] as Dimension[]) {
    const include = state.rules[ruleField("include", dimension)];
    const exclude = new Set(state.rules[ruleField("exclude", dimension)]);
    const both = include.filter((id) => exclude.has(id));
    if (both.length) {
      const names = both.map((id) => nameOf(dimension, id)).sort();
      messages.push(`Cannot both include and exclude the same ${labels[dimension]}: ${names.join(", ")}.`);
    }
  }
  return messages;
}

const WHOLE = /^[+-]?\d+$/;

function parseWhole(raw: string): number | null {
  const text = raw.trim();
  return WHOLE.test(text) ? Number(text) : null;
}

export interface ValidateContext {
  nameOf: (dimension: Dimension, id: number) => string;
  /** The existing commitment on a target, if there is one that is not this one. */
  existingFor?: (aggregation: Aggregation, targetId: number) => Commitment | undefined;
  mode: "create" | "edit";
}

/* Every CommitmentForm / CommitmentEditService rule, as field errors. */
export function validateForm(state: FormState, context: ValidateContext): FormErrors {
  const fields: Record<string, string[]> = {};
  const general: string[] = [];
  const add = (field: string, message: string) => (fields[field] ??= []).push(message);

  if (state.targetId === null) {
    add("scope", state.targetText.trim() ? `No ${state.aggregation} matches “${state.targetText.trim()}”.` : "Please select a target for the chosen aggregation type.");
  } else {
    const clash = context.existingFor?.(state.aggregation, state.targetId);
    if (clash) add("scope", `This ${state.aggregation} already has a commitment.`);
  }

  const target = parseWhole(state.target);
  if (!state.target.trim()) add("target", "This field is required.");
  else if (target === null) add("target", "Enter a whole number.");
  else if (target < 1) add("target", "Ensure this value is greater than or equal to 1.");

  const max = parseWhole(state.maxBalance);
  const min = parseWhole(state.minBalance);
  if (!state.maxBalance.trim()) add("max_balance", "This field is required.");
  else if (max === null) add("max_balance", "Enter a whole number.");
  else if (max < 0) add("max_balance", "Ensure this value is greater than or equal to 0.");
  if (!state.minBalance.trim()) add("min_balance", "This field is required.");
  else if (min === null) add("min_balance", "Enter a whole number.");
  else if (min > 0) add("min_balance", "Min balance must be zero or negative.");
  if (min !== null && max !== null && min > max) add("min_balance", "Min balance cannot be greater than max balance.");

  if (state.startDate && !/^\d{4}-\d{2}-\d{2}$/.test(state.startDate)) add("start_date", "Enter a valid date.");

  general.push(...overlappingRules(normalize(state), context.nameOf));
  return Object.keys(fields).length || general.length ? { fields, general } : NO_ERRORS;
}

const sorted = (ids: number[]) => [...ids].sort((a, b) => a - b);
const sameIds = (a: number[], b: number[]) => sorted(a).join(",") === sorted(b).join(",");

function targetKey(aggregation: Aggregation): "project_id" | "subproject_id" | "context_id" | "tag_id" {
  return `${aggregation}_id` as "project_id";
}

/* Everything a restart is given: the whole definition, since a restart opens a
   new generation and replaces any queued revision. */
export function definitionPayload(state: FormState): CommitmentChanges {
  const s = normalize(state);
  const payload: CommitmentChanges = {
    aggregation_type: s.aggregation,
    commitment_type: s.commitmentType,
    period: s.period,
    target_value: Number(s.target),
    banking_enabled: s.banking,
    max_balance: Number(s.maxBalance),
    min_balance: Number(s.minBalance),
    active: s.active,
  };
  payload[targetKey(s.aggregation)] = s.targetId ?? undefined;
  if (s.startDate) payload.start_date = s.startDate;
  for (const field of RULE_FIELDS) payload[field] = s.rules[field];
  return payload;
}

export function createPayload(state: FormState): CommitmentCreate {
  const s = normalize(state);
  const payload: CommitmentCreate = {
    aggregation_type: s.aggregation,
    commitment_type: s.commitmentType,
    period: s.period,
    target_value: Number(s.target),
    banking_enabled: s.banking,
    max_balance: Number(s.maxBalance),
    min_balance: Number(s.minBalance),
  };
  payload[targetKey(s.aggregation)] = s.targetId ?? undefined;
  if (s.startDate) payload.start_date = s.startDate;
  for (const field of RULE_FIELDS) if (s.rules[field].length) payload[field] = s.rules[field];
  return payload;
}

/* What an edit touches, by how the server applies it (CommitmentEditService):
   RESTART_FIELDS need the restart operation, NEXT_BOUNDARY fields are queued
   for the next period, active=false applies at once. */
export interface EditChanges {
  restart: string[];
  nextPeriod: string[];
  immediate: string[];
}

export function classifyChanges(base: FormState, next: FormState): EditChanges {
  const a = normalize(base);
  const b = normalize(next);
  const restart: string[] = [];
  if (a.aggregation !== b.aggregation) restart.push("Applies to");
  if (a.aggregation !== b.aggregation || a.targetId !== b.targetId) restart.push("Scope target");
  if (a.commitmentType !== b.commitmentType) restart.push("Measure");
  if (a.period !== b.period) restart.push("Period");
  if (b.startDate && a.startDate !== b.startDate) restart.push("Start date");
  if (!a.active && b.active) restart.push("Reactivating");

  const nextPeriod: string[] = [];
  if (Number(a.target) !== Number(b.target)) nextPeriod.push("Target");
  if (a.banking !== b.banking) nextPeriod.push("Time banking");
  if (Number(a.maxBalance) !== Number(b.maxBalance)) nextPeriod.push("Surplus cap");
  if (Number(a.minBalance) !== Number(b.minBalance)) nextPeriod.push("Deficit cap");
  if (RULE_FIELDS.some((field) => !sameIds(a.rules[field], b.rules[field]))) nextPeriod.push("Rules");

  const immediate = a.active && !b.active ? ["Paused"] : [];
  return { restart, nextPeriod, immediate };
}

/* PATCH body for an edit that needs no restart: only what changed. */
export function patchPayload(base: FormState, next: FormState): CommitmentChanges {
  const a = normalize(base);
  const b = normalize(next);
  const patch: CommitmentChanges = {};
  if (Number(a.target) !== Number(b.target)) patch.target_value = Number(b.target);
  if (a.banking !== b.banking) patch.banking_enabled = b.banking;
  if (Number(a.maxBalance) !== Number(b.maxBalance)) patch.max_balance = Number(b.maxBalance);
  if (Number(a.minBalance) !== Number(b.minBalance)) patch.min_balance = Number(b.minBalance);
  for (const field of RULE_FIELDS) if (!sameIds(a.rules[field], b.rules[field])) patch[field] = b.rules[field];
  if (a.active && !b.active) patch.active = false;
  return patch;
}

export const hasRestartChanges = (changes: EditChanges) => changes.restart.length > 0;
export const hasAnyChange = (changes: EditChanges) =>
  changes.restart.length + changes.nextPeriod.length + changes.immediate.length > 0;

/* Map API field names onto the form's field keys for server-side errors. */
export const API_FIELD_MAP: Record<string, string> = {
  aggregation_type: "scope",
  project_id: "scope",
  subproject_id: "scope",
  context_id: "scope",
  tag_id: "scope",
  target_value: "target",
  commitment_type: "commitment_type",
  start_date: "start_date",
  max_balance: "max_balance",
  min_balance: "min_balance",
};
