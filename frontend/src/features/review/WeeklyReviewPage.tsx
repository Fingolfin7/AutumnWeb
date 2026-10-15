import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { faChevronLeft, faChevronRight } from "@fortawesome/free-solid-svg-icons";
import { api, unwrap } from "@/api/client";
import { keys } from "@/api/keys";
import { AppLink, urls } from "@/app/links";
import { bootstrap } from "@/bootstrap";
import { Icon } from "@/components/Icon";
import { ErrorState, Skeleton } from "@/components/states";
import { formatDateKey, todayKey } from "@/features/notifications/dates";
import { canGoNext, defaultStart, nextStart, selectedStart, sessionsLink, shiftWeek, weekParamFor } from "./weeks";
import "./review.css";

const plural = (count: number) => (count === 1 ? "" : "s");

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
            <section className="slab" aria-labelledby="projects-title">
              <div className="slab-pad nx-section-head">
                <h2 className="nx-title" id="projects-title">
                  Projects
                </h2>
              </div>
              {data.per_project.length ? (
                <div className="band-list">
                  {data.per_project.map((project) => (
                    <article className="band nx-review-row" key={project.project_id}>
                      <div>
                        <AppLink className="nx-review-project text-red" href={urls.updateProject(project.project_id)}>
                          {project.project_name}
                        </AppLink>
                        <small className="muted">
                          {project.session_count} session{plural(project.session_count)}
                        </small>
                      </div>
                      <div className="nx-review-actions">
                        <strong className="mono text-green">{Math.round(project.total_minutes)}m</strong>
                        <AppLink className="btn btn--quiet" href={`${urls.startTimer()}?project_id=${project.project_id}`}>
                          Start timer
                        </AppLink>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <p className="empty slab-pad">No completed sessions in this week.</p>
              )}
              <div className="slab-foot">
                <AppLink className="btn btn--ghost" href={sessionsLink(data.week_start, data.week_end)}>
                  Browse sessions
                </AppLink>
              </div>
            </section>

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
