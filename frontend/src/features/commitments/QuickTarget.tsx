import { useState } from "react";
import { Sheet } from "@/components/Sheet";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import type { Commitment } from "@/api/types";
import { formatDate, formatDuration } from "@/lib/format";
import { useUpdateCommitment } from "./api";
import { CommitmentForm } from "./CommitmentForm";
import { CommitmentMeter } from "./CommitmentMeter";
import { hasPendingChange, liveDefinition } from "./display";

export function QuickTarget({ commitment }: { commitment: Commitment }) {
  const [editing, setEditing] = useState(false);
  const update = useUpdateCommitment(commitment.id);
  const toast = useToast();
  const pending = commitment.pending_revision;
  const value = (amount: number) => commitment.commitment_type === "time" ? formatDuration(amount) : `${amount} sessions`;
  return <>
    <CommitmentMeter commitment={commitment} />
    <button className="btn btn--quiet" type="button" onClick={() => setEditing(true)}>Edit commitment</button>
    {editing ? <Sheet open onClose={() => setEditing(false)} title={`Commitment · ${commitment.target.name}`} className="commitment-target-sheet"><CommitmentForm mode="edit" commitment={commitment} onClose={() => setEditing(false)} /></Sheet> : null}
    {hasPendingChange(commitment) ? <div className="commitment-pending" role="status"><span>{pending?.changes.target_value !== undefined ? value(Number(pending.changes.target_value)) : "Updated settings"} from {formatDate(pending!.effective_from)}</span><button type="button" className="btn btn--quiet" disabled={update.isPending} onClick={() => update.mutate({ body: liveDefinition(commitment), version: commitment.version }, { onSuccess: () => toast.success("Pending changes cancelled."), onError: error => toast.error(errorMessage(error)) })}>Cancel pending change</button></div> : null}
  </>;
}
