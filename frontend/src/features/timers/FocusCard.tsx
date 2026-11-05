import { Fragment, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { faRedo, faStopwatch, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { ConfirmDialog } from "@/components/Sheet";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import type { Timer } from "@/api/types";
import { elapsedSeconds, formatClock, formatTime, parseInstant } from "@/lib/format";
import { useDeleteTimer, useRestartTimer } from "./api";

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
      className={`focus-card ember-clock${elapsed >= 3600 ? " ember-clock--deep" : elapsed >= 1200 ? " ember-clock--warm" : ""}`}
      id={`timer-${timer.id}`}
      data-timer-id={timer.id}
      data-ember-step={Math.min(6, Math.floor(elapsed / 900))}
      aria-label={`Running timer: ${timer.project.name}`}
      aria-busy={pending || undefined}
    >
      <p className="focus-eyebrow">
        <span className="live-dot" /> {pending ? "Starting…" : timer.pending_sync ? "Running · saved offline" : "Running"}
      </p>
      <h2 className="focus-project">
        <AppLink href={urls.updateProject(timer.project.id)}>{timer.project.name}</AppLink>
      </h2>
      <p className="focus-time" aria-live="off">
        <span className="sr-only">{formatClock(elapsed)} elapsed</span>
        {formatClock(elapsed).split(":").map((part, index) => (
          <span className={`focus-time-part${index === 2 ? " focus-seconds" : ""}`} key={index} aria-hidden="true">
            <span className="num">{index === 0 ? Number(part) : part}</span>
            <span className="unit">{["h", "m", "s"][index]}</span>
          </span>
        ))}
      </p>
      <div className="focus-details">
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
      <div className="focus-autostop">
        <span>
          started <span className="mono">{formatTime(timer.start)}</span>
        </span>
        {countdown !== null ? (
          <span>
            stops in <span className="mono">{formatClock(countdown)}</span>
          </span>
        ) : (
          null
        )}
      </div>
      </div>
      {stopAt ? (
        <div className="focus-autostop-bar">
          <progress className="focus-autostop-fill" max={100} value={fill} aria-label="Auto-stop progress" />
        </div>
      ) : null}
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
      {children}
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
