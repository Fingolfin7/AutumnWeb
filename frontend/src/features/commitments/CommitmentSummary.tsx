import { useState, type ReactNode } from "react";
import { Sheet } from "@/components/Sheet";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import type { Commitment } from "@/api/types";
import { formatDate, formatDuration } from "@/lib/format";
import { useUpdateCommitment } from "./api";
import { CommitmentForm } from "./CommitmentForm";
import { CommitmentMeter } from "./CommitmentMeter";
import { hasPendingChange, liveDefinition } from "./display";

/** The same quiet row, disclosure and complete editor on Today, Review and projects. */
export function CommitmentSummary({ commitment: c, showTarget = true, compact = false, children }: { commitment: Commitment; showTarget?: boolean; compact?: boolean; children?: ReactNode }) {
  const [editing, setEditing] = useState(false);
  const update = useUpdateCommitment(c.id);
  const toast = useToast();
  const pending = c.pending_revision;
  const amount = (value: number) => c.commitment_type === "time" ? formatDuration(value) : `${Math.round(value)} session${Math.round(value) === 1 ? "" : "s"}`;
  const targetClass = c.target.kind === "project" ? "text-red" : c.target.kind === "subproject" ? "text-blue" : "text-orange";
  const content = <>
    {showTarget && !compact ? <header className="commitment-summary-heading"><AppLink className={targetClass} href={urls.updateCommitment(c.id)}>{c.target.name}</AppLink><span>{c.period}</span></header> : null}
    {!c.active ? <p className="muted">Commitment paused</p> : null}
    <CommitmentMeter commitment={c} />
    <div className="commitment-summary-actions"><button className="btn btn--quiet" type="button" onClick={() => setEditing(true)}>Edit commitment</button><span>Resets {formatDate(c.current_period.end)}</span></div>
    {editing ? <Sheet open onClose={() => setEditing(false)} title={`Commitment · ${c.target.name}`} className="commitment-target-sheet"><CommitmentForm mode="edit" commitment={c} onClose={() => setEditing(false)} /></Sheet> : null}
    {hasPendingChange(c) ? <div className="commitment-pending" role="status"><span>{pending?.changes.target_value !== undefined ? amount(Number(pending.changes.target_value)) : "Updated settings"} from {formatDate(pending!.effective_from)}</span><button type="button" className="btn btn--quiet" disabled={update.isPending} onClick={() => update.mutate({ body: liveDefinition(c), version: c.version }, { onSuccess: () => toast.success("Pending changes cancelled."), onError: error => toast.error(errorMessage(error)) })}>Cancel pending change</button></div> : null}
    <details className="commitment-details"><summary>Balance & details</summary>
      <p>{c.banking_enabled ? `${amount(Math.abs(c.balance))} ${c.balance < 0 ? "owed" : "carried over"}; ${amount(Math.abs(c.current_surplus))} ${c.current_surplus < 0 ? "below" : "above"} this period’s target.` : "Time carryover is off."}</p>
      {children}
      <AppLink className="btn btn--quiet" href={urls.updateCommitment(c.id)}>Full commitment page</AppLink>
    </details>
  </>;
  return compact ? <details className="commitment-summary commitment-summary--compact"><summary><span className={targetClass} title={c.target.name}>{c.target.name}</span><strong>{amount(c.current_period.accrued)} <span>/ {amount(c.current_period.target)}</span></strong></summary>{content}</details> : <article className="commitment-summary">{content}</article>;
}
