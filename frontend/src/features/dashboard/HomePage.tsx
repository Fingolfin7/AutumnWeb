import { useRef, useState } from "react";
import { faPlay } from "@fortawesome/free-solid-svg-icons";
import { EmptyWorkspace } from "@/features/settings/FirstRunPage";
import { Icon } from "@/components/Icon";
import { ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { useActiveContext } from "@/app/context";
import { errorMessage } from "@/api/errors";
import { useAllProjects } from "@/api/meta";
import type { Timer } from "@/api/types";
import { formatDayDate, formatDuration, localDateKey } from "@/lib/format";
import { FocusCard } from "@/features/timers/FocusCard";
import { TimerNoteEditor } from "@/features/timers/TimerNoteEditor";
import { TimerReminders } from "@/features/timers/TimerReminders";
import { useNow, useOutsideContextTimerCount, useStartTimer, useTimers } from "@/features/timers/api";
import { Suggestions } from "@/features/timers/Suggestions";
import { SessionBand } from "@/features/sessions/SessionBand";
import { CommitmentsPanel } from "./CommitmentsPanel";
import { DayTimeline } from "./DayTimeline";
import { useDashboard, useRefreshOnRunningChange, useTimeline, type Dashboard, type TimelineRange } from "./api";

export default function HomePage() {
  const dashboard = useDashboard();
  const projects = useAllProjects();
  const timers = useTimers();
  useRefreshOnRunningChange(timers.data);
  if (dashboard.isPending)
    return (
      <section className="slab">
        <Skeleton lines={5} />
      </section>
    );
  if (dashboard.isError) return <ErrorState error={dashboard.error} onRetry={() => void dashboard.refetch()} />;
  if (projects.isSuccess && projects.data.length === 0 && !dashboard.data.recent_sessions.length && !dashboard.data.active_timers.length) return <EmptyWorkspace />;
  return <HomeContent data={dashboard.data} />;
}

function HomeContent({ data }: { data: Dashboard }) {
  const timers = useTimers();
  const now = useNow();
  const running = timers.data ?? data.active_timers;
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const [range, setRange] = useState<TimelineRange>("today");
  const timeline = useTimeline(range, data.timeline);
  const outside = useOutsideContextTimerCount();
  const { setContextId } = useActiveContext();
  const firstRun = !running.length && !data.recent_sessions.length && !data.quick_starts.length;
  const today = data.recent_sessions.filter((day) => day.date === localDateKey(new Date(now)));
  return (
    <div className="today-page">
      <header className="today-heading">
        <h1 className="page-title">Today</h1>
        <span>{formatDayDate(new Date(now))}</span>
        {running.length ? (
          <AppLink className="btn btn--quiet" href={urls.startTimer()}>
            + New timer
          </AppLink>
        ) : null}
      </header>
      {running.length ? (
        <section className="ember-deck" aria-label="Running timers">
          {running.map((timer) => (
            <TimerCard key={timer.id} timer={timer} now={now} />
          ))}
        </section>
      ) : (
        <StartCard quickStarts={data.quick_starts} />
      )}
      {outside ? (
        <p className="muted timers-outside-context">
          {outside} timer{outside === 1 ? "" : "s"} running in other contexts {" / "}
          <button type="button" className="btn btn--quiet" onClick={() => void setContextId(null)}>
            Show all
          </button>
        </p>
      ) : null}
      {timeline.data && !firstRun ? (
        <DayTimeline timeline={timeline.data} running={running} range={range} onRange={setRange} />
      ) : null}
      {data.commitments.length ? (
        <section className="today-commitments" aria-label="Commitment summary">
          <div className="today-section-head">
            <h2>Commitments</h2>
            <span className="muted today-scope">All contexts</span>
          </div>
          {data.commitments.map(({ commitment, progress }) => {
            const time = progress.commitment_type === "time";
            const amount = (value: number) => (time ? formatDuration(value) : `${Math.round(value)} sessions`);
            return (
              <AppLink className="today-commitment-row" key={commitment.id} href={urls.updateCommitment(commitment.id)}>
                <span className="text-red">{commitment.target.name}</span>
                <span>
                  <span className="text-green">{amount(progress.actual)}</span> of {amount(progress.target)}{" "}
                  <span className="muted">{progress.period}</span>
                </span>
              </AppLink>
            );
          })}
          <details className="today-history">
            <summary>Banking & commitment details</summary>
            <CommitmentsPanel items={data.commitments} />
            <AppLink className="btn btn--quiet" href={urls.weeklyReview()}>
              Open weekly review
            </AppLink>
          </details>
        </section>
      ) : null}
      {!firstRun ? (
        <>
          <details className="today-suggestions" onToggle={(event) => setSuggestionsOpen(event.currentTarget.open)}>
            <summary>Need a starting point?</summary>
            {suggestionsOpen ? <Suggestions /> : null}
          </details>
          <section className="today-journal" aria-label="Today's journal">
            <header className="today-section-head">
              <h2>Today's journal</h2>
              <AppLink className="btn btn--quiet" href={urls.sessions()}>
                All sessions
              </AppLink>
            </header>
            {today.length ? (
              today.map((day) => (
                <ul className="band-list" key={day.date}>
                  {day.sessions.map((session) => (
                    <SessionBand key={session.id} session={session} />
                  ))}
                </ul>
              ))
            ) : (
              <p className="empty">Your saved sessions and notes will gather here.</p>
            )}
            {data.recent_sessions.some((day) => day.date !== localDateKey(new Date(now))) ? (
              <details className="today-history">
                <summary>Earlier journal entries</summary>
                {data.recent_sessions
                  .filter((day) => day.date !== localDateKey(new Date(now)))
                  .map((day) => (
                    <div className="day-group" key={day.date}>
                      <header className="day-head">
                        <span>{formatDayDate(day.date)}</span>
                        <span className="day-total">{formatDuration(day.total_minutes)}</span>
                      </header>
                      <ul className="band-list">
                        {day.sessions.map((session) => (
                          <SessionBand key={session.id} session={session} />
                        ))}
                      </ul>
                    </div>
                  ))}
              </details>
            ) : null}
          </section>
        </>
      ) : null}
    </div>
  );
}

function TimerCard({ timer, now }: { timer: Timer; now: number }) {
  const stash = useRef<() => void>(() => undefined);
  return (
    <FocusCard timer={timer} now={now} beforeStop={() => stash.current()}>
      <TimerNoteEditor
        timer={timer}
        registerStash={(fn) => {
          stash.current = fn;
        }}
      />
      <TimerReminders timer={timer} />
    </FocusCard>
  );
}

function StartCard({ quickStarts }: { quickStarts: Dashboard["quick_starts"] }) {
  const start = useStartTimer();
  const toast = useToast();
  const projects = useAllProjects();
  const empty = projects.isSuccess && projects.data.length === 0;
  return (
    <section className="today-idle" aria-label="Start a new timer">
      <div className="today-idle-intro">
        <span className="ember-idle-clock" aria-hidden="true">
          00<span>:00</span>
        </span>
        <h2>{empty ? "A project gives your time a home." : "Make room for what matters."}</h2>
        {empty ? (
          <AppLink className="btn btn--primary btn--lg" href={urls.createProject()}>
            Create your first project
          </AppLink>
        ) : (
          <>
            <AppLink className="btn btn--primary btn--lg" href={urls.startTimer()}>
              <Icon icon={faPlay} /> Start a timer
            </AppLink>
            <AppLink className="btn btn--quiet" href="/start_timer/?mode=past">
              Log past time
            </AppLink>
          </>
        )}
      </div>
      {quickStarts.length ? (
        <div className="today-quick">
          <h3>Pick up where you left off</h3>
          {quickStarts.slice(0, 4).map((quick) => (
            <button
              key={quick.label}
              className="today-quick-pick"
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
                    onError: (error) => toast.error(errorMessage(error)),
                  },
                )
              }
            >
              <Icon icon={faPlay} />
              <span>
                <span className="text-red">{quick.project.name}</span>
                {quick.subprojects.length ? (
                  <small className="text-blue">{quick.subprojects.map((s) => s.name).join(", ")}</small>
                ) : null}
              </span>
              <span className="today-quick-verb">Start</span>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}
