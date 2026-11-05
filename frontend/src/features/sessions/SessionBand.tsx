import { useLocation } from "react-router";
import { useEffect, useRef, useState } from "react";
import { faEllipsisH, faPen, faRedo, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { ConfirmDialog, Sheet } from "@/components/Sheet";
import { SessionNote } from "@/components/SessionNote";
import { useNoteDraft } from "@/lib/noteDraft";
import { NoteEditor } from "@/components/NoteEditor";
import { AppLink, urls } from "@/app/links";
import { formatDuration, formatShortDate, formatTime, formatTimeRange } from "@/lib/format";
import { useStartTimer } from "@/features/timers/api";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { useDeleteSession, useUpdateSession, type SessionRow } from "./api";

/* Journal row shared with Today. Actions are explicit; a left swipe is an
   optional shortcut that reveals the same controls without moving the prose. */
export function SessionBand({ session, showDate, hideProject = false }: { session: SessionRow; showDate?: boolean; hideProject?: boolean }) {
  const location = useLocation();
  hideProject = hideProject || location.pathname === urls.updateProject(session.project.id);
  const start = useStartTimer();
  const remove = useDeleteSession();
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [editing, setEditing] = useState<SessionRow | null>(null);
  const row = useRef<HTMLLIElement>(null);
  const editNote = () => {
    setEditing(session);
    setActionsOpen(false);
  };

  useEffect(() => {
    const node = row.current;
    if (!node) return;
    let origin: { x: number; y: number } | null = null;
    const begin = (event: TouchEvent) => {
      const point = event.touches[0];
      origin = point ? { x: point.clientX, y: point.clientY } : null;
    };
    const movingLeft = (point: Touch) => {
      if (!origin) return false;
      const dx = origin.x - point.clientX;
      const dy = Math.abs(origin.y - point.clientY);
      return dx > 10 && dx > dy * 1.5 && dy < 35;
    };
    const move = (event: TouchEvent) => {
      const point = event.touches[0];
      // Consume a horizontal gesture before native scrolling can swallow its next tap.
      if (point && movingLeft(point) && event.cancelable) event.preventDefault();
    };
    const finish = (event: TouchEvent) => {
      const point = event.changedTouches[0];
      if (point && origin && movingLeft(point) && origin.x - point.clientX > 60) {
        if (event.cancelable) event.preventDefault();
        setActionsOpen(true);
      }
      origin = null;
    };
    const cancel = () => { origin = null; };
    node.addEventListener("touchstart", begin, { passive: true });
    node.addEventListener("touchmove", move, { passive: false });
    node.addEventListener("touchend", finish);
    node.addEventListener("touchcancel", cancel);
    return () => {
      node.removeEventListener("touchstart", begin);
      node.removeEventListener("touchmove", move);
      node.removeEventListener("touchend", finish);
      node.removeEventListener("touchcancel", cancel);
    };
  }, []);

  const restart = () => {
    const subprojects = session.subproject_allocations.map((a) => ({ id: a.subproject_id, name: a.name }));
    start.mutate(
      {
        project_id: session.project.id,
        subproject_ids: subprojects.map((s) => s.id),
        optimistic: { projectName: session.project.name, subprojects },
      },
      {
        onSuccess: () => { setActionsOpen(false); toast.success(`Started ${session.project.name}.`); },
        onError: (error) => toast.error(`Couldn't start the timer: ${errorMessage(error)}`),
      },
    );
  };

  return (
    <li ref={row} className="band journal-entry" id={`session-${session.id}`}>
      <div className="journal-heading">
        {hideProject ? <span className="session-project journal-entry-date">{formatShortDate(session.end)}</span> : <AppLink className="session-project" href={urls.updateProject(session.project.id)}>{session.project.name}</AppLink>}
        <span className="journal-duration">{formatDuration(session.duration_minutes)}</span>
        <div className="journal-row-actions">
          <button className="btn btn--quiet" type="button" onClick={editNote}><Icon icon={faPen} /> Edit note</button>
          <button className="btn btn--quiet" type="button" onClick={restart} disabled={start.isPending}><Icon icon={faRedo} /> Restart</button>
          <button className="btn btn--quiet journal-delete" type="button" onClick={() => setConfirming(true)}><Icon icon={faTrash} /> Delete session</button>
        </div>
        <button className="btn-icon journal-overflow" type="button" aria-label="Session actions" aria-expanded={actionsOpen} aria-controls={`actions-${session.id}`} onClick={() => setActionsOpen(!actionsOpen)}><Icon icon={faEllipsisH} /></button>
      </div>
      <div className="journal-meta">
        {session.subproject_allocations.map((sub) => <AppLink key={sub.subproject_id} className="journal-subproject" href={urls.updateSubproject(sub.subproject_id)}>{sub.name}</AppLink>)}
        {showDate ? <span>{formatShortDate(session.end)}</span> : null}
        <span className="journal-time">{formatTimeRange(session.start, session.end)}</span>
        {crossesDst(session) ? <span className="badge-dst" title="Session crosses a daylight savings transition">DST</span> : null}
      </div>
      {editing ? <InlineNoteWriter session={editing} onDone={() => setEditing(null)} /> : <SessionNote id={`note-${session.id}`} html={session.note_html} text={session.note} onEdit={editNote} identity={<><span>{formatShortDate(session.end)}</span>{!hideProject ? <span className="text-red">{session.project.name}</span> : null}</>} />}

      {actionsOpen ? <Sheet open onClose={() => setActionsOpen(false)} title="Session actions" className="session-actions-sheet">
        <p className="session-action-context">{session.project.name} · {formatDuration(session.duration_minutes)}</p>
        <div className="journal-actions" id={`actions-${session.id}`}>
        <button className="btn btn--quiet" type="button" onClick={editNote}><Icon icon={faPen} /> Edit note</button>
        <AppLink className="btn btn--quiet" href={urls.updateSession(session.id)}><Icon icon={faPen} /> Edit session</AppLink>
        <button className="btn btn--quiet" type="button" onClick={restart} disabled={start.isPending}><Icon icon={faRedo} /> Restart</button>
        <button className="btn btn--quiet journal-delete" type="button" onClick={() => { setActionsOpen(false); setConfirming(true); }}><Icon icon={faTrash} /> Delete session</button>
        </div>
      </Sheet> : null}
      <ConfirmDialog
        open={confirming}
        title="Delete this session?"
        body={
          <>
            {session.project.name}, {formatDuration(session.duration_minutes)} ending {formatShortDate(session.end)} at {formatTime(session.end, false)}.
            You can undo straight after.
          </>
        }
        confirmLabel="Delete"
        danger
        busy={remove.isPending}
        onClose={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false);
          remove.mutate(session);
        }}
      />
    </li>
  );
}

