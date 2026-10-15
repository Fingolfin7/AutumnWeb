import { Fragment, useState } from "react";
import { faPen, faRedo, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { ConfirmDialog } from "@/components/Sheet";
import { SessionNote } from "@/components/SessionNote";
import { AppLink, urls } from "@/app/links";
import { formatDuration, formatShortDate, formatTime } from "@/lib/format";
import { useStartTimer } from "@/features/timers/api";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { useDeleteSession, type SessionRow } from "./api";

/* One session row (partials/session_band.html). On phones the actions sit
   behind a horizontal swipe (CSS scroll-snap); on desktop they appear on
   hover/focus. `showDate` prefixes the day for rows outside a day group. */
export function SessionBand({ session, showDate }: { session: SessionRow; showDate?: boolean }) {
  const start = useStartTimer();
  const remove = useDeleteSession();
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);

  const restart = () => {
    const subprojects = session.subproject_allocations.map((a) => ({ id: a.subproject_id, name: a.name }));
    start.mutate(
      {
        project_id: session.project.id,
        subproject_ids: subprojects.map((s) => s.id),
        optimistic: { projectName: session.project.name, subprojects },
      },
      {
        onSuccess: () => toast.success(`Started ${session.project.name}.`),
        onError: (error) => toast.error(`Couldn't start the timer: ${errorMessage(error)}`),
      },
    );
  };

  return (
    <li className="band swipe" id={`session-${session.id}`}>
      <div className="swipe-track">
        <div className="swipe-face session">
          <div className="session-mid">
            {showDate ? <span className="session-time session-day">{formatShortDate(session.end, new Date(0))}</span> : null}
            <span className="session-time">{formatTime(session.start)}</span>
            <span className="session-arrow">&rarr;</span>
            <span className="session-time">{formatTime(session.end)}</span>
            {crossesDst(session) ? (
              <span className="badge-dst" title="Session crosses a daylight savings transition">
                DST
              </span>
            ) : null}
          </div>
          <div className="session-top">
            <AppLink className="session-project" href={urls.updateProject(session.project.id)}>
              {session.project.name}
            </AppLink>
            {session.subproject_allocations.map((sub) => (
              <Fragment key={sub.subproject_id}>
                {" "}
                <AppLink className="sub-chip" href={urls.updateSubproject(sub.subproject_id)}>
                  {sub.name}
                </AppLink>
              </Fragment>
            ))}
          </div>
          <SessionNote id={`note-${session.id}`} html={session.note_html} text={session.note} />
          <span className="session-dur">{formatDuration(session.duration_minutes)}</span>
        </div>
        <div className="swipe-actions">
          <button className="btn-icon" type="button" title="Restart this project + subprojects" onClick={restart} disabled={start.isPending}>
            <Icon icon={faRedo} />
            <span className="sr-only">Restart</span>
          </button>
          <AppLink className="btn-icon" href={urls.updateSession(session.id)} title="Edit session">
            <Icon icon={faPen} />
            <span className="sr-only">Edit session</span>
          </AppLink>
          <button className="btn-icon btn-icon--danger" type="button" title="Delete session" onClick={() => setConfirming(true)}>
            <Icon icon={faTrash} />
            <span className="sr-only">Delete session</span>
          </button>
        </div>
      </div>
      <span className="swipe-hint" />
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
