import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { faArrowLeft, faCheck } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { LocalTimeNotice, useLocalTime, type LocalTimeField } from "@/components/LocalTimeNotice";
import { NoteEditor } from "@/components/NoteEditor";
import { AllocationEditor } from "@/components/AllocationEditor";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { FieldErrors, FormLevelErrors } from "@/features/contexts-tags/ui";
import { NO_ERRORS, parseFormErrors, type FormErrors } from "@/features/contexts-tags/formErrors";
import { useLogSession, type LogSessionInput } from "@/features/sessions/api";
import type { AllocationWrite } from "@/lib/allocation";
import { formatDurationWords, localDateKey, toDateTimeLocal } from "@/lib/format";
import { ProjectFields, type ProjectPick } from "./ProjectPick";

/* Lengths offered as one tap: each sets the start that far before the end. */
const LENGTHS = [15, 30, 45, 60, 120];
const NEED_PROJECT = "Choose a project.";
const lengthLabel = (minutes: number) => (minutes < 60 ? `${minutes}m` : `${minutes / 60}h`);

/** A stretch to log, from a link (a Home timeline gap): exact ISO instants,
 *  and where to go once it is saved. */
export interface LogPrefill {
  start: string;
  end: string;
  next: string | null;
}

/** The instant to send. While a prefilled field still shows its original
 *  second (and occurrence, in a repeated DST hour) the original string goes
 *  as it came, sub-second part and all; an edit sends the field's instant. */
export function exactInstant(field: LocalTimeField, original: string | undefined): string | null {
  if (!field.instant || !original) return field.instant;
  const second = (iso: string) => Math.floor(Date.parse(iso) / 1000);
  return second(field.instant) === second(original) ? original : field.instant;
}

/* Log a session that already happened: the end defaults to now (to the
   minute) and the start to an hour before, so "an hour, just now" is one
   tap; the length buttons move the start and keep the end. A prefill opens
   it on an exact stretch instead, to the second. */
