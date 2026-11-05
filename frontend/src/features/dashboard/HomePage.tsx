import { NoteEditor } from "@/components/NoteEditor";
import { clearNoteDraft } from "@/lib/noteDraft";
import { CapturePicker } from "@/features/timers/CapturePicker";
import { useNavigate } from "react-router";
import { useRef, useState } from "react";
import { faPlay } from "@fortawesome/free-solid-svg-icons";
import { EmptyWorkspace } from "@/features/settings/FirstRunPage";
import { Icon } from "@/components/Icon";
import { ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { useActiveContext } from "@/app/context";
import { errorMessage } from "@/api/errors";
import { useAllProjects, useSubprojects } from "@/api/meta";
import type { Project, Timer } from "@/api/types";
import { elapsedSeconds, formatClock, formatDayDate, formatDuration, localDateKey } from "@/lib/format";
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
  const running = [...(timers.data ?? data.active_timers)].sort((a, b) => Date.parse(b.start) - Date.parse(a.start));
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
          {running.map((timer, index) => (
            <TimerCard key={timer.uuid ?? timer.id} timer={timer} now={now} primary={index === 0} />
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
      {!firstRun ? (
        <>
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
          <details className="today-suggestions" onToggle={(event) => setSuggestionsOpen(event.currentTarget.open)}>
            <summary>Need a starting point?</summary>
            {suggestionsOpen ? <Suggestions /> : null}
          </details>

        </>
      ) : null}
    </div>
  );
}

function TimerCard({ timer, now, primary }: { timer: Timer; now: number; primary: boolean }) {
  const stash = useRef<() => void>(() => undefined);
  const [expanded, setExpanded] = useState(false);
  if (!primary && !expanded) return <CompactTimer timer={timer} now={now} onExpand={() => setExpanded(true)} />;
  const editor = <TimerNoteEditor timer={timer} registerStash={(fn) => { stash.current = fn; }} />;
  return (
    <FocusCard timer={timer} now={now} beforeStop={() => stash.current()}>
      {editor}{!primary ? <button className="btn btn--quiet" type="button" onClick={() => setExpanded(false)}>Collapse timer</button> : null}
      <TimerReminders timer={timer} />
    </FocusCard>
  );
}

function CompactTimer({ timer, now, onExpand }: { timer: Timer; now: number; onExpand: () => void }) {
  const navigate = useNavigate();
  return <article className="compact-timer" aria-label={`Running timer: ${timer.project.name}`} id={`timer-${timer.id}`} data-timer-id={timer.id}>
    <button type="button" className="compact-timer-open" onClick={onExpand} aria-label={`Open ${timer.project.name} timer`}>
      <span className="live-dot" /><span className="text-red">{timer.project.name}</span>
      <span className="timer-dock-clock">{formatClock(elapsedSeconds(timer.start, now))}</span>
    </button>
    <AppLink className="btn btn--stop" href={urls.stopTimer(timer.id)} onClick={(event) => { if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); navigate(urls.stopTimer(timer.id), { state: { stopRequestedAt: Date.now() } }); }}>Stop</AppLink>
  </article>;
}

function StartCard({ quickStarts }: { quickStarts: Dashboard["quick_starts"] }) {
  const start = useStartTimer();
  const toast = useToast();
  const [project, setProject] = useState<Project | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [note, setNote] = useState("");
  const subs = useSubprojects(project?.id);
  const quick = [...new Map(quickStarts.map((item) => [`${item.project.id}:${item.subprojects.map((s) => s.id).sort().join(",")}`, item])).values()].slice(0, 4);
  const begin = (chosen: { id: number; name: string }, subprojects: { id: number; name: string }[], text = "") => start.mutate({
    project_id: chosen.id, subproject_ids: subprojects.map((sub) => sub.id), note: text,
    optimistic: { projectName: chosen.name, subprojects },
  }, { onSuccess: () => { clearNoteDraft("capture", text); toast.success(`Started ${chosen.name}.`); }, onError: (error) => toast.error(errorMessage(error)) });
  return <section className="today-idle" aria-label="Start a new timer">
    <form className="today-start-form" onSubmit={(event) => { event.preventDefault(); if (project) begin(project, (subs.data ?? []).filter((sub) => selected.includes(sub.id)), note); }}>
      <label className="today-start-prompt" htmlFor="today-project-search">What are you working on?</label>
      <CapturePicker id="today-project-search" autoFocus={false} placeholder="Find a project" value={project} recent={quickStarts} onChange={(next, ids) => { setProject(next); setSelected(ids); }} />
      {project ? <div className="today-start-details fields">
        {subs.data?.length ? <fieldset className="today-start-subs"><legend>Subproject (optional)</legend>{subs.data.map((sub) => <label className="check-row" key={sub.id}><input type="checkbox" checked={selected.includes(sub.id)} onChange={(event) => setSelected((list) => event.target.checked ? [...list, sub.id] : list.filter((id) => id !== sub.id))} />{sub.name}</label>)}</fieldset> : null}
        <NoteEditor persistKey="capture" value={note} onChange={setNote} rows={3} placeholder="A thought to begin with (optional)" />
        <div className="today-start-actions"><button className="btn btn--primary" disabled={start.isPending}>Start timer</button><AppLink className="btn btn--quiet" href={`${urls.startTimer()}?project_id=${project.id}${selected.map((id) => `&subproject_id=${id}`).join("")}`}>Auto-stop & reminders</AppLink></div>
      </div> : null}
      <AppLink className="btn btn--quiet today-log-past" href="/start_timer/?mode=past">Log past time</AppLink>
    </form>
    {!project && quick.length ? <div className="today-quick"><h3>Pick up where you left off</h3>{quick.map((item) => <button key={`${item.project.id}:${item.subprojects.map((s) => s.id).join(",")}`} className="today-quick-pick" type="button" disabled={start.isPending} onClick={() => begin(item.project, item.subprojects)}>
      <Icon icon={faPlay} /><span><span className="text-red">{item.project.name}</span>{item.subprojects.length ? <small className="text-blue">{item.subprojects.map((s) => s.name).join(", ")}</small> : null}</span><span className="today-quick-verb">Start</span>
    </button>)}</div> : null}
  </section>;
}
