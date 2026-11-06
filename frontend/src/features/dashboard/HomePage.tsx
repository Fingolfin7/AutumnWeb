import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router";
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
import { dayPortions, groupByDay } from "@/lib/sessions";
import { JournalDay, SessionBand } from "@/features/sessions/SessionBand";
import { CommitmentHistory } from "./CommitmentsPanel";
import { CommitmentSummary } from "@/features/commitments/CommitmentSummary";
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
  const { hash } = useLocation();
  const runningIds = running.map((timer) => timer.id).join(",");
  useEffect(() => {
    if (hash.startsWith("#timer-")) document.getElementById(hash.slice(1))?.scrollIntoView({ block: "center" });
  }, [hash, runningIds]);
  const [range, setRange] = useState<TimelineRange>("today");
  const timeline = useTimeline(range, data.timeline);
  const todayTimeline = useTimeline("today", data.timeline);
  const weekTimeline = useTimeline("wk");
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
          <strong className="today-total">{formatDuration(total)}</strong><span className="today-total-scope"> {running.length ? "including running" : "saved today"}</span>
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
        {!firstRun ? <div className="today-day">
          {timeline.data ? <DayTimeline timeline={timeline.data} running={running} range={range} onRange={setRange} /> : null}
          {weekTimeline.data ? <WeekEmbers timeline={weekTimeline.data} running={running} now={now} /> : null}
        </div> : null}
        <div className="today-lead">
          {running.length ? (
            <section className="ember-deck" aria-label="Running timers">
              {running.map((timer, index) => (
                <TimerCard key={timer.uuid ?? timer.id} timer={timer} now={now} compact={index > 0} />
              ))}
            </section>
          ) : (
            <StartCard items={data.quick_starts} />
          )}
        </div>
        {!firstRun ? <aside className="today-rail">
          {data.commitments.length ? <section className="today-commitments" aria-label="Commitment summary">
            <header className="today-section-head"><h2>Commitments</h2><span className="today-scope">All contexts</span></header>
            {data.commitments.map(item => <CommitmentSummary key={item.commitment.id} commitment={item.commitment} compact><CommitmentHistory item={item} /></CommitmentSummary>)}
            </section> : null}
        </aside> : null}
        {!firstRun ? <section className="today-journal" aria-label="Today's journal">
          <JournalDay label="Today's journal · saved time" minutes={today?.totalMinutes}>
            {today?.sessions.map((session) => <SessionBand key={session.id} session={session} day={today.date} hideDuration={today.sessions.length === 1} />)}
          </JournalDay>
          {!today ? <p className="empty">Your saved sessions and notes will gather here.</p> : null}
          <AppLink className="today-all-sessions quiet-link" href={urls.sessions()}>All sessions</AppLink>
        </section> : null}
      </div>
    </div>
  );
}

function TimerCard({ timer, now, compact }: { timer: Timer; now: number; compact?: boolean }) {
  const stash = useRef<() => void>(() => undefined);
  return <FocusCard timer={timer} now={now} compact={compact} beforeStop={() => stash.current()}>
    <TimerNoteEditor timer={timer} registerStash={(fn) => { stash.current = fn; }} />
  </FocusCard>;
}

/** Recent project and subproject pairs, each project's subprojects beneath it. */
function pickupRows(items: Dashboard["quick_starts"]) {
  const projects = new Map<number, Dashboard["quick_starts"]>();
  for (const item of items) {
    const pairs = projects.get(item.project.id) ?? [];
    const key = item.subprojects.map((sub) => sub.id).sort().join(",");
    if (!pairs.some((pair) => pair.subprojects.map((sub) => sub.id).sort().join(",") === key)) projects.set(item.project.id, [...pairs, item]);
  }
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
          {sublabel ? nested ? <span className="capture-pick-label"><span className="capture-pick-sub text-blue">{sublabel}</span></span> : <CapturePickLabel project={item.project.name} sublabel={sublabel} /> : <CapturePickLabel project={item.project.name} />}
        </button>;
      })}
      <CaptureLink className="today-quick-pick today-something-else"><Icon icon={faSearch} /><span>Another project</span></CaptureLink>
      <CaptureLink className="today-quick-pick today-log-past" mode="past"><Icon icon={faHistory} /><span>Log past time</span></CaptureLink>
    </div>
  </section>;
}

function WeekEmbers({ timeline, running, now }: { timeline: Parameters<typeof ledgerEntries>[0]; running: Timer[]; now: number }) {
  const monday = new Date(now); monday.setDate(monday.getDate() - (monday.getDay() + 6) % 7); monday.setHours(0, 0, 0, 0);
  const totals = new Map<string, number>();
  for (const block of ledgerEntries(timeline, running, now)) {
    for (const part of dayPortions({ start: block.start, end: block.end ?? new Date(now).toISOString(), duration_minutes: block.minutes })) totals.set(part.date, (totals.get(part.date) ?? 0) + part.minutes);
  }
  const days = Array.from({ length: 7 }, (_, index) => { const date = new Date(monday); date.setDate(date.getDate() + index); return { date, minutes: totals.get(localDateKey(date)) ?? 0 }; });
  const max = Math.max(60, ...days.map((day) => day.minutes));
  return <AppLink className="today-week" href={urls.review()} aria-label={`This week. ${days.map((day) => `${formatDayDate(day.date)}: ${formatDuration(day.minutes)}`).join(". ")}. Open review.`}>
    <span>This week</span><span className="week-embers" aria-hidden="true">{days.map(({ date, minutes }) => <span className="week-ember-day" key={localDateKey(date)} title={`${formatDayDate(date)} · ${formatDuration(minutes)}`} data-today={localDateKey(date) === localDateKey(new Date(now)) || undefined}><i data-level={minutes > 0 ? Math.max(1, Math.ceil(minutes / max * 4)) : 0} /><small>{formatDayDate(date).slice(0, 1)}</small></span>)}</span>
  </AppLink>;
}
