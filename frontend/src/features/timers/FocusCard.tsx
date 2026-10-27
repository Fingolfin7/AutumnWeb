import { Fragment, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { faRedo, faStopwatch, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { ConfirmDialog } from "@/components/Sheet";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import type { Timer } from "@/api/types";
import { elapsedSeconds, formatClock, formatTime, heroParts, parseInstant } from "@/lib/format";
import { useDeleteTimer, useRestartTimer } from "./api";

export const NOTE_DRAFT_KEY_PREFIX = "autumn:timer-note-draft:";

/* A running timer as a .focus-card (partials/active_timers_*.html). Live
   figures are computed from `now`, which the parent ticks once a second, so
   every card on the page shares one clock. `children` slot in above the
   actions (the Timers page puts reminders and the note editor there). */
export function FocusCard({
  timer,
  now,
  children,
  beforeStop,
}: {
  timer: Timer;
  now: number;
  children?: ReactNode;
  /** Runs before navigating to the stop page (e.g. stash an unsaved note). */
  beforeStop?: () => void;
}) {
  const toast = useToast();
  const navigate = useNavigate();
  const restart = useRestartTimer();
  const remove = useDeleteTimer();
  const [confirmRemove, setConfirmRemove] = useState(false);
  /* In flight to the server; a queued offline timer is settled locally. */
  const pending = timer.id < 0 && !timer.pending_sync;

  const elapsed = elapsedSeconds(timer.start, now);
  const start = parseInstant(timer.start);
  const stopAt = parseInstant(timer.auto_stop_at);
  const countdown = stopAt ? Math.max(0, Math.floor((stopAt.getTime() - now) / 1000)) : null;
  const fill =
    stopAt && start && stopAt > start
      ? Math.max(0, Math.min(100, ((now - start.getTime()) / (stopAt.getTime() - start.getTime())) * 100))
      : 0;

  return (
    <article
      className="focus-card"
      id={`timer-${timer.id}`}
      data-timer-id={timer.id}
      aria-label={`Running timer: ${timer.project.name}`}
      aria-busy={pending || undefined}
    >
      <p className="focus-eyebrow">
        <span className="live-dot" /> {pending ? "Starting…" : timer.pending_sync ? "Running · saved offline" : "Running"}
      </p>
      <h2 className="focus-project">
        <AppLink href={urls.updateProject(timer.project.id)}>{timer.project.name}</AppLink>
      </h2>
      {timer.subproject_allocations.length ? (
        <div className="focus-subs">
          {timer.subproject_allocations.map((sub) => (
            <Fragment key={sub.subproject_id}>
              <AppLink className="sub-chip" href={urls.updateSubproject(sub.subproject_id)}>
                {sub.name}
              </AppLink>{" "}
            </Fragment>
          ))}
        </div>
      ) : null}
      <p className="focus-time" aria-live="off">
        {heroParts(elapsed).map((part) => (
          <span className="focus-time-part" key={part.unit}>
            <span className="num">{part.value}</span>
            <span className="unit">{part.unit}</span>
          </span>
        ))}
      </p>
      <div className="focus-autostop">
        <span>
          started <span className="mono">{formatTime(timer.start)}</span>
        </span>
        {countdown !== null ? (
          <span>
            stops in <span className="mono">{formatClock(countdown)}</span>
          </span>
        ) : (
          <span className="muted">no auto-stop</span>
        )}
      </div>
      {stopAt ? (
        <div className="focus-autostop-bar">
          <div className="focus-autostop-fill" style={{ width: `${fill.toFixed(1)}%` }} />
        </div>
      ) : null}
      {children}
      <div className="focus-actions">
        <AppLink
          className="btn btn--stop btn--lg focus-stop"
          href={urls.stopTimer(timer.id)}
          onClick={(event) => {
            if (pending) {
              event.preventDefault();
              return;
            }
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            const stopRequestedAt = Date.now();
            beforeStop?.();
            navigate(urls.stopTimer(timer.id), { state: { stopRequestedAt } });
          }}
        >
          <Icon icon={faStopwatch} /> Stop
        </AppLink>
        <button
          className="btn-icon"
          type="button"
          title="Restart this timer"
          disabled={pending || timer.pending_sync || restart.isPending}
          onClick={() =>
            restart
              .mutateAsync(timer)
              .then(() => toast.success("Restarted timer"))
              .catch((error) => toast.error(`Couldn't restart: ${errorMessage(error)}`))
          }
        >
          <Icon icon={faRedo} />
          <span className="sr-only">Restart timer</span>
        </button>
        <button
          className="btn-icon btn-icon--danger"
          type="button"
          title="Remove without saving"
          disabled={pending}
          onClick={() => setConfirmRemove(true)}
        >
          <Icon icon={faTrash} />
          <span className="sr-only">Remove timer</span>
        </button>
      </div>
      <ConfirmDialog
        open={confirmRemove}
        title="Remove this timer?"
        body={<>The running {timer.project.name} timer is discarded without saving a session.</>}
        confirmLabel="Remove"
        danger
        busy={remove.isPending}
        onClose={() => setConfirmRemove(false)}
        onConfirm={() => {
          setConfirmRemove(false);
          /* mutateAsync, not mutate(..., callbacks): the card unmounts as soon
             as the optimistic update removes it, and per-call callbacks are
             dropped for unmounted observers. */
          remove
            .mutateAsync(timer)
            .then(() => toast.success("Removed timer"))
            .catch((error) => toast.error(`Couldn't remove: ${errorMessage(error)}`));
        }}
      />
    </article>
  );
}

/* Phone carousel position dots (.focus-dots). Inert on the desk, where CSS
   turns the track into a grid and hides them. */
export function FocusDots({ count, active, onPick }: { count: number; active: number; onPick: (index: number) => void }) {
  return (
    <div className="focus-dots" aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <span key={index} className={`focus-dot${index === active ? " is-active" : ""}`} onClick={() => onPick(index)} />
      ))}
    </div>
  );
}
