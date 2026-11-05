import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router";
import { Sheet } from "@/components/Sheet";
import { useNoteDraft, readNoteDraft, clearNoteDraft } from "@/lib/noteDraft";
import { NoteEditor, takeNoteDraft } from "@/components/NoteEditor";
import { AllocationEditor } from "@/components/AllocationEditor";
import { LocalTimeNotice, useLocalTime } from "@/components/LocalTimeNotice";
import { ErrorState, Skeleton } from "@/components/states";
import { useToast } from "@/app/toasts";
import { api, unwrap } from "@/api/client";
import { ApiError, errorMessage } from "@/api/errors";
import { useInvalidate } from "@/api/sync";
import type { Timer } from "@/api/types";
import { formatDate, formatDuration, toDateTimeLocal } from "@/lib/format";
import { updateQueuedStart } from "@/lib/offlineQueue";
import HomePage from "@/features/dashboard/HomePage";
import { useStopTimer, useTimers } from "./api";

export default function StopTimerPage() {
  const { sessionId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const requestedAt = useRef(location.state?.stopRequestedAt ?? Date.now());
  const timers = useTimers();
  const [initial, setInitial] = useState<Timer | null>(null);
  const found = initial ?? timers.data?.find((t) => t.id === Number(sessionId));
  useEffect(() => {
    if (found && !initial) setInitial(found);
  }, [found, initial]);
  return (
    <>
      <HomePage />
      {found ? (
        <StopSheet key={found.id} timer={found} requestedAt={requestedAt.current} />
      ) : timers.isPending ? (
        <Skeleton />
      ) : (
        <Sheet open title="Timer" onClose={() => navigate("/")}>
          <ErrorState error={timers.error ?? new Error("This timer has already stopped.")} />
        </Sheet>
      )}
    </>
  );
}

function StopSheet({ timer, requestedAt }: { timer: Timer; requestedAt: number }) {
  const navigate = useNavigate();
  const toast = useToast();
  const invalidate = useInvalidate();
  const stop = useStopTimer();
  const [offline, setOffline] = useState(() => !navigator.onLine || !!timer.pending_sync);
  const draftKey = `session:${timer.uuid ?? timer.id}`;
  const [openingNote] = useState(() => readNoteDraft(draftKey)?.text ?? sessionStorage.getItem(`autumn:timer-note-draft:${timer.uuid ?? timer.id}`) ?? sessionStorage.getItem(`autumn:timer-note-draft:${timer.id}`) ?? timer.note ?? "");
  const [current, setCurrent] = useState(timer);
  const currentRef = useRef(current);
  currentRef.current = current;
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [start, setStart] = useState(() => toDateTimeLocal(timer.start));
  const [end, setEnd] = useState(() => toDateTimeLocal(new Date(requestedAt)));
  const [endTouched, setEndTouched] = useState(false);
  const [allocations, setAllocations] = useState<{ subproject_id: number; allocation_bp: number }[] | null>(null);
  const startTime = useLocalTime(start, timer.start);
  const endTime = useLocalTime(end);
  const launched = useRef(false);
  const initialNote = useRef(openingNote);
  const draft = useNoteDraft({
    draftKey, text: openingNote, version: timer.version, enabled: saved && !current.pending_sync,
    save: async (note, version) => {
      const result = await unwrap(api.PATCH("/api/v2/sessions/{session_id}", {
        params: { path: { session_id: currentRef.current.id }, header: { "If-Match": version } }, body: { note },
      })) as Timer;
      currentRef.current = result;
      setCurrent(result);
      invalidate("sessions");
      return result;
    },
  });
  const note = draft.value;
  const stopNow = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await stop.mutateAsync({
        timer: current,
        note: initialNote.current,
        end: new Date(requestedAt).toISOString(),
        queueOnFailure: false,
      });
      currentRef.current = result;
      setCurrent(result);
      draft.accept(initialNote.current, result.version);
      setSaved(true);
      if (result.pending_sync) toast.info("Stop saved on this device. It will sync when connected.");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 0) setOffline(true);
      else setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (!offline && !launched.current) {
      launched.current = true;
      void stopNow();
    }
  }, []);
  const done = async () => {
    if (busy) return;
    if (!startTime.instant || (endTouched && !endTime.instant)) {
      setError("Choose valid start and end times.");
      return;
    }
    const endIso = endTouched ? endTime.instant! : new Date(requestedAt).toISOString();
    if (Date.parse(endIso) < Date.parse(startTime.instant)) {
      setError("End time cannot be earlier than start time.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (saved && !current.pending_sync && !(await draft.flush())) return;
      let target = currentRef.current;
      if (!saved) {
        if (start !== toDateTimeLocal(timer.start)) {
          if (timer.pending_sync && timer.uuid) updateQueuedStart(timer.uuid, startTime.instant);
          else
            target = (await unwrap(
              api.PATCH("/api/v2/sessions/{session_id}", {
                params: { path: { session_id: timer.id }, header: { "If-Match": target.version } },
                body: { start: startTime.instant },
              }),
            )) as Timer;
        }
        await stop.mutateAsync({ timer: target, note, end: endIso, ...(allocations ? { allocations } : {}) });
      } else if (endTouched || start !== toDateTimeLocal(timer.start) || allocations) {
        if (current.pending_sync) {
          setError("This stop is queued. Reconnect before editing the saved session.");
          return;
        }
        target = (await unwrap(
          api.PATCH("/api/v2/sessions/{session_id}", {
            params: { path: { session_id: target.id }, header: { "If-Match": target.version } },
            body: {
              start: startTime.instant,
              end: endIso,
              ...(allocations ? { subproject_allocations: allocations } : {}),
            },
          }),
        )) as Timer;
        setCurrent(target);
        invalidate("sessions");
      }
      clearNoteDraft(draftKey, note);
      takeNoteDraft(timer.id);
      if (timer.uuid) takeNoteDraft(timer.uuid);
      toast.success("Session saved.");
      navigate("/");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  };
  const undo = async () => {
    if (!saved) {
      navigate("/");
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (saved && !current.pending_sync && !(await draft.flush())) return;
      let target = currentRef.current;
      await unwrap(
        api.POST("/api/v2/timers/{session_id}/restart/", {
          params: { path: { session_id: target.id }, header: { "If-Match": target.version } },
          body: { start: timer.start },
        }),
      );
      clearNoteDraft(draftKey, note);
      takeNoteDraft(timer.id);
      if (timer.uuid) takeNoteDraft(timer.uuid);
      invalidate("timers", "sessions");
      toast.info("Timer is running again.");
      navigate("/");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet
      open
      title={offline ? "Finish your session" : saved ? "Time saved. A moment to reflect." : "Saving your time..."}
      className="capture-sheet stop-sheet"
      onClose={() => {
        if (offline && !saved) navigate("/");
        else void done();
      }}
    >
      <div className="stop-summary">
        <h2 className="text-red">{timer.project.name}</h2>
        <span className="timer-duration text-green">
          {formatDuration((requestedAt - Date.parse(timer.start)) / 60000)}
        </span>
      </div>
      {offline ? (
        <p className="muted">Add your note before stopping. Your session will sync when Autumn is reachable.</p>
      ) : null}
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      <form
        className="fields"
        onSubmit={(e) => {
          e.preventDefault();
          void done();
        }}
      >
        <NoteEditor
          sessionTitle={`${timer.project.name} · ${formatDate(timer.start)} · ${formatDuration((requestedAt - Date.parse(timer.start)) / 60000)}`}
          id="id_note"
          disabled={busy && (saved || offline)}
          value={note}
          onChange={draft.change}
          onDone={saved ? draft.flush : undefined}
          saveStatus={draft.status}
          onRetry={() => void draft.flush()}
          onBlur={() => { if (saved) void draft.flush(); }}
          autoFocus
          rows={10}
          placeholder="What moved forward? What is on your mind?"
        />
        <details className="capture-options">
          <summary>Adjust times & allocation</summary>
          <div className="two-up">
            <div className="field">
              <label htmlFor="id_start_time">Start time</label>
              <input
                id="id_start_time"
                type="datetime-local"
                step={1}
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
              <LocalTimeNotice field={startTime} label="the start" />
            </div>
            <div className="field">
              <label htmlFor="id_end_time">End time</label>
              <input
                id="id_end_time"
                type="datetime-local"
                step={1}
                value={end}
                onChange={(e) => {
                  setEnd(e.target.value);
                  setEndTouched(true);
                }}
              />
              <LocalTimeNotice field={endTime} label="the end" />
            </div>
          </div>
          <AllocationEditor
            items={timer.subproject_allocations.map((a) => ({
              id: a.subproject_id,
              name: a.name,
              bp: a.allocation_bp,
            }))}
            onChange={setAllocations}
            collapsible
          />
        </details>
        <div className="capture-footer">
          <button
            type="button"
            className="btn btn--quiet"
            disabled={busy || (!!current.pending_sync && saved)}
            onClick={() => void undo()}
          >
            {offline && !saved ? "Cancel" : "Undo stop"}
          </button>
          <button type="submit" className="btn btn--primary" disabled={busy || (!offline && !saved)}>
            {offline && !saved ? "Stop timer" : "Done"}
          </button>
        </div>
        {error && !saved && !offline ? (
          <button type="button" className="btn btn--secondary" onClick={() => void stopNow()} disabled={busy}>
            Retry saving
          </button>
        ) : null}
      </form>
    </Sheet>
  );
}
