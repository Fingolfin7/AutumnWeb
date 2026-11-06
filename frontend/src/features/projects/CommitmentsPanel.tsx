import { CommitmentSummary } from "@/features/commitments/CommitmentSummary";
import { faBullseye, faPlus } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Disclose } from "@/components/Disclose";
import { AppLink } from "@/app/links";
import { useAllProjects, useContexts, useTags } from "@/api/meta";
import type { Commitment } from "@/api/types";
import { useSubprojectNames } from "./api";
import { commitmentRuleLines, unnamedSubprojectIds, type NameLookup } from "./logic";

export function CommitmentsPanel({ commitments, addUrl, entityLabel, knownSubprojects }: {
  commitments: Commitment[];
  addUrl: string;
  entityLabel: "project" | "subproject";
  knownSubprojects: Map<number, string>;
}) {
  const projects = useAllProjects();
  const tags = useTags();
  const contexts = useContexts();
  const fetched = useSubprojectNames(unnamedSubprojectIds(commitments, knownSubprojects));
  const names: NameLookup = {
    tags: new Map((tags.data ?? []).map(t => [t.id, t.name])),
    projects: new Map((projects.data ?? []).map(p => [p.id, p.name])),
    contexts: new Map((contexts.data ?? []).map(c => [c.id, c.name])),
    subprojects: new Map([...knownSubprojects, ...fetched]),
  };
  if (!commitments.length) return <div className="commitment-empty"><AppLink className="btn btn--quiet" href={addUrl}><Icon icon={faPlus} /> Add commitment</AppLink><span className="muted">Set a rhythm for this {entityLabel}.</span></div>;
  return <Disclose id="commitments" icon={faBullseye} iconClass="text-cyan" title="Commitments" summary={commitments.length} className="commitment-section">
    {commitments.map(commitment => <CommitmentSummary key={commitment.id} commitment={commitment}>{commitmentRuleLines(commitment, names).map(line => <p key={line}>{line}</p>)}</CommitmentSummary>)}
    <div className="slab-foot"><AppLink className="btn btn--quiet" href={addUrl}>Add another commitment</AppLink></div>
  </Disclose>;
}
