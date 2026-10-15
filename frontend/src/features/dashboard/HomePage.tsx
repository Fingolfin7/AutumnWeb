import { useState } from "react";
import { faArrowRight, faCalendarAlt, faHistory, faPlay } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Disclose } from "@/components/Disclose";
import { ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { formatDayDate, formatDuration } from "@/lib/format";
import { FocusCard } from "@/features/timers/FocusCard";
import { FocusDeck } from "@/features/timers/FocusDeck";
import { useNow, useStartTimer, useTimers } from "@/features/timers/api";
import { SessionBand } from "@/features/sessions/SessionBand";
import { CommitmentsPanel } from "./CommitmentsPanel";
import { DayTimeline } from "./DayTimeline";
import { useDashboard, useRefreshOnRunningChange, useTimeline, type Dashboard, type TimelineRange } from "./api";

/* Home (dashboard.html): quick stats, the focus deck of running timers plus
   quick starts, the day timeline, recent sessions, commitments and activity.
   One /dashboard/ request paints everything; running timers then come from
   the shared, polled timers query so they stay live. */
export default function HomePage() {
  const dashboard = useDashboard();
  const timers = useTimers();
  useRefreshOnRunningChange(timers.data);

  if (dashboard.isPending) {
    return (
      <>
        <section className="slab">
          <Skeleton lines={2} height="2.2rem" />
        </section>
        <section className="slab">
          <Skeleton lines={5} />
        </section>
      </>
    );
  }
  if (dashboard.isError) return <ErrorState error={dashboard.error} onRetry={() => void dashboard.refetch()} />;
  return <HomeContent data={dashboard.data} />;
}

function HomeContent({ data }: { data: Dashboard }) {
  const timers = useTimers();
  const now = useNow();
  const running = timers.data ?? data.active_timers;
  const [range, setRange] = useState<TimelineRange>("today");
  const timeline = useTimeline(range, data.timeline);

  return (
    <>
      <h1 className="sr-only">Home</h1>
      <div className="desk-head desk-head--stats">
        <section className="stat-strip" aria-label="Quick stats">
          <div className="stat">
            <p className="stat-label">Today</p>
            <p className="stat-value text-green">{formatDuration(data.today_total)}</p>
          </div>
          <div className="stat">
            <p className="stat-label">This week</p>
            <p className="stat-value text-cyan">{formatDuration(data.week_total)}</p>
          </div>
          <div className="stat">
            <p className="stat-label">Active timers</p>
            <p className={`stat-value ${running.length ? "text-yellow" : "muted"}`}>{running.length}</p>
          </div>
          <div className="stat">
            <p className="stat-label">Current streak</p>
            <p className="stat-value text-red">
              {data.daily_streak.current_streak} day{data.daily_streak.current_streak === 1 ? "" : "s"}
            </p>
          </div>
        </section>
      </div>

      <FocusDeck label="What you are working on right now">
        {running.map((timer) => (
          <FocusCard key={timer.id} timer={timer} now={now} />
        ))}
        <StartCard quickStarts={data.quick_starts} />
      </FocusDeck>

      {timeline.data ? <DayTimeline timeline={timeline.data} range={range} onRange={setRange} /> : null}

      <div className="desk">
        <div className="desk-main">
          <Disclose
            id="home-recent"
            className="session-list"
            icon={faHistory}
            iconClass="text-blue"
            title="Recent sessions"
            summary={`last ${data.recent_sessions.reduce((n, day) => n + day.sessions.length, 0)}`}
          >
            {data.recent_sessions.length ? (
              <>
                {data.recent_sessions.map((day) => (
                  <div className="day-group" key={day.date}>
                    <header className="day-head">
                      <span className="day-date">{formatDayDate(day.date)}</span>
                      <span className="day-total">{formatDuration(day.total_minutes)}</span>
                    </header>
                    <ul className="band-list">
                      {day.sessions.map((session) => (
                        <SessionBand key={session.id} session={session} />
                      ))}
                    </ul>
                  </div>
                ))}
                <div className="slab-foot">
                  <AppLink className="btn btn--ghost btn--block" href={urls.sessions()}>
                    View all sessions <Icon icon={faArrowRight} />
                  </AppLink>
                </div>
              </>
            ) : (
              <p className="empty">
                No sessions yet. <AppLink href={urls.startTimer()}>Start a timer</AppLink> to begin tracking.
              </p>
            )}
          </Disclose>
        </div>

        <aside className="desk-side">
          <CommitmentsPanel items={data.commitments} />
          <ActivityPanel streak={data.daily_streak} />
        </aside>
      </div>
    </>
  );
}

function StartCard({ quickStarts }: { quickStarts: Dashboard["quick_starts"] }) {
  const start = useStartTimer();
  const toast = useToast();
  return (
    <article className="focus-card focus-card--start" aria-label="Start a new timer">
      {quickStarts.length ? (
        <div className="focus-subs focus-quick">
          {quickStarts.map((quick) => (
            <button
              key={quick.label}
              className="quick-chip"
              type="button"
              disabled={start.isPending}
              onClick={() =>
                start.mutate(
                  {
                    project_id: quick.project.id,
                    subproject_ids: quick.subprojects.map((s) => s.id),
                    optimistic: { projectName: quick.project.name, subprojects: quick.subprojects },
                  },
                  {
                    onSuccess: () => toast.success(`Started ${quick.project.name}.`),
                    onError: (error) => toast.error(`Couldn't start the timer: ${errorMessage(error)}`),
                  },
                )
              }
            >
              <Icon icon={faHistory} className="muted" /> {quick.project.name}
              {quick.subprojects.length ? <span className="muted"> &middot; {quick.subprojects.map((s) => s.name).join(", ")}</span> : null}
            </button>
          ))}
        </div>
      ) : null}
      <div className="focus-actions">
        <AppLink className="btn btn--primary btn--lg" href={urls.startTimer()}>
          <Icon icon={faPlay} /> Start a timer
        </AppLink>
      </div>
    </article>
  );
}

const ACTIVITY_RANGES = [
  { days: 7, label: "Week" },
  { days: 14, label: "2 weeks" },
  { days: 30, label: "Month" },
];

function ActivityPanel({ streak }: { streak: Dashboard["daily_streak"] }) {
  const [days, setDays] = useState(14);
  const cells = streak.recent_days.slice(-days);
  return (
    <Disclose id="home-activity" icon={faCalendarAlt} iconClass="text-green" title="Activity" summary={`${streak.current_streak}-day streak`}>
      <div className="activity">
        <div className="range-tabs" role="tablist" aria-label="Activity range">
          {ACTIVITY_RANGES.map((option) => (
            <button
              key={option.days}
              className={`range-tab${days === option.days ? " is-active" : ""}`}
              type="button"
              role="tab"
              aria-selected={days === option.days}
              onClick={() => setDays(option.days)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="cal">
          <div className="cal-head">
            {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
              <span key={d}>{d}</span>
            ))}
          </div>
          <div className="cal-grid">
            {cells.map((day, index) => {
              const date = new Date(`${day.date}T12:00:00`);
              const title = `${date.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" })}${
                day.active ? " — tracked" : ""
              }`;
              return (
                <span
                  key={day.date}
                  className={`cal-cell ${day.active ? "is-active" : "is-inactive"}`}
                  title={title}
                  style={index === 0 ? { gridColumnStart: day.weekday + 1 } : undefined}
                >
                  {date.getDate()}
                </span>
              );
            })}
          </div>
        </div>
      </div>
    </Disclose>
  );
}
