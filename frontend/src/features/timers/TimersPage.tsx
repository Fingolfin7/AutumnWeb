import { useRef } from "react";
import { faPlay } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import type { Timer } from "@/api/types";
import { FocusCard } from "./FocusCard";
import { FocusDeck } from "./FocusDeck";
import { Suggestions } from "./Suggestions";
import { TimerNoteEditor } from "./TimerNoteEditor";
import { TimerReminders } from "./TimerReminders";
import { useNow, useTimers } from "./api";

/* Timers (timers.html): the running timers ARE the content, each with its
   reminders and a live note; suggestions sit beside them. */
export default function TimersPage() {
  const timers = useTimers();
  const now = useNow();

  return (
    <>
      <h1 className="sr-only">Timers</h1>
      <div className="desk">
        <div className="desk-main">
          {timers.isPending ? (
            <section className="slab">
              <Skeleton lines={4} height="2rem" />
            </section>
          ) : timers.isError && !timers.data ? (
            <ErrorState error={timers.error} onRetry={() => void timers.refetch()} />
          ) : (
            <FocusDeck label="Running timers">
              {(timers.data ?? []).map((timer) => (
                <TimerCard key={timer.id} timer={timer} now={now} />
              ))}
              <article className="focus-card focus-card--start" aria-label="Start a new timer">
                <div className="focus-actions">
                  <AppLink className="btn btn--primary btn--lg" href={urls.startTimer()}>
                    <Icon icon={faPlay} /> New timer
                  </AppLink>
                </div>
              </article>
            </FocusDeck>
          )}
        </div>
        <aside className="desk-side">
          <Suggestions />
        </aside>
      </div>
    </>
  );
}

function TimerCard({ timer, now }: { timer: Timer; now: number }) {
  const stash = useRef<() => void>(() => undefined);
  return (
    <FocusCard timer={timer} now={now} beforeStop={() => stash.current()}>
      <TimerReminders timer={timer} />
      <TimerNoteEditor
        timer={timer}
        registerStash={(fn) => {
          stash.current = fn;
        }}
      />
    </FocusCard>
  );
}
