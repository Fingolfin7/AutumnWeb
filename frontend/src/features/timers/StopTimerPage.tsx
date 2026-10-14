import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";
import { faArrowLeft, faStopwatch } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { NoteEditor } from "@/components/NoteEditor";
import { AllocationEditor } from "@/components/AllocationEditor";
import { ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useToast, type Celebration } from "@/app/toasts";
import { api, unwrap } from "@/api/client";
import { ApiError, errorMessage } from "@/api/errors";
import { useInvalidate } from "@/api/sync";
import type { Timer } from "@/api/types";
import { elapsedSeconds, formatDurationWords, fromDateTimeLocal, toDateTimeLocal } from "@/lib/format";
import { updateQueuedStart } from "@/lib/offlineQueue";
import { useNow, useStopTimer, useTimers } from "./api";

/* Stop a timer (stop_timer.html): adjust start/end, write the note (a draft
   typed on the Timers page carries over), split the time across subprojects,
   then stop. Leaving End untouched stops at the moment you press the button,
   not when the page opened. */
export default function StopTimerPage() {
  const { sessionId } = useParams();
  const id = Number(sessionId);
  const timers = useTimers();
  const navigate = useNavigate();
  const toast = useToast();
  const found = timers.data?.find((t) => t.id === id);
  /* Stopping removes the timer from the list at once (optimistic), so once
     submitted, keep the form on the timer as it was and skip the "already
     stopped elsewhere" redirect. */
  const [stopping, setStopping] = useState<Timer | null>(null);
  const timer = stopping ?? found;

  useEffect(() => {
    if (timers.isSuccess && !timer) {
      toast.info("That timer has already stopped.");
      navigate(urls.timers(), { replace: true });
    }
  }, [timers.isSuccess, timer, navigate, toast]);

  if (timers.isPending || (timers.isSuccess && !timer)) {
    return (
      <section className="slab">
        <Skeleton lines={4} />
      </section>
    );
  }
  if (timers.isError || !timer) return <ErrorState error={timers.error} onRetry={() => void timers.refetch()} />;
  return <StopForm timer={timer} onSubmitting={() => setStopping(timer)} />;
}

