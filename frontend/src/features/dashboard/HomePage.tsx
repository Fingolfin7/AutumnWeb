import { CaptureForm } from "@/features/timers/CaptureForm";
import { useRef, useState } from "react";
import { EmptyWorkspace } from "@/features/settings/FirstRunPage";
import { ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useActiveContext } from "@/app/context";
import { useAllProjects } from "@/api/meta";
import type { Timer } from "@/api/types";
import { formatDayDate, formatDuration, localDateKey } from "@/lib/format";
import { FocusCard } from "@/features/timers/FocusCard";
import { TimerNoteEditor } from "@/features/timers/TimerNoteEditor";
import { TimerReminders } from "@/features/timers/TimerReminders";
import { useNow, useOutsideContextTimerCount, useTimers } from "@/features/timers/api";
import { groupByDay } from "@/lib/sessions";
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
  const running = [...(timers.data ?? data.active_timers)].sort((a, b) => Date.parse(b.start) - Date.parse(a.start));
  const [range, setRange] = useState<TimelineRange>("today");
  const timeline = useTimeline(range, data.timeline);
  const outside = useOutsideContextTimerCount();
  const { setContextId } = useActiveContext();
  const firstRun = !running.length && !data.recent_sessions.length && !data.quick_starts.length;
  const today = groupByDay(data.recent_sessions.flatMap((day) => day.sessions)).filter((day) => day.date === localDateKey(new Date(now)));
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
            <TimerCard key={timer.uuid ?? timer.id} timer={timer} now={now} />
          ))}
        </section>
      ) : (
        <StartCard />
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
      {!firstRun ? (
        <>
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
              <div className="today-commitment" key={commitment.id}><AppLink className="today-commitment-row" href={urls.updateCommitment(commitment.id)}>
                <span className="text-red">{commitment.target.name}</span>
                <span>
                  <span className="text-green">{amount(progress.actual)}</span> of {amount(progress.target)}{" "}
                  <span className="muted">{progress.period}</span>
                </span>
              </AppLink><details className="today-history"><summary>Banking & details</summary><CommitmentsPanel items={data.commitments.filter((item) => item.commitment.id === commitment.id)} /></details></div>
            );
          })}

        </section>
      ) : null}
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
                    <SessionBand key={session.id} session={session} day={day.date} />
                  ))}
                </ul>
              ))
            ) : (
              <p className="empty">Your saved sessions and notes will gather here.</p>
            )}

          </section>


        </>
      ) : null}
    </div>
  );
}

function TimerCard({ timer, now }: { timer: Timer; now: number }) {
  const stash = useRef<() => void>(() => undefined);
  const [expanded, setExpanded] = useState(false);
  return <FocusCard timer={timer} now={now} expanded={expanded} onExpand={() => setExpanded((value) => !value)} beforeStop={() => stash.current()}>
    <TimerNoteEditor preview={!expanded} timer={timer} registerStash={(fn) => { stash.current = fn; }} />
    {expanded ? <TimerReminders timer={timer} /> : null}
  </FocusCard>;
}

function StartCard() {
  return <section className="today-idle" aria-label="Start a new timer"><CaptureForm inline /></section>;
}
