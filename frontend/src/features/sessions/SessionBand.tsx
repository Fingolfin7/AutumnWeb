import { useEffect, useRef, useState } from "react";
import { faEllipsisH, faPen, faRedo, faSlidersH, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { ConfirmDialog, Sheet } from "@/components/Sheet";
import { SessionNote } from "@/components/SessionNote";
import { useNoteDraft } from "@/lib/noteDraft";
import { NoteEditor } from "@/components/NoteEditor";
import { api, unwrap } from "@/api/client";
import { AppLink, urls } from "@/app/links";
import { dayPortions } from "@/lib/sessions";
import { formatDate, formatDuration, localDateKey, formatShortDate, formatTime, formatTimeRange } from "@/lib/format";
import { useStartTimer } from "@/features/timers/api";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { useDeleteSession, useUpdateSession, type SessionRow } from "./api";

/* Journal row shared with Today. Actions are explicit; a left swipe is an
   optional shortcut that reveals the same controls without moving the prose. */
export function SessionBand({ session, showDate, hideProject = false, onEditNote, onNoteSaved, search, day }: { search?: string; day?: string; session: SessionRow; showDate?: boolean; hideProject?: boolean; onEditNote?: (session: SessionRow) => void; onNoteSaved?: (session: SessionRow) => void }) {
  const start = useStartTimer();
  const remove = useDeleteSession();
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [editing, setEditing] = useState<SessionRow | null>(null);
  const row = useRef<HTMLLIElement>(null);
  const editNote = () => {
    onEditNote?.(session);
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
        <div className="journal-identity">
        <AppLink className="session-project" title={session.project.name} href={urls.updateProject(session.project.id)}>{session.project.name}</AppLink>
      <div className="journal-meta">
        {session.subproject_allocations.map((sub) => <AppLink key={sub.subproject_id} className="journal-subproject" href={urls.updateSubproject(sub.subproject_id)}>{sub.name}</AppLink>)}
        {showDate ? <span>{formatShortDate(session.start)}</span> : null}
        <span className="journal-time">{formatTimeRange(session.start, session.end)}</span>
        {crossesDst(session) ? <span className="badge-dst" title="Session crosses a daylight savings transition">DST</span> : null}
      </div>
        </div>
        <span className={`journal-duration${!session.duration_minutes ? " is-zero" : ""}`}>{formatDuration(day ? dayPortions(session).find((part) => part.date === day)?.minutes ?? session.duration_minutes : session.duration_minutes)}</span>
        <div className="journal-row-actions">
          <button className="btn btn--quiet" type="button" aria-label="Edit" onClick={editNote}>Edit</button>
          <button className="btn-icon journal-delete" type="button" aria-label="Delete session" title="Delete session" onClick={() => setConfirming(true)}><Icon icon={faTrash} /></button>
        </div>
        <button className="btn-icon journal-overflow" type="button" aria-label="Session actions" aria-expanded={actionsOpen} aria-controls={`actions-${session.id}`} onClick={() => setActionsOpen(!actionsOpen)}><Icon icon={faEllipsisH} /></button>
      </div>
      {dayPortions(session).length > 1 ? <p className="journal-day-split">{dayPortions(session).map((part) => `${formatDuration(part.minutes)} ${part.date === localDateKey(new Date()) ? "today" : part.date === localDateKey(new Date(Date.now() - 86400000)) ? "yesterday" : formatShortDate(part.date)}`).join(" · ")}</p> : null}
      {session.match === "related" ? <p className="journal-match-reason">{session.match_passage ? "Related meaning in this passage" : "Related meaning in the project or session note"}</p> : search ? <p className="journal-match-reason">Matches “{search}”</p> : null}
      {!session.note && !session.note_html && !editing ? <button className="btn btn--quiet journal-add-note" type="button" onClick={editNote}>Add a note</button> : null}
      {editing ? <InlineNoteWriter session={editing} onDone={() => setEditing(null)} onSaved={onNoteSaved} /> : <SessionNote search={search} id={`note-${session.id}`} html={session.note_html} text={session.note} onEdit={editNote} passage={session.match_passage} identity={<><span>{formatShortDate(session.end)}</span>{!hideProject ? <span className="text-red">{session.project.name}</span> : null}</>} />}

      {actionsOpen ? <Sheet open onClose={() => setActionsOpen(false)} title="Session actions" className="session-actions-sheet">
        <p className="session-action-context">{session.project.name} · {formatDuration(session.duration_minutes)}</p>
        <div className="journal-actions" id={`actions-${session.id}`}>
        <button className="btn btn--quiet" type="button" onClick={editNote}><Icon icon={faPen} /> Edit note</button>
        <AppLink className="btn btn--quiet" href={urls.updateSession(session.id)}><Icon icon={faSlidersH} /> Edit session</AppLink>
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

function InlineNoteWriter({ session, onDone, onSaved }: { session: SessionRow; onDone: () => void; onSaved?: (session: SessionRow) => void }) {
  const update = useUpdateSession();
  const toast = useToast();
  const draft = useNoteDraft({
    draftKey: `session:${session.uuid ?? session.id}`, text: session.note ?? "", version: session.version,
    save: async (note, version) => {
      const saved = await update.mutateAsync({ session, body: { note }, version });
      onSaved?.(saved);
      return saved;
    },
  });
  const complete = async () => {
    if (!(await draft.flush())) return;
    if (onSaved) {
      // PATCH returns plain text; retain the sanitized rendering as well when
      // this entry no longer matches its list's search.
      try {
        const rendered = await unwrap(api.GET("/api/v2/sessions/{session_id}", {
          params: { path: { session_id: session.id }, query: { include: "note_html" } },
        }));
        if (rendered.note === draft.value) onSaved(rendered);
      } catch { /* The successfully saved plain note stays available. */ }
    }
    onDone();
    toast.success("Note saved.");
  };
  return <form className="journal-note-edit fields" onSubmit={(event) => {
    event.preventDefault();
    void complete();
  }}>
    <NoteEditor sessionTitle={`${session.project.name} · ${formatDate(session.end)} · ${formatDuration(session.duration_minutes)}`} value={draft.value} onChange={draft.change} autoFocus rows={4} onDone={draft.flush} saveStatus={draft.status} onRetry={() => void draft.flush()} onBlur={() => void draft.flush()} />
    <div className="journal-edit-actions">
      <button className="btn btn--primary" aria-busy={update.isPending}>Done</button>
      {draft.value !== (session.note ?? "") ? <button className="btn btn--quiet" type="button" onClick={() => { draft.change(session.note ?? ""); void draft.flush(); }}>Undo note edits</button> : null}
      <AppLink className="btn btn--quiet" href={urls.updateSession(session.id)}>Time & allocation</AppLink>
    </div>
  </form>;
}