/* Elapsed wall-clock vs local-clock difference: a DST change in between
   makes the clock times disagree with the duration by the offset change. */
function crossesDst(session: SessionRow): boolean {
  if (!session.end) return false;
  const start = new Date(session.start);
  const end = new Date(session.end);
  return start.getTimezoneOffset() !== end.getTimezoneOffset();
}

function InlineNoteWriter({ session, onDone }: { session: SessionRow; onDone: () => void }) {
  const update = useUpdateSession();
  const toast = useToast();
  const draft = useNoteDraft({
    draftKey: `session:${session.uuid ?? session.id}`, text: session.note ?? "", version: session.version,
    save: (note, version) => update.mutateAsync({ session, body: { note }, version }),
  });
  return <form className="journal-note-edit fields" onSubmit={(event) => {
    event.preventDefault();
    void draft.flush().then((ok) => { if (ok) { onDone(); toast.success("Note saved."); } });
  }}>
    <NoteEditor value={draft.value} onChange={draft.change} autoFocus rows={4} saveStatus={draft.status} onRetry={() => void draft.flush()} onBlur={() => void draft.flush()} />
    <div className="journal-edit-actions">
      <button className="btn btn--primary" disabled={update.isPending}>{update.isPending ? "Saving…" : "Done"}</button>
      <button className="btn btn--quiet" type="button" onClick={onDone}>Close editor</button>
      <AppLink className="btn btn--quiet" href={urls.updateSession(session.id)}>Time & allocation</AppLink>
    </div>
  </form>;
}
