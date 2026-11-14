import { useEffect, useRef, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { faCloudUploadAlt, faWifi } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { seedSynced } from "@/api/meta";
import { useInvalidate } from "@/api/sync";
import { describeOp, flushQueue, hasUnsavedChanges, isFlushing, onSynced, queuedOps, subscribe } from "@/lib/offlineQueue";
import { pluralize } from "@/lib/format";
import { subscribeNoteDrafts, syncNoteDrafts, waitingNoteDrafts } from "@/lib/noteDrafts";
import { useOnline } from "@/lib/useOnline";
import { isUnreachable, subscribeUnreachable } from "./savedData";
import { useToast } from "./toasts";

const RETRY_MS = 20_000;

/* Replays what was queued while Autumn was unreachable (timer starts and
   stops, logged sessions, new projects and subprojects), then sends
   timer notes still only on this device (lib/noteDrafts): at load, when the
   connection returns, when the tab comes back, and every 20 s while anything
   is waiting. Shows a small pill while offline or unsynced. */
export function OfflineSync() {
  const ops = useSyncExternalStore(subscribe, queuedOps);
  /* No connection, or one that can't reach Autumn. */
  const unreachable = useSyncExternalStore(subscribeUnreachable, isUnreachable);
  const online = useOnline() && !unreachable;
  const unsaved = useSyncExternalStore(subscribe, hasUnsavedChanges);
  const invalidate = useInvalidate();
  const client = useQueryClient();
  const toast = useToast();
  useEffect(() => onSynced((op, record) => seedSynced(client, op, record)), [client]);
  const waiting = ops.length + useSyncExternalStore(subscribeNoteDrafts, waitingNoteDrafts);
  /* Each synced op changes `waiting` and re-runs the effect mid-flush, so
     only unmounting (not a re-run) should silence the report. */
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!waiting) return;
    const flush = () => {
      /* Already running: its own caller reports it. */
      if (document.hidden || !navigator.onLine || isFlushing()) return;
      void flushQueue()
        .then((report) => {
          if (!mounted.current) return;
          if (report.synced || report.dropped.length) {
            invalidate("timers", "sessions", "projects");
            if (report.synced && !report.remaining) toast.success(`Synced ${pluralize(report.synced, "offline change")}.`);
          }
          for (const drop of report.dropped) {
            /* What was typed must not go with it: the message stays up and
               offers the note. */
            const note = (drop.op.kind === "stop" ? drop.op.note : drop.op.kind === "session" ? (drop.op.body.note as string | null | undefined) : null)?.trim();
            toast.error(
              `Couldn't sync the offline ${describeOp(drop.op)}: ${drop.message}`,
              note ? { duration: 0, action: { label: "Copy its note", run: () => void navigator.clipboard?.writeText(note) } } : undefined,
            );
          }
        })
        .then(syncNoteDrafts)
        .then((notes) => {
          if (!mounted.current || !(notes.saved.length + notes.merged.length)) return;
          invalidate("timers", "sessions");
          for (const draft of notes.merged) {
            toast.info(`The ${draft.project} note changed elsewhere, so what you wrote on this device was added below it.`);
          }
        });
    };
    flush();
    const id = window.setInterval(flush, RETRY_MS);
    window.addEventListener("online", flush);
    document.addEventListener("visibilitychange", flush);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("online", flush);
      document.removeEventListener("visibilitychange", flush);
    };
  }, [waiting, invalidate, toast]);

  if (online && !waiting) return null;
  return (
    <div className="offline-banner" role="status">
      {unsaved ? (
        <>Offline changes are only saved in this tab. Keep it open until they sync; reloading or closing it may lose them.</>
      ) : online ? (
        <>
          <Icon icon={faCloudUploadAlt} /> {pluralize(waiting, "change")} waiting to sync
        </>
      ) : (
        <>
          <Icon icon={faWifi} /> Offline{waiting ? ` · ${pluralize(waiting, "change")} to sync` : " · saved data"}
        </>
      )}
    </div>
  );
}
