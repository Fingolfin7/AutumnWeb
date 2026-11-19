import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { faEllipsisH, faPen, faRedo, faSlidersH, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { ConfirmDialog, Sheet } from "@/components/Sheet";
import { NoteEditor } from "@/components/NoteEditor";
import { SessionNote } from "@/components/SessionNote";
import { AppLink, urls } from "@/app/links";
import { formatJournalDate, formatJournalDuration, formatShortDate, formatTime, formatTimeRange } from "@/lib/format";
import { useStartTimer } from "@/features/timers/api";
import { useToast } from "@/app/toasts";
import { ApiError, errorMessage } from "@/api/errors";
import { useDeleteSession, useUpdateSession, type SessionRow } from "./api";

/** A day of the journal: its heading shares the rows' duration column. */
export function JournalDay({ date, minutes, children }: { date: string; minutes: number; children: ReactNode }) {
  return (
    <div className="day-group">
      <header className="day-head">
        <span className="day-date">{formatJournalDate(date)}</span>
        <span className="day-total">{formatJournalDuration(minutes)}</span>
      </header>
      <ul className="band-list">{children}</ul>
    </div>
  );
}

/* One journal row, on Sessions and Home: project and duration, then
   subprojects and times, then the note read in full. Desktop shows the
   actions on hover; a phone opens them from "…" or a left swipe. `showDate`
   adds the day for rows outside a day group; `search` marks matched words. */
export function SessionBand({ session, showDate, search }: { session: SessionRow; showDate?: boolean; search?: string }) {
  const start = useStartTimer();
  const remove = useDeleteSession();
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const row = useRef<HTMLLIElement>(null);
  const pending = !!session.pending_sync;
  const hasNote = !!(session.note || session.note_html);

  useEffect(() => {
    const node = row.current;
    if (!node || pending) return;
    let origin: { x: number; y: number } | null = null;
    const begin = (event: TouchEvent) => {
      const point = event.touches[0];
      origin = point ? { x: point.clientX, y: point.clientY } : null;
    };
    const finish = (event: TouchEvent) => {
      const point = event.changedTouches[0];
      if (point && origin) {
        const dx = origin.x - point.clientX;
        const dy = Math.abs(origin.y - point.clientY);
        if (dx > 60 && dx > dy * 1.5 && dy < 35) setActionsOpen(true);
      }
      origin = null;
    };
    node.addEventListener("touchstart", begin, { passive: true });
    node.addEventListener("touchend", finish);
    return () => {
      node.removeEventListener("touchstart", begin);
      node.removeEventListener("touchend", finish);
    };
  }, [pending]);

  const editNote = () => {
    setActionsOpen(false);
    setEditing(true);
  };

  const restart = () => {
    const subprojects = session.subproject_allocations.map((a) => ({ id: a.subproject_id, name: a.name }));
    start.mutate(
      {
        project_id: session.project.id,
        subproject_ids: subprojects.map((s) => s.id),
        optimistic: { projectName: session.project.name, subprojects },
      },
      {
        onSuccess: () => {
          setActionsOpen(false);
          toast.success(`Started ${session.project.name}.`);
        },
        onError: (error) => toast.error(`Couldn't start the timer: ${errorMessage(error)}`),
      },
    );
  };

  const actionsId = `actions-${session.id}`;
  const overflow = (className: string) => (
    <button className={`btn-icon journal-overflow ${className}`} type="button" aria-label="Session actions" title="Session actions" aria-expanded={actionsOpen} aria-controls={actionsId} onClick={() => setActionsOpen(true)}>
      <Icon icon={faEllipsisH} />
    </button>
  );

  return (
    <li ref={row} className="band journal-entry" id={`session-${session.id}`}>
      <div className="journal-heading">
        {pending ? (
          /* Logged offline: nothing on the server to open or edit yet. */
          <span className="session-project">{session.project.name}</span>
        ) : (
          <AppLink className="session-project" title={session.project.name} href={urls.updateProject(session.project.id)}>
            {session.project.name}
          </AppLink>
        )}
        <span className="journal-duration">{formatJournalDuration(session.duration_minutes)}</span>
        <div className="journal-meta">
          {session.subproject_allocations.length ? (
            <span className="journal-subs" title={session.subproject_allocations.map((sub) => sub.name).join(", ")}>
              {session.subproject_allocations.map((sub) =>
                pending ? (
                  <span key={sub.subproject_id} className="journal-subproject">{sub.name}</span>
                ) : (
                  <AppLink key={sub.subproject_id} className="journal-subproject" href={urls.updateSubproject(sub.subproject_id)}>
                    {sub.name}
                  </AppLink>
                ),
              )}
            </span>
          ) : null}
          {showDate ? <span className="journal-time">{formatJournalDate(session.end ?? session.start)}</span> : null}
          <span className="journal-time">{formatTimeRange(session.start, session.end)}</span>
          {crossesDst(session) ? <span className="badge-dst" title="Session crosses a daylight savings transition">DST</span> : null}
          {pending ? <span className="journal-time">Saved offline · waiting to sync</span> : overflow("journal-meta-overflow")}
        </div>
        {!pending ? (
          <div className="journal-row-actions">
            <button className="btn-icon" type="button" aria-label="Edit note" title="Edit note" onClick={editNote}>
              <Icon icon={faPen} />
            </button>
            <button className="btn-icon journal-delete" type="button" aria-label="Delete session" title="Delete session" onClick={() => setConfirming(true)}>
              <Icon icon={faTrash} />
            </button>
            {overflow("")}
          </div>
        ) : null}
      </div>
      {session.match === "related" ? (
        <p className="journal-match-reason">{session.match_passage ? "Related in meaning to this passage" : "Related in meaning to the project or note"}</p>
      ) : null}
      {editing ? (
        <InlineNoteWriter session={session} onDone={() => setEditing(false)} />
      ) : hasNote ? (
        <SessionNote id={`note-${session.id}`} html={session.note_html} text={session.note} passage={session.match_passage} search={search} />
      ) : !pending ? (
        <button className="journal-add-note quiet-link" type="button" onClick={editNote}>Add a note</button>
      ) : null}

      {actionsOpen ? (
        <Sheet open onClose={() => setActionsOpen(false)} title="Session actions" className="session-actions-sheet">
          <p className="session-action-context">
            {session.project.name} · {formatJournalDuration(session.duration_minutes)} · {formatShortDate(session.end)}
          </p>
          <div className="journal-actions" id={actionsId}>
            <button className="btn btn--quiet" type="button" onClick={editNote}><Icon icon={faPen} /> {hasNote ? "Edit note" : "Add a note"}</button>
            <AppLink className="btn btn--quiet" href={urls.updateSession(session.id)}><Icon icon={faSlidersH} /> Edit session</AppLink>
            <button className="btn btn--quiet" type="button" onClick={restart} disabled={start.isPending}><Icon icon={faRedo} /> Restart</button>
            <button className="btn btn--quiet journal-delete" type="button" onClick={() => { setActionsOpen(false); setConfirming(true); }}><Icon icon={faTrash} /> Delete session</button>
          </div>
        </Sheet>
      ) : null}
      <ConfirmDialog
        open={confirming}
        title="Delete this session?"
        body={
          <>
            {session.project.name}, {formatJournalDuration(session.duration_minutes)} ending {formatShortDate(session.end)} at {formatTime(session.end, false)}.
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

/* Edit the note in place. Saves with the version the row was loaded at
   (If-Match), so a change made elsewhere meanwhile is never overwritten:
   the text stays here and the row asks for a reload. */
function InlineNoteWriter({ session, onDone }: { session: SessionRow; onDone: () => void }) {
  const update = useUpdateSession();
  const toast = useToast();
  const [value, setValue] = useState(session.note ?? "");
  const [error, setError] = useState<string | null>(null);
  const save = (event: FormEvent) => {
    event.preventDefault();
    if (value === (session.note ?? "")) return onDone();
    setError(null);
    update.mutate(
      { session, body: { note: value } },
      {
        onSuccess: () => {
          toast.success("Note saved.");
          onDone();
        },
        onError: (failure) =>
          setError(
            failure instanceof ApiError && failure.status === 409
              ? "This session changed elsewhere. Copy your text, then reload to see the latest note."
              : `Couldn't save the note: ${errorMessage(failure)}`,
          ),
      },
    );
  };
  return (
    <form className="journal-note-edit fields" onSubmit={save}>
      <NoteEditor id={`note-edit-${session.id}`} label={null} value={value} onChange={setValue} rows={5} autoFocus error={error} />
      <div className="journal-edit-actions">
        <button className="btn btn--primary" type="submit" aria-busy={update.isPending} disabled={update.isPending}>Save note</button>
        <button className="btn btn--quiet" type="button" onClick={() => { if (value === (session.note ?? "") || window.confirm("Discard your changes to this note?")) onDone(); }}>Cancel</button>
        <AppLink className="btn btn--quiet" href={urls.updateSession(session.id)}>Time &amp; allocation</AppLink>
      </div>
    </form>
  );
}

/* Elapsed wall-clock vs local-clock difference: a DST change in between
   makes the clock times disagree with the duration by the offset change. */
function crossesDst(session: SessionRow): boolean {
  if (!session.end) return false;
  return new Date(session.start).getTimezoneOffset() !== new Date(session.end).getTimezoneOffset();
}
