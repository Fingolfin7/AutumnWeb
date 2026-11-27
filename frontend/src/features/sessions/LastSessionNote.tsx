import { useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { keys } from "@/api/keys";
import { SessionNote } from "@/components/SessionNote";
import { AppLink, urls } from "@/app/links";
import { formatJournalDate, formatJournalDuration, formatTimeRange } from "@/lib/format";
import type { SessionRow } from "./api";

/* The project's latest finished session, through the same list endpoint as
   the journal. Under ["sessions"], so logging, stopping or editing a session
   refreshes it. A project made offline has no server id yet: nothing to ask. */
export function useLastSession(projectId: number) {
  return useQuery({
    queryKey: keys.sessions({ last: projectId }),
    enabled: projectId > 0,
    queryFn: async ({ signal }): Promise<SessionRow | null> => {
      const data = await unwrap(
        api.GET("/api/v2/sessions/", {
          signal,
          params: {
            query: { project_ids: String(projectId), active: false, ordering: "newest", limit: 1, include: "note,note_html" },
          },
        }),
      );
      return data.sessions[0] ?? null;
    },
  });
}

/* Where you left off: when the project was last worked on and that
   session's note, as written. Shown when a project is picked for a timer and
   on the project's page. */
export function LastSessionNote({ projectId }: { projectId: number }) {
  const last = useLastSession(projectId);
  const titleId = useId();
  if (projectId <= 0) return null;
  const session = last.data;
  return (
    <section className="slab slab-pad last-note" aria-labelledby={titleId} aria-busy={last.isPending || undefined}>
      <header className="last-note-head">
        <h2 className="last-note-title" id={titleId}>
          Last session
        </h2>
        {session?.end ? (
          <p className="last-note-when">
            <AppLink href={urls.updateSession(session.id)}>
              <time dateTime={session.end}>{formatJournalDate(session.end)}</time>
            </AppLink>{" "}
            <span className="journal-time">{formatTimeRange(session.start, session.end)}</span>{" "}
            <span className="last-note-duration">{formatJournalDuration(session.duration_minutes)}</span>
          </p>
        ) : null}
      </header>
      {last.isPending ? (
        <p className="last-note-empty">Looking for the last session…</p>
      ) : last.isError && !session ? (
        <p className="last-note-empty">
          Couldn't load the last session.{" "}
          <button type="button" className="quiet-link" onClick={() => void last.refetch()}>
            Try again
          </button>
        </p>
      ) : !session ? (
        <p className="last-note-empty">No finished sessions on this project yet.</p>
      ) : session.note?.trim() || session.note_html ? (
        <SessionNote id={`last-note-${session.id}`} html={session.note_html} text={session.note} clamp />
      ) : (
        <p className="last-note-empty">That session has no note.</p>
      )}
    </section>
  );
}
