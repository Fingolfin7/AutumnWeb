import { Sheet } from "@/components/Sheet";
import { CommitmentMeter } from "./CommitmentMeter";
import { TargetInput } from "./TargetInput";
import { AppLink, urls } from "@/app/links";
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
    <CommitmentMeter commitment={commitment} />
    <Sheet open={editing} onClose={() => setEditing(false)} title={`Commitment · ${commitment.target.name}`} className="commitment-target-sheet"><form className="commitment-quick-target" onSubmit={(event) => { event.preventDefault(); save(); }}><div className="field"><label htmlFor={id}>Target</label><TargetInput id={id} time={timeBased} value={target} onChange={setTarget} /><small className="muted" id={`${id}-help`}>{timeBased ? "Hours and minutes, e.g. 3h 30m" : "Number of sessions"}</small></div><div className="form-actions"><button className="btn btn--primary" disabled={update.isPending || !Number.isInteger(Number(target)) || Number(target) < 1}>Save target</button></div><span className="muted">Applies from {formatDate(pending?.effective_from ?? commitment.current_period.end)}</span><button className="btn btn--quiet" type="button" onClick={() => setEditing(false)}>Cancel</button><AppLink className="btn btn--quiet" href={urls.updateCommitment(commitment.id)}>Period and rules</AppLink></form></Sheet><button className="btn btn--quiet" type="button" onClick={() => { setTarget(String(pending?.changes.target_value ?? commitment.target_value)); setEditing(true); }}>Edit commitment</button>
    {hasPendingChange(commitment) ? <div className="commitment-pending" role="status"><span>{pending?.changes.target_value !== undefined ? value(Number(pending.changes.target_value)) : "Updated settings"} from {formatDate(pending!.effective_from)}</span><button type="button" className="btn btn--quiet" disabled={update.isPending} onClick={() => save(true)}>Cancel pending change</button></div> : null}
  </>;
}
