import { Fragment } from "react";
import { Navigate, useNavigate, useParams } from "react-router";
import { faArrowLeft, faExclamationTriangle, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { ApiError } from "@/api/errors";
import { formatDuration, formatTime } from "@/lib/format";
import { parseSessionParam, useDeleteSession, useSession, type SessionRow } from "./api";

/* /delete_session/<id>/ (delete_session.html): a confirm page showing the
   session about to disappear in the same shape the lists show it. Back is the
   quiet default; Delete wears the destructive colour. Unlike the old page the
   toast that follows offers Undo (the session is re-recorded with the same
   uuid, times, note and split). */
export default function DeleteSessionPage() {
  const { sessionId } = useParams();
  const query = useSession(sessionId);
  const navigate = useNavigate();
  const remove = useDeleteSession();

  if (parseSessionParam(sessionId).kind === "invalid") return <Gone />;
  if (query.isPending) return <Skeleton lines={5} height="2rem" />;
  if (query.isError) {
    return query.error instanceof ApiError && query.error.status === 404 ? (
      <Gone />
    ) : (
      <ErrorState error={query.error} onRetry={() => void query.refetch()} />
    );
  }
  const session = query.data;
  /* A running timer is discarded through the timer pages, not as a session. */
  if (session.active) return <Navigate to={`/remove_timer/${session.id}/`} replace />;

  return (
    <>
      <div className="desk-head">
        <div>
          <h1 className="page-title">Delete session?</h1>
        </div>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          remove.mutate(session, { onSuccess: () => navigate(urls.sessions()) });
        }}
      >
        <section className="slab session-list">
          <ul className="band-list">
            <SessionSummary session={session} html={session.note_html} />
          </ul>
        </section>

        <p className="confirm-warn">
          <Icon icon={faExclamationTriangle} /> This removes the session and its time from every total. You can undo straight after.
        </p>

        <div className="form-actions">
          <AppLink className="btn btn--ghost" href={urls.sessions()}>
            <Icon icon={faArrowLeft} /> Back
          </AppLink>
          <button className="btn btn--stop btn--spacer" type="submit" disabled={remove.isPending}>
            <Icon icon={faTrash} /> {remove.isPending ? "Deleting..." : "Delete session"}
          </button>
        </div>
      </form>
    </>
  );
}

function Gone() {
  return (
    <>
      <div className="desk-head">
        <h1 className="page-title">Session not found</h1>
      </div>
      <Empty>That session no longer exists. It may already have been deleted.</Empty>
      <div className="form-actions">
        <AppLink className="btn btn--ghost" href={urls.sessions()}>
          <Icon icon={faArrowLeft} /> Back
        </AppLink>
      </div>
    </>
  );
}

function SessionSummary({ session, html }: { session: SessionRow; html?: string | null }) {
  const crossesDst = !!session.end && new Date(session.start).getTimezoneOffset() !== new Date(session.end).getTimezoneOffset();
  return (
    <li className="band">
      <div className="session">
        <div className="session-mid">
          <span className="session-time">{formatTime(session.start)}</span>
          <span className="session-arrow">&rarr;</span>
          <span className="session-time">{formatTime(session.end)}</span>
          {crossesDst ? (
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
        {html ? (
          <div className="session-note is-open" dangerouslySetInnerHTML={{ __html: html }} />
        ) : session.note ? (
          <div className="session-note is-open" style={{ whiteSpace: "pre-wrap" }}>
            {session.note}
          </div>
        ) : null}
        <span className="session-dur">{formatDuration(session.duration_minutes)}</span>
      </div>
    </li>
  );
}
