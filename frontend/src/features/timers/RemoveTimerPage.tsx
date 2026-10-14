import { useEffect, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";
import { faArrowLeft, faExclamationTriangle, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { elapsedSeconds, formatDurationWords } from "@/lib/format";
import { useDeleteTimer, useNow, useTimers } from "./api";

/* "Remove timer?" (remove_timer.html). The cards remove inline with a
   confirm dialog; this page keeps the old URL working. */
export default function RemoveTimerPage() {
  const { sessionId } = useParams();
  const id = Number(sessionId);
  const timers = useTimers();
  const remove = useDeleteTimer();
  const navigate = useNavigate();
  const toast = useToast();
  const now = useNow();
  const timer = timers.data?.find((t) => t.id === id);

  useEffect(() => {
    if (timers.isSuccess && !timer && !remove.isPending && !remove.isSuccess) {
      toast.info("That timer has already stopped.");
      navigate(urls.timers(), { replace: true });
    }
  }, [timers.isSuccess, timer, remove.isPending, remove.isSuccess, navigate, toast]);

  if (timers.isPending || !timer) {
    return timers.isError ? (
      <ErrorState error={timers.error} onRetry={() => void timers.refetch()} />
    ) : (
      <section className="slab">
        <Skeleton lines={3} />
      </section>
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    remove
      .mutateAsync(timer)
      .then(() => {
        toast.success("Removed timer");
        navigate(urls.timers());
      })
      .catch((error) => toast.error(`Couldn't remove: ${errorMessage(error)}`));
  };

  return (
    <>
      <div className="desk-head">
        <div>
          <h1 className="page-title">Remove timer?</h1>
        </div>
      </div>
      <form onSubmit={submit}>
        <section className="slab slab-pad" id={`timer-${timer.id}`}>
          <div className="project-top">
            <AppLink className="project-name" href={urls.updateProject(timer.project.id)}>
              {timer.project.name}
            </AppLink>
          </div>
          {timer.subproject_allocations.length ? (
            <div className="project-subs">
              {timer.subproject_allocations.map((sub) => (
                <span className="sub-chip" key={sub.subproject_id}>
                  {sub.name}
                </span>
              ))}
            </div>
          ) : null}
          <p className="project-total">
            <span className="timer-duration">{formatDurationWords(elapsedSeconds(timer.start, now) / 60)}</span>{" "}
            <span className="muted">running</span>
          </p>
        </section>
        <p className="confirm-warn">
          <Icon icon={faExclamationTriangle} /> Removing discards this timer without recording a session. To keep the time,{" "}
          <AppLink href={urls.stopTimer(timer.id)}>stop it</AppLink> instead.
        </p>
        <div className="form-actions">
          <AppLink className="btn btn--ghost" href={urls.timers()}>
            <Icon icon={faArrowLeft} /> Back
          </AppLink>
          <button className="btn btn--stop btn--spacer" type="submit" disabled={remove.isPending}>
            <Icon icon={faTrash} /> Remove timer
          </button>
        </div>
      </form>
    </>
  );
}
