import { useEffect, useRef, useState, type ReactNode } from "react";
import { faEllipsisH, faPen, faRedo, faSlidersH, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { ConfirmDialog, Sheet } from "@/components/Sheet";
import { SessionNote } from "@/components/SessionNote";
import { useNoteDraft } from "@/lib/noteDraft";
import { NoteEditor } from "@/components/NoteEditor";
import { api, unwrap } from "@/api/client";
import { AppLink, urls } from "@/app/links";
import { dayPortions } from "@/lib/sessions";
import { formatDate, formatDayDate, formatDuration, localDateKey, formatShortDate, formatTime, formatTimeRange } from "@/lib/format";
import { useStartTimer } from "@/features/timers/api";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { useDeleteSession, useUpdateSession, type SessionRow } from "./api";

/** A day of the journal: its heading shares the rows' duration column. Pass
 *  `label` to name the day in words instead of its date. */
export function JournalDay({ date, label, minutes, children }: { date?: string; label?: string; minutes?: number; children?: ReactNode }) {
  return <div className="day-group">
    <header className="day-head">
      <span className="day-date">{label ?? (date ? formatDayDate(date) : "")}</span>
      {minutes !== undefined ? <span className={`day-total${!Math.round(minutes) ? " is-zero" : ""}`}>{formatDuration(minutes)}</span> : null}
    </header>
    {children ? <ul className="band-list">{children}</ul> : null}
  </div>;
}

/** Why a search returned this row: the fields it matched, or its related meaning. */
function matchReason(session: SessionRow, search?: string) {
  if (session.match === "related") return session.match_passage ? "Related in meaning to this passage" : "Related in meaning to the project or note";
  const words = search?.toLowerCase().match(/"[^"]+"|[^\s]+/g)?.map((word) => word.replace(/^"|"$/g, "")) ?? [];
  if (!words.length) return null;
  const has = (text?: string | null) => words.some((word) => text?.toLowerCase().includes(word));
  const fields = [
    has(session.note) ? "the note" : "",
    has(session.project.name) ? "the project name" : "",
    session.subproject_allocations.some((sub) => has(sub.name)) ? "the subproject" : "",
  ].filter(Boolean);
  return `Matches “${search}”${fields.length ? ` in ${fields.join(" and ")}` : ""}`;
}

/* The one journal row, on Today, Sessions and project pages: project and
   duration, then subproject and time on one truncating line, then the note.
   `hideProject` drops the project line where the page already names it, and
   `day` shows a midnight-crossing session's share of that day. A left swipe is
   an optional shortcut to the same actions. */
export function SessionBand({ session, showDate, hideProject = false, hideDuration = false, onEditNote, onNoteSaved, search, day }: { search?: string; day?: string; session: SessionRow; showDate?: boolean; hideProject?: boolean; hideDuration?: boolean; onEditNote?: (session: SessionRow) => void; onNoteSaved?: (session: SessionRow) => void }) {
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

  const portions = dayPortions(session);
  // A midnight session appears in both days. Keep the public anchor on the
  // latest portion, with distinct note/action IDs on its earlier appearances.
  const instance = `${session.id}${day && day !== portions[portions.length - 1]?.date ? `-${day}` : ""}`;
  const minutes = (day ? portions.find((part) => part.date === day)?.minutes : undefined) ?? session.duration_minutes ?? 0;
  const continuation = !!day && day !== localDateKey(new Date(session.start));
  const portionStart = day && day > localDateKey(new Date(session.start)) ? "00:00" : formatTime(session.start);
  const portionEnd = day && session.end && day < localDateKey(new Date(session.end)) ? "24:00" : formatTime(session.end);
  const reason = matchReason(session, search);

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
    <li ref={row} className={`band journal-entry${hideProject ? " journal-entry--in-project" : ""}${continuation ? " journal-entry--continuation" : ""}`} id={`session-${instance}`} data-session-id={session.id}>
      <div className="journal-heading">
        {!hideProject ? <AppLink className="session-project" title={session.project.name} href={urls.updateProject(session.project.id)}>{session.project.name}</AppLink> : null}
        {!hideDuration && !continuation ? <span className={`journal-duration${!Math.round(minutes) ? " is-zero" : ""}`}>{formatDuration(minutes)}</span> : null}
        <div className="journal-meta">
          {session.subproject_allocations.length ? <span className="journal-subs" title={session.subproject_allocations.map((sub) => sub.name).join(", ")}>{session.subproject_allocations.map((sub) => <AppLink key={sub.subproject_id} className="journal-subproject" href={urls.updateSubproject(sub.subproject_id)}>{sub.name}</AppLink>)}</span> : null}
          {showDate ? <span className="journal-time">{formatShortDate(session.start)}</span> : null}
          <span className="journal-time">{day && portions.length > 1 ? `${portionStart}–${portionEnd}` : formatTimeRange(session.start, session.end)}</span>
          {continuation ? <><span className="journal-time">{formatDuration(minutes)}</span><AppLink className="journal-note-origin quiet-link" href={`${urls.sessions()}?start_date=${portions[0]?.date}&end_date=${portions[0]?.date}#session-${session.id}-${portions[0]?.date}`}>note on {formatDayDate(session.start)}</AppLink></> : null}
          {crossesDst(session) ? <span className="badge-dst" title="Session crosses a daylight savings transition">DST</span> : null}
          <button className="btn-icon journal-overflow journal-meta-overflow" type="button" aria-label="Session actions" title="Session actions" aria-expanded={actionsOpen} aria-controls={`actions-${instance}`} onClick={() => setActionsOpen(!actionsOpen)}><Icon icon={faEllipsisH} /></button>
        </div>
        <div className="journal-row-actions">
          <button className="btn-icon journal-action" type="button" aria-label="Edit note" title="Edit note" onClick={editNote}><Icon icon={faPen} /></button>
          <button className="btn-icon journal-action journal-delete" type="button" aria-label="Delete session" title="Delete session" onClick={() => setConfirming(true)}><Icon icon={faTrash} /></button>
          <button className="btn-icon journal-overflow" type="button" aria-label="Session actions" title="Session actions" aria-expanded={actionsOpen} aria-controls={`actions-${instance}`} onClick={() => setActionsOpen(!actionsOpen)}><Icon icon={faEllipsisH} /></button>
        </div>
      </div>
      {!continuation && portions.length > 1 ? <p className="journal-day-split">{portions.map((part) => `${formatDuration(part.minutes)} on ${formatDayDate(part.date)}`).join(" · ")}</p> : null}
      {reason ? <p className="journal-match-reason">{reason}</p> : null}
      {!continuation && !session.note && !session.note_html && !editing ? <button className="btn btn--quiet journal-add-note" type="button" onClick={editNote}>Add a note</button> : null}
      {editing ? <InlineNoteWriter session={editing} onDone={() => setEditing(null)} onSaved={onNoteSaved} /> : !continuation ? <SessionNote search={search} id={`note-${instance}`} html={session.note_html} text={session.note} onEdit={editNote} passage={session.match_passage} identity={<><span>{formatShortDate(session.end)}</span>{!hideProject ? <span className="text-red">{session.project.name}</span> : null}</>} /> : null}

      {actionsOpen ? <Sheet open onClose={() => setActionsOpen(false)} title="Session actions" className="session-actions-sheet">
        <p className="session-action-context">{session.project.name} · {formatDuration(session.duration_minutes)}</p>
        <div className="journal-actions" id={`actions-${instance}`}>
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
    if (!(await draft.flush())) return false;
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
    return true;
  };
  /* A phone edits in the full-screen writer, whose Done saves and closes. */
  const [phone] = useState(() => window.matchMedia("(max-width: 999px)").matches);
  return <form className="journal-note-edit fields" onSubmit={(event) => {
    event.preventDefault();
    void complete();
  }}>
    <NoteEditor initiallyWriting={phone} sessionTitle={`${session.project.name} · ${formatDate(session.end)} · ${formatDuration(session.duration_minutes)}`} value={draft.value} onChange={draft.change} autoFocus rows={4} onDone={phone ? complete : draft.flush} saveStatus={draft.status} onRetry={() => void draft.flush()} onBlur={() => void draft.flush()} />
    {!phone ? <div className="journal-edit-actions">
      <button className="btn btn--primary" aria-busy={update.isPending}>Done</button>
      {draft.value !== (session.note ?? "") ? <button className="btn btn--quiet" type="button" onClick={() => { draft.change(session.note ?? ""); void draft.flush(); }}>Undo note edits</button> : null}
      <AppLink className="btn btn--quiet" href={urls.updateSession(session.id)}>Time & allocation</AppLink>
    </div> : null}
  </form>;
}
