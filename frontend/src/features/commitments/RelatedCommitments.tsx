import { useMemo } from "react";
import { faBullseye, faPlus } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Disclose } from "@/components/Disclose";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useAllProjects, useContexts, useTags } from "@/api/meta";
import type { Commitment } from "@/api/types";
import { tagStyle } from "@/features/contexts-tags/ui";
import { useAllSubprojects, useCommitmentsAppliedTo } from "./api";
import { needsSubprojects, ruleLines, type EntityKind } from "./applies";
import { CommitmentSummary } from "./CommitmentSummary";

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
            <div key={c.id} className="related-commitment">
              <CommitmentTarget c={c} tagColor={tags.data?.find((t) => t.id === c.target.id)?.color} />
              <CommitmentSummary commitment={c} showTarget={false}>
              <div className="commit-rules">{ruleLines(c, names).map(line => <p key={line} className="commit-rule-line">{line}</p>)}</div>
              </CommitmentSummary>
            </div>
          ))}
        </div>
      ) : (
        <Empty>No commitments apply to this {kind} yet.</Empty>
      )}
      <div className="slab-foot">
        <AppLink className="btn btn--secondary" href={addHref}>
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

