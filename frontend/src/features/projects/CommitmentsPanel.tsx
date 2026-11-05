import { QuickTarget } from "@/features/commitments/QuickTarget";
import { faBullseye, faPlus } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Disclose } from "@/components/Disclose";
import { AppLink, urls } from "@/app/links";
import { useAllProjects, useContexts, useTags } from "@/api/meta";
import type { Commitment } from "@/api/types";
import { useSubprojectNames } from "./api";
import {
  commitmentRuleLines,
  formatSigned,
  unnamedSubprojectIds,
  type NameLookup,
} from "./logic";

const KIND_LABEL = { project: "Project", subproject: "Subproject", context: "Context", tag: "Tag" } as const;
const PERIOD_LABEL = {
  daily: "Daily",
  weekly: "Weekly",
  fortnightly: "Fortnightly",
  monthly: "Monthly",
  quarterly: "Quarterly",
  yearly: "Yearly",
} as const;

/* The commitments that apply to a project or subproject
   (partials/commitments_panel.html). Callers filter; this shows. */
export function CommitmentsPanel({
  commitments,
  addUrl,
  entityLabel,
  knownSubprojects,
}: {
  commitments: Commitment[];
  addUrl: string;
  entityLabel: "project" | "subproject";
  /** Subproject names already at hand; others named in rules are fetched. */
  knownSubprojects: Map<number, string>;
}) {
  const projects = useAllProjects();
  const tags = useTags();
  const contexts = useContexts();
  const missing = unnamedSubprojectIds(commitments, knownSubprojects);
  const fetched = useSubprojectNames(missing);

  const names: NameLookup = {
    tags: new Map((tags.data ?? []).map((t) => [t.id, t.name])),
    projects: new Map((projects.data ?? []).map((p) => [p.id, p.name])),
    contexts: new Map((contexts.data ?? []).map((c) => [c.id, c.name])),
    subprojects: new Map([...knownSubprojects, ...fetched]),
  };
  const tagColor = (id: number) => tags.data?.find((t) => t.id === id)?.color;

  if (!commitments.length) return (
    <div className="commitment-empty">
      <AppLink className="btn btn--quiet" href={addUrl}><Icon icon={faPlus} /> Add commitment</AppLink>
      <span className="muted">Set a rhythm for this {entityLabel}.</span>
    </div>
  );

  const target = (commitment: Commitment) => {
    const { kind, id, name } = commitment.target;
    switch (commitment.aggregation_type) {
      case "project":
        return (
          <AppLink className="commit-target text-red" href={urls.updateProject(id)}>
            {name}
          </AppLink>
        );
      case "subproject":
        return (
          <AppLink className="commit-target text-blue" href={urls.updateSubproject(id)}>
            {name}
          </AppLink>
        );
      case "context":
        return (
          <AppLink className="commit-target text-orange" href={urls.updateContext(id)}>
            {name}
          </AppLink>
        );
      case "tag": {
        const color = tagColor(id);
        return (
          <AppLink
            className="commit-target tag-chip"
            href={urls.updateTag(id)}
            style={color ? ({ "--tag": color } as React.CSSProperties) : undefined}
          >
            {name}
          </AppLink>
        );
      }
      default:
        return <span className="commit-target">{name || kind}</span>;
    }
  };

  return (
    <Disclose id="commitments" icon={faBullseye} iconClass="text-cyan" title="Commitments" summary={commitments.length} className="commitment-section">
      <div className="band-list">
          {commitments.map((commitment) => {
            const period = commitment.current_period;
            const timeBased = commitment.commitment_type === "time";

            const rules = commitmentRuleLines(commitment, names);
            const balance = commitment.balance;
            const surplus = commitment.current_surplus;
            return (
              <article className="band commit" key={commitment.id}>
                <header className="commit-head">
                  {target(commitment)}
                  <span className="commit-kind">({KIND_LABEL[commitment.aggregation_type]})</span>
                  {!commitment.active ? <span className="badge-paused">paused</span> : null}
                  <span className="commit-period">{PERIOD_LABEL[commitment.period]}</span>
                </header>

                {commitment.active ? (
                  <>
                    <QuickTarget key={commitment.version} commitment={commitment} />
                    <progress className="subproject-progress commitment-progress" max={Math.max(period.target, period.accrued, 1)} value={period.accrued} aria-label="Commitment progress" />

                    {commitment.banking_enabled ? (
                      <details className="commitment-bank-detail"><summary>Time carryover</summary><div className="bank-row">
                        <div className="bank-cell">
                          <span className="bank-label">Carried balance</span>
                          <span className={`bank-value ${balance >= 0 ? "text-green" : "text-red"}`}>{formatSigned(balance, timeBased)}</span>
                        </div>
                        <div className="bank-cell">
                          <span className="bank-label">This period</span>
                          <span className={`bank-value ${surplus >= 0 ? "text-green" : "text-red"}`}>{formatSigned(surplus, timeBased)}</span>
                        </div>
                      </div></details>
                    ) : null}
                  </>
                ) : null}

                {rules.length ? (
                  <div className="commit-rules">
                    {rules.map((line) => (
                      <p className="commit-rule-line" key={line}>
                        {line}
                      </p>
                    ))}
                  </div>
                ) : null}


              </article>
            );
          })}
      </div>


      <div className="slab-foot"><AppLink className="btn btn--quiet" href={addUrl}>Add another commitment</AppLink></div>
    </Disclose>
  );
}
