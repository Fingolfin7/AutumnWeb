import { useMemo } from "react";
import { faBullseye, faPen, faPlus } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Disclose } from "@/components/Disclose";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useAllProjects, useContexts, useTags } from "@/api/meta";
import type { Commitment } from "@/api/types";
import { tagStyle } from "@/features/contexts-tags/ui";
import { useAllSubprojects, useCommitmentsAppliedTo } from "./api";
import { needsSubprojects, ruleLines, type EntityKind } from "./applies";
import { floatText, progressOf, signed, unitSuffix } from "./display";
import { aggregationLabel } from "./scope";
import { periodLabel } from "./formModel";

/* The "Commitments" slab on the context and tag edit pages
   (partials/commitments_panel.html): every commitment that reaches this
   item, its progress, the rules it composes and a way to edit or add one. */
export function RelatedCommitments({ kind, id }: { kind: EntityKind; id: number }) {
  const applied = useCommitmentsAppliedTo(kind, id);
  const projects = useAllProjects();
  const tags = useTags();
  const contexts = useContexts();
  const items = useMemo(() => applied.data ?? [], [applied.data]);
  /* Subprojects are only fetched to name the ones a rule mentions. */
  const wantSubprojects = needsSubprojects(items);
  const subs = useAllSubprojects(wantSubprojects);

  const names = useMemo(
    () => ({
      tags: new Map((tags.data ?? []).map((t) => [t.id, t.name])),
      projects: new Map((projects.data ?? []).map((p) => [p.id, p.name])),
      subprojects: new Map(subs.subprojects.map((s) => [s.id, s.name])),
      contexts: new Map((contexts.data ?? []).map((c) => [c.id, c.name])),
    }),
    [tags.data, projects.data, subs.subprojects, contexts.data],
  );

  const error = applied.error ?? projects.error;
  const loading = applied.isPending || projects.isPending || (wantSubprojects && subs.isPending);
  const addHref =
    kind === "project" ? urls.createCommitment(id) : `${urls.createCommitment()}?aggregation_type=${kind}&target_id=${id}`;

  return (
    <Disclose id={`${kind}-commitments`} icon={faBullseye} iconClass="text-cyan" title="Commitments" summary={loading ? "…" : items.length}>
      {error ? (
        <ErrorState error={error} onRetry={() => void applied.refetch()} />
      ) : loading ? (
        <Skeleton lines={3} />
      ) : items.length ? (
        <div className="band-list">
          {items.map((c) => (
            <CommitmentCard key={c.id} commitment={c} lines={ruleLines(c, names)} tagColor={tags.data?.find((t) => t.id === c.target.id)?.color} />
          ))}
        </div>
      ) : (
        <Empty>No commitments apply to this {kind} yet.</Empty>
      )}
      <div className="slab-foot">
        <AppLink className="btn btn--primary" href={addHref}>
          <Icon icon={faPlus} /> Add commitment
        </AppLink>
      </div>
    </Disclose>
  );
}

function CommitmentTarget({ c, tagColor }: { c: Commitment; tagColor?: string | null }) {
  switch (c.aggregation_type) {
    case "project":
      return (
        <AppLink className="commit-target text-red" href={urls.updateProject(c.target.id)}>
          {c.target.name}
        </AppLink>
      );
    case "subproject":
      return (
        <AppLink className="commit-target text-blue" href={urls.updateSubproject(c.target.id)}>
          {c.target.name}
        </AppLink>
      );
    case "context":
      return (
        <AppLink className="commit-target text-orange" href={urls.updateContext(c.target.id)}>
          {c.target.name}
        </AppLink>
      );
    default:
      return (
        <AppLink className="commit-target tag-chip" href={urls.updateTag(c.target.id)} style={tagStyle(tagColor)}>
          {c.target.name}
        </AppLink>
      );
  }
}

function CommitmentCard({ commitment: c, lines, tagColor }: { commitment: Commitment; lines: string[]; tagColor?: string | null }) {
  const progress = progressOf(c);
  const unit = unitSuffix(c.commitment_type);
  const pct = Math.round(progress.percentage);
  const balance = c.balance;
  return (
    <article className="band commit">
      <header className="commit-head">
        <CommitmentTarget c={c} tagColor={tagColor} />
        <span className="commit-kind">({aggregationLabel(c.aggregation_type)})</span>
        {!c.active ? <span className="badge-paused">paused</span> : null}
        <span className="commit-period">{periodLabel(c.period)}</span>
      </header>

      {c.active ? (
        <>
          <p className="commit-figures">
            <span className="commit-actual">{Math.round(progress.actual)}</span>
            <span className="commit-goal">
              / {progress.target}
              {c.commitment_type === "time" ? "m" : " sessions"}
            </span>
            <span className="commit-pct">{pct}%</span>
          </p>
          <div className="meter">
            <div className={`meter-fill ${progress.status}`} style={{ width: `${pct}%` }} />
          </div>
          {c.banking_enabled ? (
            <div className="bank-row">
              <div className="bank-cell">
                <span className="bank-label">Bank (reconciled)</span>
                <span className={`bank-value ${balance >= 0 ? "text-green" : "text-red"}`}>
                  {signed(balance)}
                  {unit}
                </span>
              </div>
              <div className="bank-cell">
                <span className="bank-label">This period (unbanked)</span>
                <span className={`bank-value ${progress.surplus >= 0 ? "text-green" : "text-red"}`}>
                  {signed(progress.surplus, c.commitment_type === "time" ? floatText(progress.surplus) : String(progress.surplus))}
                  {unit}
                </span>
              </div>
            </div>
          ) : null}
        </>
      ) : null}

      {lines.length ? (
        <div className="commit-rules">
          {lines.map((line) => (
            <p key={line} className="commit-rule-line">
              {line}
            </p>
          ))}
        </div>
      ) : null}

      <div className="commit-foot">
        <AppLink className="btn btn--ghost" href={urls.updateCommitment(c.id)}>
          <Icon icon={faPen} /> Edit commitment
        </AppLink>
      </div>
    </article>
  );
}