function StopForm({ timer, onSubmitting }: { timer: Timer; onSubmitting: () => void }) {
  const navigate = useNavigate();
  const toast = useToast();
  const invalidate = useInvalidate();
  const stop = useStopTimer();
  const now = useNow();
  const openedAt = useRef(new Date());

  const initialStart = useMemo(() => toDateTimeLocal(timer.start), [timer.start]);
  const [start, setStart] = useState(initialStart);
  const [end, setEnd] = useState(() => toDateTimeLocal(openedAt.current));
  const [endTouched, setEndTouched] = useState(false);
  const [note, setNote] = useState(timer.note ?? "");
  const [allocations, setAllocations] = useState<{ subproject_id: number; allocation_bp: number }[] | null>(null);
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [busy, setBusy] = useState(false);

  /* Until End is edited, keep it showing "now". */
  useEffect(() => {
    if (!endTouched) setEnd(toDateTimeLocal(new Date(now)));
  }, [now, endTouched]);

  const items = timer.subproject_allocations.map((a) => ({ id: a.subproject_id, name: a.name, bp: a.allocation_bp }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const startIso = fromDateTimeLocal(start);
    const endIso = endTouched ? fromDateTimeLocal(end) : new Date().toISOString();
    const nextErrors: Record<string, string[]> = {};
    if (!startIso) nextErrors.start = ["Enter a valid date and time."];
    if (!endIso) nextErrors.end = ["Enter a valid date and time."];
    if (startIso && endIso && new Date(endIso) < new Date(startIso)) nextErrors.end = ["End time cannot be earlier than start time."];
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    setBusy(true);
    onSubmitting();
    try {
      let current = timer;
      if (start !== initialStart && timer.pending_sync && timer.uuid) {
        /* Not on the server yet: correct the queued start instead. */
        updateQueuedStart(timer.uuid, startIso!);
      } else if (start !== initialStart) {
        /* The stop endpoint only takes the end; a corrected start is saved
           first, carrying the version forward. */
        current = (await unwrap(
          api.PATCH("/api/v2/sessions/{session_id}", {
            params: { path: { session_id: timer.id }, header: { "If-Match": timer.version } },
            body: { start: startIso! },
          }),
        )) as Timer;
      }
      const result = (await stop.mutateAsync({
        timer: current,
        note,
        ...(allocations ? { allocations } : {}),
        end: endIso!,
      })) as Timer & { celebration?: { kind: Celebration; message: string } | null };
      try {
        window.sessionStorage.removeItem(`autumn:timer-note-draft:${timer.id}`);
      } catch {
        /* storage unavailable */
      }
      if (result.pending_sync) {
        toast.info("Stopped. Saved on this device; it syncs when Autumn is reachable.");
      } else if (result.celebration) {
        toast.success(result.celebration.message, { celebration: result.celebration.kind });
      } else {
        toast.success("Stopped timer");
      }
      invalidate("timers", "sessions");
      navigate(urls.timers());
    } catch (error) {
      if (error instanceof ApiError && error.status === 400) {
        const details = (error.details ?? {}) as Record<string, string[] | string>;
        const mapped: Record<string, string[]> = {};
        for (const [key, value] of Object.entries(details)) {
          const target = key === "start" || key === "start_time" ? "start" : key === "end" || key === "end_time" ? "end" : key === "note" ? "note" : "form";
          mapped[target] = [...(mapped[target] ?? []), ...(Array.isArray(value) ? value : [String(value)])];
        }
        setErrors(Object.keys(mapped).length ? mapped : { form: [error.message] });
      } else {
        toast.error(`Couldn't stop the timer: ${errorMessage(error)}`);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="desk-head">
        <div>
          <h1 className="page-title text-red">{timer.project.name}</h1>
        </div>
      </div>
      <form className="fields" onSubmit={submit} noValidate>
        {errors.form ? (
          <ul className="errorlist nonfield">
            {errors.form.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        ) : null}
        <section className="slab slab-pad" id={`timer-${timer.id}`}>
          <div className="project-top">
            <span className="project-name">{timer.project.name}</span>
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
            <span className="muted">so far</span>
          </p>
        </section>
        <section className="slab slab-pad">
          <div className="two-up">
            <div className="field">
              <label htmlFor="id_start_time">Start time</label>
              <input id="id_start_time" type="datetime-local" step={1} className="half-width" value={start} onChange={(e) => setStart(e.target.value)} />
              <Errors messages={errors.start} />
            </div>
            <div className="field">
              <label htmlFor="id_end_time">End time</label>
              <input
                id="id_end_time"
                type="datetime-local"
                step={1}
                className="half-width"
                value={end}
                onChange={(e) => {
                  setEndTouched(true);
                  setEnd(e.target.value);
                }}
              />
              <Errors messages={errors.end} />
            </div>
          </div>
          <NoteEditor id="id_note" value={note} onChange={setNote} draftKey={timer.id} placeholder="Session Note..." error={errors.note} />
          <AllocationEditor items={items} onChange={setAllocations} collapsible />
        </section>
        <div className="form-actions">
          <AppLink className="btn btn--ghost" href={urls.timers()}>
            <Icon icon={faArrowLeft} /> Back
          </AppLink>
          <button className="btn btn--stop btn--lg btn--spacer" type="submit" disabled={busy}>
            <Icon icon={faStopwatch} /> Stop timer
          </button>
        </div>
      </form>
    </>
  );
}

function Errors({ messages }: { messages?: string[] }) {
  if (!messages?.length) return null;
  return (
    <ul className="errorlist">
      {messages.map((message) => (
        <li key={message}>{message}</li>
      ))}
    </ul>
  );
}
