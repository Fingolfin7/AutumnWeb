import { useId, useState } from "react";
import type { Commitment } from "@/api/types";
import { formatDate, formatDuration } from "@/lib/format";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { useUpdateCommitment } from "./api";

export function hasPendingChange(commitment: Commitment) {
  return !!commitment.pending_revision && Object.keys(commitment.pending_revision.changes).length > 0;
}

/** Restoring the live definition cancels queued edits through the existing API. */
export function liveDefinition(commitment: Commitment) {
  return { target_value: commitment.target_value, banking_enabled: commitment.banking_enabled, max_balance: commitment.max_balance, min_balance: commitment.min_balance, ...commitment.filters };
}

export function QuickTarget({ commitment }: { commitment: Commitment }) {
  const [editing, setEditing] = useState(false);
  const [target, setTarget] = useState("");
  const id = useId();
  const update = useUpdateCommitment(commitment.id);
  const toast = useToast();
  const pending = commitment.pending_revision;
  const timeBased = commitment.commitment_type === "time";
  const value = (amount: number) => timeBased ? formatDuration(amount) : `${amount} sessions`;
  const save = (cancel = false) => {
    if (!cancel && (!Number.isInteger(Number(target)) || Number(target) < 1)) return;
    update.mutate({ body: cancel ? liveDefinition(commitment) : { target_value: Number(target) }, version: commitment.version }, {
      onSuccess: () => { setEditing(false); toast.success(cancel ? "Pending changes cancelled." : "Target change saved for the next period."); },
      onError: (error) => toast.error(errorMessage(error)),
    });
  };
  return <>
    <p className="commitment-readable"><strong>{value(commitment.current_period.accrued)}</strong> of <strong>{value(commitment.current_period.target)}</strong> {commitment.period === "weekly" ? "this week" : "this period"}<br />{value(Math.max(0, commitment.current_period.target - commitment.current_period.accrued))} left · resets {formatDate(commitment.current_period.end)}</p>
    {editing ? <form className="commitment-quick-target" onSubmit={(event) => { event.preventDefault(); save(); }}><div className="field"><label htmlFor={id}>Target ({timeBased ? "minutes" : "sessions"})</label><input className="input" id={id} type="number" min="1" step="1" required value={target} onChange={(event) => setTarget(event.target.value)} /></div><button className="btn btn--secondary" disabled={update.isPending}>Save target</button><button className="btn btn--quiet" type="button" onClick={() => setEditing(false)}>Cancel</button></form> : <button className="btn btn--quiet" type="button" onClick={() => { setTarget(String(pending?.changes.target_value ?? commitment.target_value)); setEditing(true); }}>Edit target</button>}
    {hasPendingChange(commitment) ? <div className="commitment-pending" role="status"><span>{pending?.changes.target_value !== undefined ? `${pending.changes.target_value} ${timeBased ? "min" : "sessions"}` : "Updated settings"} from {formatDate(pending!.effective_from)}</span><button type="button" className="btn btn--quiet" disabled={update.isPending} onClick={() => save(true)}>Cancel pending change</button></div> : null}
  </>;
}
