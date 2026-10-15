import type { CSSProperties } from "react";
import { faBullseye, faCheck, faFire, faHourglassHalf, faTimes } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Disclose } from "@/components/Disclose";
import { AppLink, urls } from "@/app/links";
import { useTags } from "@/api/meta";
import type { DashboardCommitment } from "./api";

const AGGREGATION_LABEL: Record<string, string> = {
  project: "Project",
  subproject: "Subproject",
  context: "Context",
  tag: "Tag",
};

/* Whole numbers read cleaner than the old "-180.0m"; keep one decimal only
   when there is a real fraction. */
const tidy = (value: number) => (Number.isInteger(value) ? String(value) : value.toFixed(1));
const signed = (value: number) => (value >= 0 ? `+${tidy(value)}` : tidy(value));

/* Active commitments with progress, bank and streak strip (the dashboard's
   commitments slab). */
export function CommitmentsPanel({ items }: { items: DashboardCommitment[] }) {
  return (
    <Disclose id="home-commitments" icon={faBullseye} iconClass="text-cyan" title="Commitments" summary={`${items.length} active`}>
      {items.length ? (
        <div className="band-list">
          {items.map((item) => (
            <CommitmentBand key={item.commitment.id} item={item} />
          ))}
        </div>
      ) : (
        <p className="empty">
          No active commitments. <AppLink href={urls.createCommitment()}>Add one</AppLink>.
        </p>
      )}
    </Disclose>
  );
}

function CommitmentTarget({ item }: { item: DashboardCommitment }) {
  const tags = useTags();
  const { aggregation_type: kind, target } = item.commitment;
  if (kind === "project") {
    return (
      <AppLink className="commit-target text-red" href={urls.updateProject(target.id)}>
        {target.name}
      </AppLink>
    );
  }
  if (kind === "subproject") {
    return (
      <AppLink className="commit-target text-blue" href={urls.updateSubproject(target.id)}>
        {target.name}
      </AppLink>
    );
  }
  if (kind === "context") {
    return (
      <AppLink className="commit-target text-orange" href={urls.updateContext(target.id)}>
        {target.name}
      </AppLink>
    );
  }
  const color = tags.data?.find((tag) => tag.id === target.id)?.color;
  return (
    <AppLink
      className="commit-target tag-chip"
      href={urls.updateTag(target.id)}
      style={color ? ({ "--tag": color } as CSSProperties) : undefined}
    >
      {target.name}
    </AppLink>
  );
}

function CommitmentBand({ item }: { item: DashboardCommitment }) {
  const { progress, streak, commitment } = item;
  const unit = progress.commitment_type === "time" ? "m" : "";
  const pct = Math.round(progress.percentage);
  return (
    <article className="band commit">
      <header className="commit-head">
        <CommitmentTarget item={item} />{" "}
        <span className="commit-kind">({AGGREGATION_LABEL[commitment.aggregation_type] ?? commitment.aggregation_type})</span>{" "}
        <span className="commit-period">{progress.period}</span>
      </header>
      <p className="commit-figures">
        <span className="commit-actual">{Math.round(progress.actual)}</span>{" "}
        <span className="commit-goal">
          / {progress.target}
          {progress.commitment_type === "time" ? "m" : " sessions"}
        </span>{" "}
        <span className="commit-pct">{pct}%</span>
      </p>
      <div className="meter">
        <div className={`meter-fill ${progress.status}`} style={{ width: `${pct}%` }} />
      </div>
      {commitment.banking_enabled ? (
        <div className="bank-row">
          <div className="bank-cell">
            <span className="bank-label">Bank (reconciled)</span>
            <span className={`bank-value ${progress.balance >= 0 ? "text-green" : "text-red"}`}>
              {signed(progress.balance)}
              {unit}
            </span>
          </div>
          <div className="bank-cell">
            <span className="bank-label">This period (unbanked)</span>
            <span className={`bank-value ${progress.current_surplus >= 0 ? "text-green" : "text-red"}`}>
              {signed(progress.current_surplus)}
              {unit}
            </span>
          </div>
        </div>
      ) : null}
      <div className="streak-row">
        <Icon icon={faFire} className={`streak-flame${streak.current_streak ? " is-hot" : ""}`} />
        <span className="streak-count">
          {streak.current_streak} period{streak.current_streak === 1 ? "" : "s"}
        </span>
        <div className="period-strip">
          {streak.periods.map((period) => {
            const state = period.is_current ? "current" : period.saved_by_bank ? "banked" : period.met ? "met" : "missed";
            const title = `${Math.round(period.actual)}/${period.target}${
              period.saved_by_bank ? " (bank covered deficit)" : period.is_current ? " — current period" : ""
            }`;
            return (
              <span key={period.period_start} className={`period-cell ${state}`} title={title}>
                <Icon icon={period.is_current ? faHourglassHalf : period.met ? faCheck : faTimes} />
              </span>
            );
          })}
        </div>
      </div>
    </article>
  );
}
