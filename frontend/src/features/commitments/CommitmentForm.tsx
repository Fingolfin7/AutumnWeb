import { useId, useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import {
  faArrowLeft,
  faArrowRight,
  faChartLine,
  faChevronDown,
  faCheckCircle,
  faCodeBranch,
  faInfoCircle,
  faSearch,
  faTrash,
  faUndo,
} from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { bootstrap } from "@/bootstrap";
import { ApiError } from "@/api/errors";
import { useAllProjects, useContexts, useTags } from "@/api/meta";
import type { Commitment } from "@/api/types";
import { DeskHead, FieldErrors, FormLevelErrors } from "@/features/contexts-tags/ui";
import { hasErrors, NO_ERRORS, parseFormErrors, type FormErrors } from "@/features/contexts-tags/formErrors";
import { useAllSubprojects, useCommitments, useCreateCommitment, useRestartCommitment, useUpdateCommitment } from "./api";
import { floatText, monthDay, monthDayYear, progressOf, redirectFor, signed, todayIn } from "./display";
import {
  API_FIELD_MAP,
  classifyChanges,
  createPayload,
  definitionPayload,
  hasAnyChange,
  MEASURES,
  newState,
  normalize,
  patchPayload,
  periodLabel,
  PERIODS,
  pruneRules,
  RULE_FIELDS,
  ruleField,
  stateFromCommitment,
  validateForm,
  type CommitmentType,
  type FormState,
  type Period,
  type RuleField,
} from "./formModel";
import {
  AGGREGATIONS,
  buildScopeMeta,
  DIMENSION_ORDER,
  isRuleOptionInScope,
  resolveTarget,
  RULE_DIMENSIONS,
  targetOptions,
  type Aggregation,
  type Dimension,
  type ScopeMeta,
} from "./scope";
import "./commitments.css";

const FORM_FIELDS = new Set(["scope", "target", "start_date", "max_balance", "min_balance", "commitment_type", "period", "rules"]);

export interface CommitmentFormProps {
  mode: "create" | "edit";
  /** Edit: the commitment as the server has it right now. */
  commitment?: Commitment;
  /** Create: a scope to start from (a project page's "Add commitment"). */
  prefill?: { aggregation: Aggregation; targetId: number };
}

/* One form for creating and editing a commitment (create_commitment.html and
   update_commitment.html). The scope metadata the old pages had injected is
   derived from the projects, subprojects, contexts and tags lists. */
export function CommitmentForm({ mode, commitment, prefill }: CommitmentFormProps) {
  const navigate = useNavigate();
  const toast = useToast();
  const projects = useAllProjects();
  const contexts = useContexts();
  const tags = useTags();
  const commitments = useCommitments();
  const create = useCreateCommitment();
  const update = useUpdateCommitment(commitment?.id ?? 0);
  const restart = useRestartCommitment(commitment?.id ?? 0);

  /* The scope-target label of an existing commitment is its target's name. */
  const [base, setBase] = useState<FormState>(() => {
    if (commitment) return stateFromCommitment(commitment, commitment.target.name);
    const state = { ...newState(), startDate: todayIn(bootstrap().profile.timezone) };
    return prefill ? { ...state, aggregation: prefill.aggregation, targetId: prefill.targetId } : state;
  });
  const [state, setState] = useState<FormState>(base);
  const [baseVersion, setBaseVersion] = useState(commitment?.version ?? 0);
  const [rulesOpen, setRulesOpen] = useState(() => RULE_FIELDS.some((field) => state.rules[field].length > 0));
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);
  const [restartRequested, setRestartRequested] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const needSubprojects = state.aggregation === "subproject" || (rulesOpen && RULE_DIMENSIONS[state.aggregation].includes("subproject"));
  const subs = useAllSubprojects(needSubprojects);
  const meta = useMemo(
    () => buildScopeMeta(projects.data ?? [], subs.subprojects, tags.data ?? []),
    [projects.data, subs.subprojects, tags.data],
  );
  const options = useMemo(() => targetOptions(state.aggregation, meta, contexts.data ?? []), [state.aggregation, meta, contexts.data]);

  /* A prefilled or loaded target gets its label once the option list exists. */
  const targetLabel = useMemo(() => {
    if (state.targetId === null) return state.targetText;
    return options.find((o) => o.id === state.targetId)?.label ?? state.targetText;
  }, [options, state.targetId, state.targetText]);

  const nameOf = (dimension: Dimension, id: number) =>
    dimension === "project"
      ? (meta.projects.get(id)?.name ?? `#${id}`)
      : dimension === "subproject"
        ? (meta.subprojects.get(id)?.name ?? `#${id}`)
        : (meta.tags.get(id)?.name ?? `#${id}`);

  const existingFor = (aggregation: Aggregation, targetId: number) =>
    commitments.data?.find((c) => c.aggregation_type === aggregation && c.target.id === targetId && c.id !== commitment?.id);

  const current = { ...state, targetText: targetLabel };
  const changes = commitment ? classifyChanges(base, current) : null;
  const showRestart = !!changes && restartRequested && changes.restart.length > 0;
  const stale = !!commitment && commitment.version !== baseVersion;
  const busy = create.isPending || update.isPending || restart.isPending;

  const live = validateForm(current, { nameOf, existingFor, mode });
  const scopeClash = state.targetId !== null ? existingFor(state.aggregation, state.targetId) : undefined;
  const early: FormErrors = scopeClash
    ? { fields: { scope: [`This ${state.aggregation} already has a commitment.`] }, general: [] }
    : NO_ERRORS;
  const shown = hasErrors(errors) ? errors : submitted ? live : early;

  const setField = (patch: Partial<FormState>) => {
    setState((prev) => ({ ...prev, ...patch }));
    setErrors(NO_ERRORS);
  };

  const chooseAggregation = (aggregation: Aggregation) => {
    setState((prev) => normalize({ ...prev, aggregation, targetId: null, targetText: "" }));
    setErrors(NO_ERRORS);
  };

  const chooseTarget = (text: string, final: boolean) => {
    const match = resolveTarget(text, options);
    const exact = match && match.label.toLowerCase() === text.trim().toLowerCase();
    setState((prev) => {
      if (match && (final || exact)) {
        const next = { ...prev, targetId: match.id, targetText: match.label };
        return subs.isPending ? normalize(next) : pruneRules(next, meta);
      }
      return { ...prev, targetId: null, targetText: text };
    });
    setErrors(NO_ERRORS);
  };

  const toggleRule = (field: RuleField, id: number) => {
    setState((prev) => {
      const list = prev.rules[field];
      return { ...prev, rules: { ...prev.rules, [field]: list.includes(id) ? list.filter((x) => x !== id) : [...list, id] } };
    });
    setErrors(NO_ERRORS);
  };

  const onFailure = (error: unknown) => {
    if (error instanceof ApiError && error.code === "version_conflict") {
      setErrors({ fields: {}, general: ["This commitment was changed somewhere else. Load the latest version, then re-apply your edits."] });
      return;
    }
    if (error instanceof ApiError && error.code === "restart_required") {
      setRestartRequested(true);
      return;
    }
    const parsed = parseFormErrors(error, { fieldMap: API_FIELD_MAP, conflictField: "scope" });
    /* Anything keyed to a field the form has no spot for still has to be read. */
    for (const key of Object.keys(parsed.fields)) {
      if (/_ids$/.test(key)) {
        parsed.fields.rules = [...(parsed.fields.rules ?? []), ...(parsed.fields[key] ?? [])];
        delete parsed.fields[key];
      } else if (!FORM_FIELDS.has(key)) {
        parsed.general.push(...(parsed.fields[key] ?? []).map((line) => `${key}: ${line}`));
        delete parsed.fields[key];
      }
    }
    setErrors(parsed);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (hasErrors(live)) {
      setErrors(NO_ERRORS);
      return;
    }
    setErrors(NO_ERRORS);

    if (!commitment) {
      create.mutate(createPayload(current), {
        onSuccess: (created) => {
          toast.success("Commitment added successfully");
          navigate(redirectFor(created));
        },
        onError: onFailure,
      });
      return;
    }
    if (!changes || !hasAnyChange(changes)) {
      toast.info("No changes to save.");
      return;
    }
    if (changes.restart.length) {
      setRestartRequested(true);
      return;
    }
    update.mutate(
      { body: patchPayload(base, current), version: commitment.version },
      {
        onSuccess: (saved) => {
          const queued = saved.pending_revision;
          toast.success(
            queued && changes.nextPeriod.length
              ? `Commitment updated. Changes to ${changes.nextPeriod.join(", ")} apply from ${monthDayYear(queued.effective_from)}.`
              : "Commitment updated successfully",
          );
          navigate(redirectFor(saved));
        },
        onError: onFailure,
      },
    );
  };

  const doRestart = (keepBalance: boolean) => {
    if (!commitment) return;
    restart.mutate(
      { keepBalance, changes: definitionPayload(current), version: commitment.version },
      {
        onSuccess: (saved) => {
          toast.success(
            `Commitment restarted. ${keepBalance ? "The existing bank balance was carried forward." : "The bank balance was reset to zero."}`,
          );
          navigate(redirectFor(saved));
        },
        onError: onFailure,
      },
    );
  };

  const reload = () => {
    if (!commitment) return;
    const next = stateFromCommitment(commitment, commitment.target.name);
    setBase(next);
    setState(next);
    setBaseVersion(commitment.version);
    setRestartRequested(false);
    setErrors(NO_ERRORS);
    setSubmitted(false);
  };

  const ruleDimensions = DIMENSION_ORDER.filter((dimension) => RULE_DIMENSIONS[state.aggregation].includes(dimension));
  const sameKind = state.aggregation === "context" ? "context" : state.aggregation;

  return (
    <>
      <DeskHead title={commitment ? commitment.target.name : "New commitment"} />

      <form className="fields" onSubmit={submit} noValidate>
        <div className="split">
          <div id="input-fields">
            {stale ? (
              <aside className="msg msg--warning" role="alert">
                <Icon icon={faInfoCircle} className="msg-icon" />
                <div>
                  <p>This commitment changed elsewhere since you opened it.</p>
                  <div className="form-actions">
                    <button type="button" className="btn btn--ghost" onClick={reload}>
                      <Icon icon={faUndo} /> Load latest
                    </button>
                  </div>
                </div>
              </aside>
            ) : null}

            <section className="slab slab-pad">
              <div className="field">
                <label htmlFor="id_aggregation_type">Applies to</label>
                <select id="id_aggregation_type" value={state.aggregation} onChange={(e) => chooseAggregation(e.target.value as Aggregation)}>
                  {AGGREGATIONS.map((a) => (
                    <option key={a.value} value={a.value}>
                      {a.label}
                    </option>
                  ))}
                </select>
                <FieldErrors errors={shown.fields.aggregation} />
              </div>

              <div className="field">
                <label htmlFor="scope-target-search">Scope target</label>
                <input
                  type="text"
                  id="scope-target-search"
                  placeholder={`Search ${state.aggregation}...`}
                  autoComplete="off"
                  list="scope-target-options"
                  value={targetLabel}
                  aria-invalid={!!shown.fields.scope}
                  aria-describedby="scope-target-help"
                  onChange={(e) => chooseTarget(e.target.value, false)}
                  onBlur={(e) => chooseTarget(e.target.value, true)}
                />
                <datalist id="scope-target-options">
                  {options.map((option) => (
                    <option key={option.id} value={option.label} />
                  ))}
                </datalist>
                <small className="muted" id="scope-target-help">
                  Type and pick the context, tag, project, or subproject this commitment belongs to.
                </small>
                <FieldErrors errors={shown.fields.scope} />
                {scopeClash ? (
                  <small className="muted commitment-scope-note">
                    <AppLink href={urls.updateCommitment(scopeClash.id)}>Edit the existing {sameKind} commitment</AppLink> instead.
                  </small>
                ) : null}
              </div>
            </section>

            <details
              className="slab slab-pad commitment-rules"
              open={rulesOpen || undefined}
              onToggle={(event) => setRulesOpen((event.currentTarget as HTMLDetailsElement).open)}
            >
              <summary className="commitment-rules-summary">
                Rules <span className="muted">(optional)</span>
                <Icon icon={faChevronDown} className="rule-chevron" />
              </summary>
              {ruleDimensions.length === 0 ? (
                <p className="muted">A subproject commitment counts that subproject alone, so there are no rules to add.</p>
              ) : (
                <RuleGroups
                  dimensions={ruleDimensions}
                  state={state}
                  meta={meta}
                  projects={projects.data ?? []}
                  tagList={tags.data ?? []}
                  loadingSubprojects={subs.isPending}
                  onToggle={toggleRule}
                />
              )}
              <FieldErrors errors={shown.fields.rules} />
            </details>

            <section className="slab slab-pad">
              <div className="two-up">
                <div className="field">
                  <label htmlFor="id_commitment_type">Measure</label>
                  <select
                    id="id_commitment_type"
                    value={state.commitmentType}
                    onChange={(e) => setField({ commitmentType: e.target.value as CommitmentType })}
                  >
                    {MEASURES.map((m) => (
                      <option key={m.value} value={m.value}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                  <FieldErrors errors={shown.fields.commitment_type} />
                </div>
                <div className="field">
                  <label htmlFor="id_period">Period</label>
                  <select id="id_period" value={state.period} onChange={(e) => setField({ period: e.target.value as Period })}>
                    {PERIODS.map((p) => (
                      <option key={p.value} value={p.value}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                  <FieldErrors errors={shown.fields.period} />
                </div>
                <div className="field">
                  <label htmlFor="id_start_date">Start date</label>
                  <input id="id_start_date" type="date" value={state.startDate} onChange={(e) => setField({ startDate: e.target.value })} />
                  <FieldErrors errors={shown.fields.start_date} />
                </div>
                <div className="field">
                  <label htmlFor="id_target">Target</label>
                  <input
                    id="id_target"
                    type="number"
                    inputMode="numeric"
                    min={1}
                    step={1}
                    placeholder="Target amount"
                    value={state.target}
                    aria-invalid={!!shown.fields.target}
                    onChange={(e) => setField({ target: e.target.value })}
                  />
                  <small className="help-text muted">
                    {state.commitmentType === "time" ? "Minutes for time-based commitments" : "Count for session-based commitments"}
                  </small>
                  <FieldErrors errors={shown.fields.target} />
                </div>
              </div>
            </section>

            <section className="slab slab-pad">
              <div className="check-row">
                <input id="id_banking_enabled" type="checkbox" checked={state.banking} onChange={(e) => setField({ banking: e.target.checked })} />
                <label htmlFor="id_banking_enabled">Enable time banking</label>
              </div>

              <div className="two-up u-mt-4">
                <div className="field">
                  <label htmlFor="id_max_balance">Surplus cap</label>
                  <input
                    id="id_max_balance"
                    type="number"
                    inputMode="numeric"
                    min={0}
                    step={1}
                    placeholder="Max balance cap"
                    value={state.maxBalance}
                    aria-invalid={!!shown.fields.max_balance}
                    onChange={(e) => setField({ maxBalance: e.target.value })}
                  />
                  {mode === "create" ? <small className="muted">Most that can be banked</small> : null}
                  <FieldErrors errors={shown.fields.max_balance} />
                </div>
                <div className="field">
                  <label htmlFor="id_min_balance">Deficit cap</label>
                  <input
                    id="id_min_balance"
                    type="number"
                    inputMode="numeric"
                    max={0}
                    step={1}
                    placeholder="Min balance cap"
                    value={state.minBalance}
                    aria-invalid={!!shown.fields.min_balance}
                    onChange={(e) => setField({ minBalance: e.target.value })}
                  />
                  {mode === "create" ? <small className="muted">Largest deficit allowed (negative)</small> : null}
                  <FieldErrors errors={shown.fields.min_balance} />
                </div>
              </div>

              {commitment ? (
                <>
                  <div className="check-row">
                    <input id="id_active" type="checkbox" checked={state.active} onChange={(e) => setField({ active: e.target.checked })} />
                    <label htmlFor="id_active">Active</label>
                  </div>
                  <small className="muted">Uncheck to pause tracking without deleting this commitment.</small>
                </>
              ) : null}

              {commitment?.pending_revision ? <PendingNotice commitment={commitment} nameOf={nameOf} /> : null}

              {changes && !showRestart ? <PolicyHints changes={changes} commitment={commitment!} /> : null}

              <FormLevelErrors errors={shown.general} />

              {showRestart && commitment ? (
                <aside className="msg msg--warning u-mt-4" role="alert" aria-labelledby="restart-heading">
                  <Icon icon={faCodeBranch} className="msg-icon" />
                  <div>
                    <p className="page-eyebrow">New tracking chapter</p>
                    <h4 id="restart-heading">Restart this commitment to apply these changes</h4>
                    <p className="u-mt-4">
                      Its completed history stays intact. The updated scope and settings begin now as a new generation.
                    </p>
                    <p className="muted u-mt-4">
                      Changing {changes!.restart.join(", ")} affects which activity counts or when tracking periods begin. Applying that to
                      earlier progress would rewrite its history.
                      {commitment.pending_revision ? " Queued changes are replaced by what is in this form." : ""}
                    </p>
                    <p className="u-mt-4">What should happen to the current bank balance?</p>
                    <div className="form-actions">
                      <button type="button" className="btn btn--primary" disabled={busy} onClick={() => doRestart(true)}>
                        <Icon icon={faArrowRight} /> Restart and keep balance
                      </button>
                      <button type="button" className="btn btn--ghost" disabled={busy} onClick={() => doRestart(false)}>
                        <Icon icon={faUndo} /> Restart and reset balance
                      </button>
                      <button
                        type="button"
                        className="btn btn--quiet"
                        onClick={() => {
                          setState(base);
                          setRestartRequested(false);
                          setSubmitted(false);
                        }}
                      >
                        Discard these changes
                      </button>
                    </div>
                  </div>
                </aside>
              ) : null}

              <div className="form-actions">
                <AppLink className="btn btn--ghost" href={urls.home()}>
                  <Icon icon={faArrowLeft} /> {commitment ? "Back" : "Cancel"}
                </AppLink>
                {commitment ? (
                  <AppLink className="btn btn--stop" href={urls.deleteCommitment(commitment.id)}>
                    <Icon icon={faTrash} /> Delete
                  </AppLink>
                ) : null}
                {!showRestart ? (
                  <button type="submit" className="btn btn--primary btn--spacer" disabled={busy}>
                    <Icon icon={faCheckCircle} /> {commitment ? "Update commitment" : "Create commitment"}
                  </button>
                ) : null}
              </div>
            </section>
          </div>

          {commitment ? <ProgressPanel commitment={commitment} /> : null}
        </div>
      </form>
    </>
  );
}

function RuleGroups({
  dimensions,
  state,
  meta,
  projects,
  tagList,
  loadingSubprojects,
  onToggle,
}: {
  dimensions: Dimension[];
  state: FormState;
  meta: ScopeMeta;
  projects: { id: number; name: string }[];
  tagList: { id: number; name: string }[];
  loadingSubprojects: boolean;
  onToggle: (field: RuleField, id: number) => void;
}) {
  const optionsFor = (dimension: Dimension) => {
    const raw =
      dimension === "project"
        ? projects.map((p) => ({ id: p.id, label: p.name }))
        : dimension === "tag"
          ? tagList.map((t) => ({ id: t.id, label: t.name }))
          : [...meta.subprojects.values()].map((s) => ({ id: s.id, label: `${s.name} (${s.projectName})` }));
    return raw
      .filter((o) => isRuleOptionInScope(meta, dimension, o.id, state.aggregation, state.targetId))
      .sort((a, b) => a.label.localeCompare(b.label));
  };
  return (
    <>
      {dimensions.flatMap((dimension) =>
        (["include", "exclude"] as const).map((mode) => {
          const field = ruleField(mode, dimension);
          return (
            <RuleGroup
              key={field}
              dimension={dimension}
              label={`${mode === "include" ? "Only include" : "Exclude"} ${dimension}s`}
              noun={`${dimension}s`}
              options={optionsFor(dimension)}
              selected={state.rules[field]}
              loading={dimension === "subproject" && loadingSubprojects}
              onToggle={(id) => onToggle(field, id)}
            />
          );
        }),
      )}
    </>
  );
}

function RuleGroup({
  dimension,
  label,
  noun,
  options,
  selected,
  loading,
  onToggle,
}: {
  dimension: Dimension;
  label: string;
  noun: string;
  options: { id: number; label: string }[];
  selected: number[];
  loading: boolean;
  onToggle: (id: number) => void;
}) {
  const [query, setQuery] = useState("");
  const labelId = useId();
  const needle = query.trim().toLowerCase();
  const visible = options.filter((o) => selected.includes(o.id) || o.label.toLowerCase().includes(needle));
  return (
    <div className="field commitment-rule-group" data-dimension={dimension} role="group" aria-labelledby={labelId}>
      <label id={labelId}>{label}</label>
      <details className="commitment-rule-dropdown">
        <summary className="filter-launcher tag-summary">
          {selected.length > 0 ? `${selected.length} selected` : "Select items"}
          <Icon icon={faChevronDown} className="rule-chevron" />
        </summary>
        <div className="picker u-mt-4">
          <div className="picker-search">
            <Icon icon={faSearch} />
            <input
              type="text"
              className="picker-search-input commitment-rule-search"
              placeholder={`Search ${noun}…`}
              aria-label={`Search ${noun}…`}
              autoComplete="off"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div className="picker-options">
            {visible.map((option) => (
              <label key={option.id} className="option-chip commitment-rule-option">
                <input type="checkbox" checked={selected.includes(option.id)} onChange={() => onToggle(option.id)} />
                <span className="option-label tag-label">{option.label}</span>
              </label>
            ))}
          </div>
          {loading ? <p className="picker-empty">Loading subprojects…</p> : visible.length === 0 ? <p className="picker-empty">Nothing matches.</p> : null}
        </div>
      </details>
    </div>
  );
}

/* What a queued revision will change and when. */
function PendingNotice({ commitment, nameOf }: { commitment: Commitment; nameOf: (d: Dimension, id: number) => string }) {
  const pending = commitment.pending_revision;
  if (!pending) return null;
  const unit = commitment.commitment_type === "time" ? " min" : " sessions";
  const lines: string[] = [];
  for (const [key, value] of Object.entries(pending.changes as Record<string, unknown>)) {
    if (key === "target_value") lines.push(`Target: ${value}${unit}`);
    else if (key === "banking_enabled") lines.push(`Time banking: ${value ? "on" : "off"}`);
    else if (key === "max_balance") lines.push(`Surplus cap: ${value}`);
    else if (key === "min_balance") lines.push(`Deficit cap: ${value}`);
    else {
      const match = /^(include|exclude)_(project|subproject|tag|context)_ids$/.exec(key);
      if (match && Array.isArray(value)) {
        const dimension = match[2] as Dimension;
        const names = (value as number[]).map((id) => nameOf(dimension, id)).join(", ");
        lines.push(`${match[1] === "include" ? "Only include" : "Exclude"} ${match[2]}s: ${names || "none"}`);
      }
    }
  }
  return (
    <aside className="msg msg--info commitment-notice">
      <Icon icon={faInfoCircle} className="msg-icon" />
      <div>
        <p>Changes are queued for {monthDayYear(pending.effective_from)}, the start of the next period. The form below already shows them.</p>
        {lines.length ? (
          <ul>
            {lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </aside>
  );
}

/* Before saving: say how the server will apply what was touched. */
function PolicyHints({ changes, commitment }: { changes: ReturnType<typeof classifyChanges>; commitment: Commitment }) {
  if (!hasAnyChange(changes)) return null;
  const boundary = monthDayYear(commitment.current_period.end);
  return (
    <div className="commitment-notice">
      {changes.restart.length ? (
        <aside className="msg msg--warning">
          <Icon icon={faCodeBranch} className="msg-icon" />
          <p>
            {changes.restart.join(", ")} can only change by restarting the commitment, which opens a new tracking chapter. You will choose
            what happens to the bank balance when you save.
          </p>
        </aside>
      ) : null}
      {changes.nextPeriod.length ? (
        <aside className="msg msg--info">
          <Icon icon={faInfoCircle} className="msg-icon" />
          <p>
            Changes to {changes.nextPeriod.join(", ")} apply from {boundary}. The current period keeps its present rules so its history
            is not rewritten.
          </p>
        </aside>
      ) : null}
      {changes.immediate.length ? (
        <aside className="msg msg--info">
          <Icon icon={faInfoCircle} className="msg-icon" />
          <p>Pausing takes effect immediately.</p>
        </aside>
      ) : null}
    </div>
  );
}

function ProgressPanel({ commitment: c }: { commitment: Commitment }) {
  const progress = progressOf(c);
  const time = c.commitment_type === "time";
  const num = (value: number) => (time ? floatText(value) : String(value));
  const period = c.current_period;
  return (
    <section id="progress-info" className="slab slab-pad">
      <p className="field-label">
        <Icon icon={faChartLine} className="text-green" /> Current progress
      </p>
      <p className="commit-figures">
        <span className="commit-actual">{num(progress.actual)}</span>
        <span className="commit-goal">
          / {progress.target}
          {time ? " min" : " sessions"}
        </span>
        <span className="commit-pct">{progress.percentage.toFixed(1)}%</span>
      </p>
      <div className="meter">
        <div className={`meter-fill ${progress.status}`} style={{ ["--progress" as string]: `${progress.percentage}%` }} />
      </div>
      <div className="meta-list u-mt-4">
        <div className="meta-row">
          <span className="meta-label">Period</span>
          <span className="meta-value">{periodLabel(c.period)}</span>
        </div>
        <div className="meta-row">
          <span className="meta-label">Window</span>
          <span className="meta-value text-cyan">
            {monthDay(period.start)} &rarr; {monthDayYear(period.end)}
          </span>
        </div>
        {c.banking_enabled ? (
          <>
            <div className="meta-row">
              <span className="meta-label">Bank balance</span>
              <span className={`meta-value ${c.balance >= 0 ? "text-green" : "text-red"}`}>
                {signed(c.balance)}
                {time ? " min" : ""}
              </span>
            </div>
            <div className="meta-row">
              <span className="meta-label">This period, unbanked</span>
              <span className={`meta-value ${progress.surplus >= 0 ? "text-green" : "text-red"}`}>
                {signed(progress.surplus, num(progress.surplus))}
                {time ? " min" : ""}
              </span>
            </div>
          </>
        ) : null}
        <div className="meta-row">
          <span className="meta-label">Tracking since</span>
          <span className="meta-value text-cyan">{monthDayYear(c.ledger_start_at)}</span>
        </div>
      </div>
    </section>
  );
}
