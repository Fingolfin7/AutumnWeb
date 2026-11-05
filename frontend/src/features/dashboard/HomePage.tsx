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
import { useNow, useOutsideContextTimerCount, useStartTimer, useTimers } from "@/features/timers/api";
import { groupByDay } from "@/lib/sessions";
import { JournalDay, SessionBand } from "@/features/sessions/SessionBand";
import { CommitmentsPanel } from "./CommitmentsPanel";
import { CommitmentMeter } from "@/features/commitments/CommitmentMeter";
import { CaptureLink } from "@/features/timers/CaptureLayer";
import { CapturePickLabel } from "@/features/timers/CapturePicker";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { Icon } from "@/components/Icon";
import { faHistory, faPlay, faSearch } from "@fortawesome/free-solid-svg-icons";
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
  const today = groupByDay(data.recent_sessions.flatMap((day) => day.sessions)).find((day) => day.date === localDateKey(new Date(now)));
  return (
    <div className="today-page">
      <header className="today-heading">
        <h1 className="page-title">Today</h1>
        <p className="today-summary">
          <span>{formatDayDate(new Date(now))}</span>
          <span aria-hidden="true"> · </span>
          <strong className="today-total" title={running.length ? "Including live time" : "Saved time today"}>{formatDuration(total)}</strong>
        </p>
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
      <div className="today-layout">
        <div className="today-lead">
          {running.length ? (
            <section className="ember-deck" aria-label="Running timers">
              {running.map((timer) => (
                <TimerCard key={timer.uuid ?? timer.id} timer={timer} now={now} />
              ))}
            </section>
          ) : (
            <StartCard items={data.quick_starts} />
          )}
        </div>
        {!firstRun ? <aside className="today-rail">
          {timeline.data ? <DayTimeline timeline={timeline.data} running={running} range={range} onRange={setRange} /> : null}
          {data.commitments.length ? <section className="today-commitments" aria-label="Commitment summary">
            <header className="today-section-head"><h2>Commitments</h2><span className="today-scope">All contexts</span></header>
            {data.commitments.map(({ commitment }) => <div className="today-commitment" key={commitment.id}>
              <AppLink className="today-commitment-name text-red" href={urls.updateCommitment(commitment.id)}>{commitment.target.name}</AppLink>
              <CommitmentMeter commitment={commitment} />
            </div>)}
            <details className="today-history"><summary>Streaks & balance</summary><CommitmentsPanel bare items={data.commitments} /></details>
          </section> : null}
        </aside> : null}
        {!firstRun ? <section className="today-journal" aria-label="Today's journal">
          <JournalDay label="Today's journal" minutes={today?.totalMinutes}>
            {today?.sessions.map((session) => <SessionBand key={session.id} session={session} day={today.date} />)}
          </JournalDay>
          {!today ? <p className="empty">Your saved sessions and notes will gather here.</p> : null}
          <AppLink className="today-all-sessions" href={urls.sessions()}>All sessions</AppLink>
        </section> : null}
      </div>
    </div>
  );
}

function TimerCard({ timer, now }: { timer: Timer; now: number }) {
  const stash = useRef<() => void>(() => undefined);
  return <FocusCard timer={timer} now={now} beforeStop={() => stash.current()}>
    <TimerNoteEditor timer={timer} registerStash={(fn) => { stash.current = fn; }} />
  </FocusCard>;
}

/** Recent project and subproject pairs, each project's subprojects beneath it. */
function pickupRows(items: Dashboard["quick_starts"]) {
  const projects = new Map<number, Dashboard["quick_starts"]>();
  for (const item of items) projects.set(item.project.id, [...(projects.get(item.project.id) ?? []), item]);
  return [...projects.values()].flatMap((pairs) => pairs.map((item, index) => ({ item, nested: index > 0 }))).slice(0, 6);
}

function StartCard({ items }: { items: Dashboard["quick_starts"] }) {
  const start = useStartTimer();
  const toast = useToast();
  return <section className="today-idle" aria-label="Start a new timer">
    <header className="today-section-head"><h2>Pick up where you left off</h2></header>
    <div className="today-pickups">
      {pickupRows(items).map(({ item, nested }) => {
        const sublabel = item.subprojects.map((sub) => sub.name).join(", ");
        return <button
          className={`today-quick-pick${nested ? " is-nested" : ""}`}
          type="button"
          key={`${item.project.id}-${item.subprojects.map((sub) => sub.id).join("-")}`}
          disabled={start.isPending}
          aria-label={`Start ${item.project.name}${sublabel ? ` / ${sublabel}` : ""}`}
          onClick={() => start.mutate({
            project_id: item.project.id, subproject_ids: item.subprojects.map((sub) => sub.id),
            optimistic: { projectName: item.project.name, subprojects: item.subprojects },
          }, { onSuccess: () => toast.success("Started timer"), onError: (error) => toast.error(`Couldn't start the timer: ${errorMessage(error)}`) })}
        >
          <Icon icon={faPlay} />
          {nested ? <span className="capture-pick-label"><span className="capture-pick-sub text-blue">{sublabel || "Whole project"}</span></span> : <CapturePickLabel project={item.project.name} sublabel={sublabel} />}
        </button>;
      })}
      <CaptureLink className="today-quick-pick today-something-else"><Icon icon={faSearch} /><span>Another project</span></CaptureLink>
      <CaptureLink className="today-quick-pick today-log-past" mode="past"><Icon icon={faHistory} /><span>Log past time</span></CaptureLink>
    </div>
  </section>;
}
