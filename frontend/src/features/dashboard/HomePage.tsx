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
import { CommitmentMeter } from "@/features/commitments/CommitmentMeter";
import { CapturePickLabel } from "@/features/timers/CapturePicker";
import { useStartTimer } from "@/features/timers/api";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { Icon } from "@/components/Icon";
import { faPlay } from "@fortawesome/free-solid-svg-icons";
import { DayTimeline, ledgerEntries } from "./DayTimeline";
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
  const todayTimeline = useTimeline("today", data.timeline);
  const total = ledgerEntries(todayTimeline.data ?? data.timeline, running, now).reduce((sum, block) => sum + block.minutes, 0);
  const outside = useOutsideContextTimerCount();
  const { setContextId } = useActiveContext();
  const firstRun = !running.length && !data.recent_sessions.length && !data.quick_starts.length;
  const today = groupByDay(data.recent_sessions.flatMap((day) => day.sessions)).filter((day) => day.date === localDateKey(new Date(now)));
  return (
    <div className="today-page">
      <header className="today-heading">
        <h1 className="page-title">Today</h1>
        <span className="today-date">{formatDayDate(new Date(now))}</span>
        <span className="today-heading-dot" aria-hidden="true">·</span>
        <strong className="today-total" title={running.length ? "Including live time" : "Saved time today"}>{formatDuration(total)}</strong>
      </header>
      {firstRun ? <p className="muted">Pick a project and start. Your notes and time will make this day your own.</p> : null}
      {outside ? (
        <p className="muted timers-outside-context">
          {outside} timer{outside === 1 ? "" : "s"} running in other contexts {" / "}
          <button type="button" className="btn btn--quiet" onClick={() => void setContextId(null)}>
            Show all
          </button>
        </p>
      ) : null}
      {running.length ? (
        <section className="ember-deck" aria-label="Running timers">
          {running.map((timer) => (
            <TimerCard key={timer.uuid ?? timer.id} timer={timer} now={now} />
          ))}
        </section>
      ) : (
        <StartCard items={data.quick_starts} />
      )}
      {!firstRun ? <div className="today-picture">
        {timeline.data ? <DayTimeline timeline={timeline.data} running={running} range={range} onRange={setRange} /> : null}
        {data.commitments.length ? <section className="today-commitments" aria-label="Commitment summary">
          <div className="today-section-head"><h2>Commitments</h2><span className="muted today-scope">All contexts</span></div>
          {data.commitments.map(({ commitment }) => <div className="today-commitment" key={commitment.id}>
            <AppLink className="today-commitment-name text-red" href={urls.updateCommitment(commitment.id)}>{commitment.target.name}</AppLink>
            <CommitmentMeter commitment={commitment} />
            <details className="today-history"><summary>Balance & details</summary><CommitmentsPanel bare items={data.commitments.filter((item) => item.commitment.id === commitment.id)} /></details>
          </div>)}
        </section> : null}
      </div> : null}
      {!firstRun ? (<>
          <section className="today-journal" aria-label="Today's journal">
            <header className="today-section-head">
              <h2>Today's journal</h2>
              <AppLink className="btn btn--quiet" href={urls.sessions()}>
                All sessions
              </AppLink>
            </header>
            {today.length ? (
              today.map((day) => (
                <div className="day-group" key={day.date}><header className="day-head"><span className="day-date">{formatDayDate(day.date)}</span><span className="day-total">{formatDuration(day.totalMinutes)}</span></header><ul className="band-list">
                  {day.sessions.map((session) => (
                    <SessionBand key={session.id} session={session} day={day.date} />
                  ))}
                </ul></div>
              ))
            ) : (
              <p className="empty">Your saved sessions and notes will gather here.</p>
            )}

          </section>


        </>) : null}
    </div>
  );
}

function TimerCard({ timer, now }: { timer: Timer; now: number }) {
  const stash = useRef<() => void>(() => undefined);
  const [expanded, setExpanded] = useState(false);
  return <FocusCard timer={timer} now={now} expanded={expanded} onExpand={() => setExpanded((value) => !value)} beforeStop={() => stash.current()}>
    <TimerNoteEditor timer={timer} registerStash={(fn) => { stash.current = fn; }} />
    {expanded ? <TimerReminders timer={timer} /> : null}
  </FocusCard>;
}

function StartCard({ items }: { items: Dashboard["quick_starts"] }) {
  const start = useStartTimer();
  const toast = useToast();
  const recent = items.filter((item, index) => items.findIndex((other) => other.project.id === item.project.id) === index).slice(0, 6);
  return <section className="today-idle" aria-label="Start a new timer">
    <div className="today-section-head"><h2>Pick up where you left off</h2></div>
    <div className="today-pickups">{recent.map((item) => <button className="today-quick-pick" type="button" key={`${item.project.id}-${item.subprojects.map((sub) => sub.id).join("-")}`} disabled={start.isPending} aria-label={`Start ${item.project.name}${item.subprojects.length ? ` / ${item.subprojects.map((sub) => sub.name).join(", ")}` : ""}`} onClick={() => start.mutate({
      project_id: item.project.id, subproject_ids: item.subprojects.map((sub) => sub.id),
      optimistic: { projectName: item.project.name, subprojects: item.subprojects },
    }, { onSuccess: () => toast.success("Started timer"), onError: (error) => toast.error(`Couldn't start the timer: ${errorMessage(error)}`) })}>
      <Icon icon={faPlay} /><CapturePickLabel project={item.project.name} sublabel={item.subprojects.map((sub) => sub.name).join(", ")} />
    </button>)}
    <AppLink className="today-quick-pick today-something-else" href={urls.startTimer()}>Another project</AppLink>
    <AppLink className="today-quick-pick today-log-past" href="/start_timer/?mode=past">Log past time</AppLink></div>
  </section>;
}