export function LogSessionForm({ pick, autoFocus, prefill = null }: { pick: ProjectPick; autoFocus: boolean; prefill?: LogPrefill | null }) {
  const navigate = useNavigate();
  const toast = useToast();
  const log = useLogSession();
  const [uuid] = useState(() => crypto.randomUUID());
  const seconds = !!prefill;
  const [end, setEnd] = useState(() => (prefill ? toDateTimeLocal(prefill.end, true) : toDateTimeLocal(new Date(), false)));
  const [start, setStart] = useState(() =>
    prefill ? toDateTimeLocal(prefill.start, true) : toDateTimeLocal(new Date(Date.parse(end) - 60 * 60_000), false),
  );
  const [note, setNote] = useState("");
  const [allocations, setAllocations] = useState<AllocationWrite[] | null>(null);
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);
  const startTime = useLocalTime(start, prefill?.start);
  const endTime = useLocalTime(end, prefill?.end);
  const startAt = exactInstant(startTime, prefill?.start);
  const endAt = exactInstant(endTime, prefill?.end);

  const { project, chosen } = pick;
  /* Fractional: a prefilled stretch runs to the second. */
  const minutes = startAt && endAt ? (Date.parse(endAt) - Date.parse(startAt)) / 60_000 : null;

  const setLength = (length: number) => {
    const until = endAt ? Date.parse(endAt) : Date.now();
    setStart(toDateTimeLocal(new Date(until - length * 60_000), seconds));
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const fields: Record<string, string[]> = {};
    if (!project) fields.project_id = [NEED_PROJECT];
    if (!startAt) fields.start = [startTime.error ?? "Enter when it started."];
    if (!endAt) fields.end = [endTime.error ?? "Enter when it ended."];
    else if (Date.parse(endAt) > Date.now()) fields.end = ["The end can't be in the future."];
    else if (minutes !== null && minutes <= 0) fields.end = ["The end must be after the start."];
    setErrors({ fields, general: [] });
    if (!project || !startAt || !endAt || Object.keys(fields).length) return;

    const input: LogSessionInput = {
      uuid,
      project_id: project.id,
      start: startAt,
      end: endAt,
      note: note.trim() ? note : null,
      ...(allocations ? { subproject_allocations: allocations } : { subproject_ids: chosen.map((s) => s.id) }),
    };
    log.mutate({ ...input, projectName: project.name, subprojects: chosen.map((s) => ({ id: s.id, name: s.name })) }, {
      onSuccess: (result) => {
        if (result === "queued") {
          toast.info(`Saved ${formatDurationWords(minutes)} of ${project.name} on this device. It syncs when Autumn can be reached.`);
          navigate(prefill?.next ?? urls.timers());
          return;
        }
        toast.success(`Logged ${formatDurationWords(minutes)} of ${project.name}.`);
        if (prefill?.next) {
          navigate(prefill.next);
          return;
        }
        const day = (iso: string) => localDateKey(new Date(iso));
        navigate(`${urls.sessions()}?start_date=${day(input.start)}&end_date=${day(input.end)}`);
      },
      onError: (error) => setErrors(parseFormErrors(error, { fieldMap: { subproject_ids: "project_id", subproject_allocations: "form" } })),
    });
  };

  /* A field's own LocalTimeNotice already shows the skipped-hour error. */
  const timeErrors = (key: string, own: string | null) => errors.fields[key]?.filter((message) => message !== own);

  return (
    <form className="fields" onSubmit={submit} noValidate>
      <FormLevelErrors errors={[...errors.general, ...(errors.fields.form ?? [])]} />
      <ProjectFields pick={pick} autoFocus={autoFocus} error={errors.fields.project_id?.filter((message) => !project || message !== NEED_PROJECT)} />
      <section className="slab slab-pad">
        <p className="project-total" role="status">
          <span className="timer-duration">{minutes !== null && minutes > 0 ? formatDurationWords(minutes) : "—"}</span>{" "}
          <span className="muted">logged</span>
        </p>
        <div className="preset-row" role="group" aria-label="How long it lasted">
          {LENGTHS.map((length) => (
            <button
              key={length}
              type="button"
              className="timer-preset-button"
              aria-pressed={minutes !== null && Math.abs(minutes - length) < 1 / 120}
              onClick={() => setLength(length)}
            >
              {lengthLabel(length)}
            </button>
          ))}
        </div>
        <div className="two-up u-mt-4">
          <div className="field">
            <label htmlFor="log-start">Start time</label>
            <input id="log-start" type="datetime-local" step={seconds ? 1 : 60} value={start} onChange={(e) => setStart(e.target.value)} />
            <FieldErrors errors={timeErrors("start", startTime.error)} />
            <LocalTimeNotice field={startTime} label="the start" />
          </div>
          <div className="field">
            <label htmlFor="log-end">End time</label>
            <input id="log-end" type="datetime-local" step={seconds ? 1 : 60} value={end} onChange={(e) => setEnd(e.target.value)} />
            <FieldErrors errors={timeErrors("end", endTime.error)} />
            <LocalTimeNotice field={endTime} label="the end" />
          </div>
        </div>
        <NoteEditor id="log-note" value={note} onChange={setNote} rows={10} placeholder="Session Note..." error={errors.fields.note} />
        <AllocationEditor items={chosen.map((s) => ({ id: s.id, name: s.name }))} onChange={setAllocations} collapsible />
      </section>
      <div className="form-actions">
        <AppLink className="btn btn--ghost" href={prefill?.next ?? urls.timers()}>
          <Icon icon={faArrowLeft} /> Back
        </AppLink>
        <button type="submit" id="log-session" className="btn btn--primary btn--lg btn--spacer" disabled={log.isPending}>
          <Icon icon={faCheck} /> Log session
        </button>
      </div>
    </form>
  );
}
