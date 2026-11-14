import { useState } from "react";
import { ConfirmDialog } from "@/components/Sheet";
import { useToast } from "@/app/toasts";
import { dependentsOf, describeOp, discard } from "@/lib/offlineQueue";

/* Throws away a project or subproject created offline that hasn't synced,
   after saying what else queued goes with it (its subprojects, timers and
   logged sessions). */
export function DiscardPending({ id, name }: { id: number; name: string }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const others = open ? dependentsOf(String(id)).filter((op) => op.kind !== "stop") : [];
  return (
    <>
      <button type="button" className="btn btn--quiet" onClick={() => setOpen(true)}>
        Discard
      </button>
      <ConfirmDialog
        open={open}
        title={`Discard ${name}?`}
        body={
          <>
            It was saved on this device and hasn't synced.
            {others.length ? ` This also discards the ${others.map(describeOp).join(", ")}.` : null}
          </>
        }
        confirmLabel="Discard"
        danger
        onClose={() => setOpen(false)}
        onConfirm={() => {
          discard(String(id));
          setOpen(false);
          toast.info(`Discarded ${name}.`);
        }}
      />
    </>
  );
}
