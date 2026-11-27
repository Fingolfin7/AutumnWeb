import { useId, useState, type ReactNode } from "react";
import { useQuery, keepPreviousData, queryOptions, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { faChevronLeft, faChevronRight } from "@fortawesome/free-solid-svg-icons";
import { api, unwrap } from "@/api/client";
import { keys } from "@/api/keys";
import type { components } from "@/api/schema";
import { AppLink, urls } from "@/app/links";
import { bootstrap } from "@/bootstrap";
import { Icon } from "@/components/Icon";
import { MarkdownActions } from "@/components/MarkdownActions";
import { SessionNote } from "@/components/SessionNote";
import { ErrorState, Skeleton } from "@/components/states";
import { addDays, formatDateKey, formatInstant, todayKey } from "@/features/notifications/dates";
import { fetchAllSessionPages, mergeSessionPages, type SessionRow } from "@/features/sessions/api";
import { formatJournalDuration } from "@/lib/format";
import { sessionsByProject, weeklyReviewMarkdown } from "@/lib/journalMarkdown";
import { canGoNext, defaultStart, nextStart, selectedStart, sessionsLink, shiftWeek, weekParamFor } from "./weeks";
import "./review.css";

const plural = (count: number) => (count === 1 ? "" : "s");
type Week = components["schemas"]["WeeklyReview"];
type WeekProject = Week["per_project"][number];

const weekHref = (start: string, latest: string) => {
  const param = weekParamFor(start, latest);
  return param ? `${urls.weeklyReview()}?week=${param}` : urls.weeklyReview();
};

/* Weekly review (templates/core/weekly_review.html): seven days at a time,
   by default the seven ending yesterday. The window's first day is kept in
   the URL so a week can be bookmarked and Back steps through the weeks. */
export default function WeeklyReviewPage() {
  const [params] = useSearchParams();
  const timezone = bootstrap().profile.timezone;
  const latest = defaultStart(todayKey(timezone));
  const requested = selectedStart(params.get("week"));
  const start = requested && requested < latest ? requested : latest;

  const review = useQuery({
    queryKey: keys.reports("weekly-review", { week: start }),
    queryFn: () => unwrap(api.GET("/api/v2/reports/weekly-review/", { params: { query: { week: start } } })),
    placeholderData: keepPreviousData,
  });
  const data = review.data;
  const stale = review.isPlaceholderData;
  const previous = shiftWeek(start, -1);
  const next = nextStart(start, latest);
  const forward = canGoNext(start, latest);

  return (
    <>
      <div className="desk-head nx-page-head">
        <div>
          <h1 className="page-title">Weekly review</h1>
          <p className="nx-lede">
            {data ? (
              <>
                <span className="mono">{formatDateKey(data.week_start)}</span> — <span className="mono">{formatDateKey(data.week_end, true)}</span>
                {start === latest ? <span className="muted"> · last 7 days</span> : null}
              </>
            ) : (
              <span className="mono">{formatDateKey(start)}</span>
            )}
          </p>
          <nav className="nx-week-nav" aria-label="Choose a week">
            <AppLink className="btn btn--quiet" href={weekHref(previous, latest)}>
              <Icon icon={faChevronLeft} /> Previous week
            </AppLink>
            {forward ? (
              <AppLink className="btn btn--quiet" href={weekHref(next, latest)}>
                Next week <Icon icon={faChevronRight} />
              </AppLink>
            ) : (
              <span className="btn btn--quiet" aria-disabled="true">
                Next week <Icon icon={faChevronRight} />
              </span>
            )}
            {start !== latest ? (
              <AppLink className="btn btn--ghost" href={urls.weeklyReview()}>
                Last 7 days
              </AppLink>
            ) : null}
          </nav>
        </div>
      </div>

      {review.isPending ? (
        <section className="slab slab-pad nx-review-hero" aria-busy="true">
          <Skeleton lines={4} height="1.6rem" />
        </section>
      ) : review.isError && !data ? (
        <ErrorState error={review.error} onRetry={() => void review.refetch()} />
      ) : data ? (
        <div className={stale ? "nx-review-dim" : undefined} aria-busy={stale}>
          {review.isError ? <ErrorState error={review.error} onRetry={() => void review.refetch()} /> : null}
          <section className="slab slab-pad nx-review-hero" aria-labelledby="review-summary-title">
            <h2 className="nx-review-number" id="review-summary-title">
              {data.duration_label}
            </h2>
            <p className="nx-review-sub">
              across {data.project_count} project{plural(data.project_count)}
            </p>
            <div className="stat-strip nx-review-stats">
              <div className="stat">
                <span className="stat-label">Sessions</span>
                <strong className="stat-value">{data.session_count}</strong>
              </div>
              <div className="stat">
                <span className="stat-label">Commitments met</span>
                <strong className="stat-value">
                  {data.met_count} / {data.eligible_count}
                </strong>
              </div>
            </div>
          </section>

          <div className="nx-review-grid">
            <WeekProjects key={data.week_start} week={data} stale={stale} />

            <section className="slab" aria-labelledby="commitments-title">
              <div className="slab-pad nx-section-head">
                <h2 className="nx-title" id="commitments-title">
                  Commitments
                </h2>
              </div>
              {data.details.length ? (
                <div className="band-list">
                  {data.details.map((item) => (
                    <article className="band nx-review-row" key={item.commitment_id}>
                      <div>
                        <AppLink className="nx-review-project" href={urls.updateCommitment(item.commitment_id)}>
                          {item.target_name}
                        </AppLink>
                        <small className="muted">
                          {item.met_period_count} of {item.period_count} period{plural(item.period_count)} met
                        </small>
                      </div>
                      {item.met ? (
                        <span className="nx-status nx-status--met">Met</span>
                      ) : (
                        <span className="nx-status nx-status--open">Needs attention</span>
                      )}
                    </article>
                  ))}
                </div>
              ) : (
                <p className="empty slab-pad">No commitment periods closed in this week.</p>
              )}
              <div className="slab-foot">
                <AppLink className="btn btn--ghost" href={urls.home()}>
                  See commitments
                </AppLink>
              </div>
            </section>
          </div>
        </div>
      ) : null}
    </>
  );
}

function weekSessions(week: Week) {
  return queryOptions({
    queryKey: keys.reports("weekly-review-sessions", { start: week.window_start, end: week.window_end }),
    staleTime: 60_000,
    networkMode: "always",
    queryFn: async ({ signal }) => {
      // Pad the calendar-date filter, then use the report's exact instants.
      // Midnight transitions can shift the report's local-day boundaries.
      const pages = await fetchAllSessionPages({
        start_date: addDays(week.week_start, -1),
        end_date: addDays(week.week_end, 1),
      }, { signal, includeHtml: true });
      const start = Date.parse(week.window_start);
      const end = Date.parse(week.window_end);
      return mergeSessionPages(pages).filter((session) => {
        const instant = Date.parse(session.end ?? "");
        return instant >= start && instant < end;
      });
    },
  });
}

function WeekProjects({ week, stale }: { week: Week; stale: boolean }) {
  const [requested, setRequested] = useState(false);
  const queryClient = useQueryClient();
  const options = weekSessions(week);
  const sessions = useQuery({ ...options, enabled: requested && !stale });
  const grouped = sessions.data ? sessionsByProject(sessions.data) : null;

  return (
    <section className="slab" aria-labelledby="projects-title">
      <div className="slab-pad nx-section-head nx-week-project-head">
        <h2 className="nx-title" id="projects-title">Projects</h2>
        {week.session_count ? (
          <MarkdownActions
            copyLabel="Copy week as Markdown"
            filename={`autumn-week-${week.week_start}.md`}
            load={async () => weeklyReviewMarkdown(week, await queryClient.fetchQuery(options))}
            disabled={stale}
            showDownload
          />
        ) : null}
      </div>
      {week.per_project.length ? (
        <div className="band-list">
          {week.per_project.map((project) => (
            <ProjectNotes
              key={project.project_id}
              project={project}
              timeZone={week.timezone}
              sessions={grouped ? grouped.get(project.project_id) ?? [] : null}
              error={sessions.error}
              retry={() => void sessions.refetch()}
              request={() => setRequested(true)}
            />
          ))}
        </div>
      ) : (
        <p className="empty slab-pad">No completed sessions in this week.</p>
      )}
      <div className="slab-foot">
        <AppLink className="btn btn--ghost" href={sessionsLink(week.week_start, week.week_end)}>Browse sessions</AppLink>
      </div>
    </section>
  );
}

function ProjectNotes({ project, timeZone, sessions, error, retry, request }: {
  project: WeekProject;
  timeZone: string;
  sessions: SessionRow[] | null;
  error: Error | null;
  retry: () => void;
  request: () => void;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  let notes: ReactNode = null;
  if (open) {
    if (!sessions) {
      notes = error ? <ErrorState error={error} onRetry={retry} /> : <div aria-busy="true" role="status">Loading session notes…</div>;
    } else if (sessions.length) {
      notes = (
        <ul className="nx-review-notes-list">
          {sessions.map((session) => (
            <li className="journal-entry" key={session.id}>
              <div className="nx-review-note-heading">
                <AppLink href={urls.updateSession(session.id)}>{formatInstant(session.end, timeZone)}</AppLink>
                <span className="muted mono">{formatJournalDuration(session.duration_minutes)}</span>
              </div>
              <SessionNote id={`${id}-${session.id}`} html={session.note_html} text={session.note} />
            </li>
          ))}
        </ul>
      );
    } else {
      notes = <p className="muted">No completed sessions for this project in this week.</p>;
    }
  }
  return (
    <article className="band">
      <div className="nx-review-row">
        <div>
          <AppLink className="nx-review-project text-red" href={urls.updateProject(project.project_id)}>{project.project_name}</AppLink>
          <small className="muted">{project.session_count} session{plural(project.session_count)}</small>
        </div>
        <div className="nx-review-actions">
          <strong className="mono text-green">{formatJournalDuration(project.total_minutes)}</strong>
          <AppLink className="btn btn--quiet" href={`${urls.startTimer()}?project_id=${project.project_id}`}>
            Start timer
          </AppLink>
        </div>
      </div>
      <details className="nx-review-notes" onToggle={(event) => {
        const expanded = event.currentTarget.open;
        setOpen(expanded);
        if (expanded) request();
      }}>
        <summary className="quiet-link">Session notes</summary>
        {notes}
      </details>
    </article>
  );
}
