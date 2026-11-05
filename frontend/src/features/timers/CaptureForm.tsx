import { faPlay } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { formatTime, formatDate, toDateTimeLocal } from "@/lib/format";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { LocalTimeNotice, useLocalTime } from "@/components/LocalTimeNotice";
import { CapturePicker, CapturePickLabel } from "./CapturePicker";
import { urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { useAllProjects, useSubprojects } from "@/api/meta";
import { errorMessage } from "@/api/errors";
import { bootstrap } from "@/bootstrap";
import type { Project } from "@/api/types";
import { useStartTimer } from "./api";
import { minutesOf, planReminders, type DurationUnit, type ReminderMode } from "./reminderPlan";
import { PushPermission } from "./PushPermission";
import { clearNoteDraft } from "@/lib/noteDraft";
import { NoteEditor } from "@/components/NoteEditor";
import { AppLink } from "@/app/links";
import { parseDuration } from "./duration";
import { SegmentedControl } from "@/components/ui";
import { useDashboard } from "@/features/dashboard/api";
import { api, unwrap } from "@/api/client";
import { useInvalidate } from "@/api/sync";
import { useQueryClient } from "@tanstack/react-query";
import { keys } from "@/api/keys";

const PRESETS: Record<DurationUnit, { value: number; label: string }[]> = {
  minutes: [15, 25, 30, 45, 60].map((value) => ({ value, label: `${value}m` })),
  hours: [1, 2, 3, 4].map((value) => ({ value, label: `${value}h` })),
};

const MODES: { value: ReminderMode; label: string }[] = [
  { value: "none", label: "None" },
  { value: "after", label: "Once after" },
  { value: "interval", label: "Every" },
  { value: "at", label: "At" },
];

const numberOrNull = (value: string) => {
  const n = Number(value);
  return value.trim() && Number.isFinite(n) && n > 0 ? n : null;
};

/* New timer (start_timer.html + timer_search_projects.js + timer_reminders.js).
   ?project_id=&subproject_id= prefill it (notification action links use
   this). */
export function CaptureForm({ inline = false, onComplete }: { inline?: boolean; onComplete?: () => void }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const start = useStartTimer();
  const projects = useAllProjects();
  const dashboard = useDashboard();
  const invalidate = useInvalidate();
  const client = useQueryClient();
  const [past, setPast] = useState(params.get("mode") === "past");
  const [pastAt, setPastAt] = useState(() => toDateTimeLocal(new Date()).slice(0, 16));
  const [pastDuration, setPastDuration] = useState("45");
  const [pastAnchor, setPastAnchor] = useState("start");
  const [note, setNote] = useState("");
  const pastTime = useLocalTime(pastAt);
  const [savingPast, setSavingPast] = useState(false);
  const [newSub, setNewSub] = useState("");
  const [creatingSub, setCreatingSub] = useState(false);
  const close = () => { onComplete?.(); if (!inline) navigate(urls.home()); };

  const [project, setProject] = useState<Project | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const subprojects = useSubprojects(project?.id);

  const [autoStop, setAutoStop] = useState(false);
  const [stopAmount, setStopAmount] = useState("");
  const [stopUnit, setStopUnit] = useState<DurationUnit>("minutes");
  const [presetActive, setPresetActive] = useState(false);

  const [mode, setMode] = useState<ReminderMode>("none");
  const [afterAmount, setAfterAmount] = useState("");
  const [afterUnit, setAfterUnit] = useState<DurationUnit>("minutes");
  const [intervalAmount, setIntervalAmount] = useState("");
  const [intervalUnit, setIntervalUnit] = useState<DurationUnit>("minutes");
  const [at, setAt] = useState("");
  const [message, setMessage] = useState("");
  const [notifyOnAutoStop, setNotifyOnAutoStop] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const atTime = useLocalTime(at);

  /* Prefill once the project list is in. */
  const [prefilled, setPrefilled] = useState(false);
  useEffect(() => {
    if (prefilled || !projects.data) return;
    setPrefilled(true);
    const projectId = Number(params.get("project_id"));
    const initial = projects.data.find((p) => p.id === projectId);
    if (initial) {
      setProject(initial);
      setSelected(
        params
          .getAll("subproject_id")
          .map(Number)
          .filter((n) => Number.isInteger(n) && n > 0),
      );
    }
  }, [params, prefilled, projects.data]);

  /* The rail's "now" moves on; refresh it every 30 s. */
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const stopAfter = autoStop ? { amount: numberOrNull(stopAmount), unit: stopUnit } : null;
  const plan = useMemo(
    () =>
      planReminders(
        {
          mode,
          stopAfter,
          after: { amount: numberOrNull(afterAmount), unit: afterUnit },
          interval: { amount: numberOrNull(intervalAmount), unit: intervalUnit },
          at: atTime.instant ?? "",
        },
        now,
      ),
    [
      mode,
      stopAfter?.amount,
      stopAfter?.unit,
      afterAmount,
      afterUnit,
      intervalAmount,
      intervalUnit,
      atTime.instant,
      now,
    ],
  );

  const pickProject = (next: Project | null) => {
    if (next?.id !== project?.id) setSelected([]);
    setProject(next);
  };

  const subs = subprojects.data ?? [];
  const allChecked = subs.length > 0 && subs.every((s) => selected.includes(s.id));
  const stopMinutes = minutesOf(stopAfter);
  const summary = project
    ? `${project.name}${stopAmount && autoStop ? ` - stops after ${stopAmount} ${stopUnit}` : ""}`
    : "No project selected";

  const submit = async (event?: FormEvent, chosenProject = project, chosenIds = selected) => {
    event?.preventDefault();
    const project = chosenProject;
    const selected = chosenIds;
    if (!project) return;
    if (past) {
      const duration = parseDuration(pastDuration);
      if (!pastTime.instant || !(duration > 0)) {
        toast.error(pastTime.error ?? "Enter a time and a duration greater than zero.");
        return;
      }
      const anchor = Date.parse(pastTime.instant);
      const from = pastAnchor === "start" ? anchor : anchor - duration * 60000;
      const to = pastAnchor === "start" ? anchor + duration * 60000 : anchor;
      if (to > Date.now()) {
        toast.error("Past time must end before now.");
        return;
      }
      setSavingPast(true);
      try {
        await unwrap(
          api.POST("/api/v2/sessions/", {
            body: {
              project_id: project.id,
              subproject_ids: selected,
              start: new Date(from).toISOString(),
              end: new Date(to).toISOString(),
              note,
            },
          }),
        );
        clearNoteDraft("capture", note);
        invalidate("sessions");
        toast.success("Saved past session.");
        close();
      } catch (error) {
        toast.error(errorMessage(error));
      } finally {
        setSavingPast(false);
      }
      return;
    }
    if (autoStop && !stopMinutes) {
      toast.error("Choose an auto-stop duration greater than zero.");
      return;
    }
    let reminder: Parameters<typeof start.mutate>[0]["reminder"];
    if (mode === "after" || mode === "interval") {
      const amount = numberOrNull(mode === "after" ? afterAmount : intervalAmount);
      if (amount === null) {
        toast.error("Enter how long until the reminder.");
        return;
      }
      reminder = { mode, amount, unit: mode === "after" ? afterUnit : intervalUnit, message };
    } else if (mode === "at") {
      const iso = atTime.instant;
      if (!iso) {
        toast.error(atTime.error ?? "Choose a date and time for the reminder.");
        return;
      }
      reminder = { mode, at: iso, message };
    }
    const chosen = subs.filter((s) => selected.includes(s.id));
    start.mutate(
      {
        project_id: project.id,
        note,
        subproject_ids: selected,
        ...(stopMinutes ? { stop_after_minutes: stopMinutes } : {}),
        ...(notifyOnAutoStop ? { notify_on_auto_stop: true } : {}),
        ...(reminder ? { reminder } : {}),
        optimistic: { projectName: project.name, subprojects: chosen.map((s) => ({ id: s.id, name: s.name })) },
      },
      {
        onSuccess: () => { clearNoteDraft("capture", note); toast.success("Started timer"); },
        onError: (error) => toast.error(`Couldn't start the timer: ${errorMessage(error)}`),
      },
    );
    /* Optimistic: the new card is already on the Timers page. */
    close();
  };

  const zone = bootstrap().profile.timezone || "UTC";

  return (
    <div className={`capture-control${inline ? " capture-control--inline" : ""}`}>
        <div hidden={inline} className="capture-modes range-tabs" role="tablist" aria-label="Capture mode">
          <button
            type="button"
            role="tab"
            aria-selected={!past}
            className={`range-tab${!past ? " is-active" : ""}`}
            onClick={() => setPast(false)}
          >
            Start timer
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={past}
            className={`range-tab${past ? " is-active" : ""}`}
            onClick={() => setPast(true)}
          >
            Log past time
          </button>
        </div>
        <div className="desk-head" hidden={inline}>
          <div>
            <h2 className="page-title">{past ? "A little time, remembered." : "What are you working on?"}</h2>
          </div>
        </div>
        <form className="fields capture-form" onSubmit={submit}>
          <div className={`desk-main${inline && !project ? " capture-awaiting-project" : ""}`}>
            <section className="slab slab-pad">
              <div className="field" id="search-projects">
                <label htmlFor={inline ? "today-project-search" : "project-search"}>{inline ? "What are you working on?" : "Project"}</label>
                <CapturePicker
                  id={inline ? "today-project-search" : "project-search"}
                  autoFocus={!inline}
                  onStart={(next, ids) => { if (!past) void submit(undefined, next, ids); }}
                  value={project}
                  recent={dashboard.data?.quick_starts ?? []}
                  onChange={(next, ids) => {
                    pickProject(next);
                    setSelected(ids);
                  }}
                />
              </div>
            </section>

            {past ? (
              <section className="capture-past fields">
                <div className="preset-row" aria-label="Session date">
                  {["Today", "Yesterday"].map((label, index) => {
                    const date = new Date(); date.setDate(date.getDate() - index);
                    const day = toDateTimeLocal(date).slice(0, 10);
                    return <button className={`btn btn--quiet${pastAt.startsWith(day) ? " is-active" : ""}`} aria-pressed={pastAt.startsWith(day)} type="button" key={label} onClick={() => setPastAt(`${day}T${pastAt.slice(11, 16)}`)}>{label}</button>;
                  })}
                </div>
                <SegmentedControl label="Time anchor" value={pastAnchor} onChange={setPastAnchor} options={[{ value: "start", label: "Started" }, { value: "end", label: "Ended" }]} />
                <div className="field">
                  <label htmlFor="past-at">{pastAnchor === "start" ? "Started" : "Ended"} at {pastAt.slice(11, 16)}</label>
                  <input id="past-at" type="datetime-local" step={60} value={pastAt} onChange={(e) => setPastAt(e.target.value)} required />
                  <LocalTimeNotice field={pastTime} label="the session" />
                </div>
                <div className="field">
                  <label htmlFor="past-duration">Duration</label>
                  <div className="preset-row" aria-label="Duration presets">
                    {[15, 30, 45, 60].map((minutes) => <button key={minutes} type="button" className={`btn btn--quiet${parseDuration(pastDuration) === minutes ? " is-active" : ""}`} aria-pressed={parseDuration(pastDuration) === minutes} onClick={() => setPastDuration(`${minutes}m`)}>{minutes}m</button>)}
                    <button className="btn btn--quiet" type="button" onClick={() => document.getElementById("past-duration")?.focus()}>Custom</button>
                  </div>
                  <input id="past-duration" type="text" required value={pastDuration} placeholder="45m or 1h 30" onChange={(e) => setPastDuration(e.target.value)} />
                </div>
              </section>
            ) : null}
              {
                <div id="pick-subprojects" className="field capture-subprojects">
                  <label htmlFor="capture-subproject">Subproject (optional)</label>
                  <select id="capture-subproject" disabled={!project} value={selected.length === 1 ? selected[0] : ""} onChange={(event) => setSelected(event.target.value ? [Number(event.target.value)] : [])}>
                    <option value="">{selected.length > 1 ? `${selected.length} selected` : "Whole project"}</option>
                    {subs.map((sub) => <option value={sub.id} key={sub.id}>{sub.name}</option>)}
                  </select>
                  <details className="capture-multiple"><summary>Multiple subprojects & new subproject</summary>
                  <div className="field-head" id="select-all-block">
                    <span className="field-label">Subprojects</span>
                    {subs.length ? (
                      <span className="select-all-row">
                        <input
                          type="checkbox"
                          id="select-all"
                          className="select-all"
                          checked={allChecked}
                          onChange={() => setSelected(allChecked ? [] : subs.map((s) => s.id))}
                        />
                        <label htmlFor="select-all">All</label>
                      </span>
                    ) : null}
                  </div>
                  <div className="check-grid" id="subproject_options">
                    {subprojects.isPending ? (
                      <span className="subproject-empty-state">Loading...</span>
                    ) : subprojects.isError ? (
                      <span className="subproject-empty-state">Could not load subprojects.</span>
                    ) : subs.length ? (
                      subs.map((sub) => (
                        <span className="subproject-option" key={sub.id}>
                          <input
                            type="checkbox"
                            id={`subproject-option-${sub.id}`}
                            checked={selected.includes(sub.id)}
                            onChange={() =>
                              setSelected((current) =>
                                current.includes(sub.id) ? current.filter((id) => id !== sub.id) : [...current, sub.id],
                              )
                            }
                          />
                          <label htmlFor={`subproject-option-${sub.id}`}>{sub.name}</label>
                        </span>
                      ))
                    ) : (
                      <span className="subproject-empty-state">
                        Track the whole project, or add a subproject below.
                      </span>
                    )}
                  </div>
                  <div className="capture-new-sub">
                    <label className="sr-only" htmlFor="capture-new-sub">
                      New subproject name
                    </label>
                    <input
                      id="capture-new-sub"
                      className="input"
                      placeholder="New subproject (optional)"
                      value={newSub}
                      onChange={(e) => setNewSub(e.target.value)}
                    />
                    <button
                      type="button"
                      className="btn btn--quiet"
                      disabled={!project || !newSub.trim() || creatingSub}
                      onClick={async () => {
                        setCreatingSub(true);
                        try {
                          const created = await unwrap(
                            api.POST("/api/v2/projects/{project_id}/subprojects/", {
                              params: { path: { project_id: project!.id } },
                              body: { name: newSub.trim() },
                            }),
                          );
                          await client.invalidateQueries({ queryKey: keys.subprojects(project!.id) });
                          setSelected((current) => [...current, created.id]);
                          setNewSub("");
                        } catch (error) {
                          toast.error(errorMessage(error));
                        } finally {
                          setCreatingSub(false);
                        }
                      }}
                    >
                      Add
                    </button>
                  </div>
                </details></div>
              }
            <div className="form-actions">
              <span className="start-summary">{summary}</span>
              <button
                type="submit"
                id="start-timer"
                className="btn btn--primary btn--spacer"
                disabled={!project || start.isPending || savingPast}
              >
                {past ? "Save session" : "Start timer"}
              </button>
            </div>
            <details className="capture-note" open={past || undefined}><summary>Add a note (optional)</summary>
            <NoteEditor persistKey="capture" value={note} onChange={setNote} rows={3} placeholder="Optional notes to begin with..." />
            </details>
            {!past ? (
              <details className="capture-options">
                <summary>
                  Options <span className="muted">Auto-stop & reminders</span>
                </summary>
                <section className="slab slab-pad">
                  <label className="check-row">
                    <input
                      type="checkbox"
                      id="auto-stop-enabled"
                      checked={autoStop}
                      onChange={(event) => {
                        setAutoStop(event.target.checked);
                        if (!event.target.checked) {
                          setStopAmount("");
                          setPresetActive(false);
                        }
                      }}
                    />
                    <span>Stop this timer automatically</span>
                  </label>
                  <div className="preset-row" role="group" aria-label="Stop after presets">
                    {PRESETS[stopUnit].map((preset) => (
                      <button
                        key={preset.label}
                        type="button"
                        className={`timer-preset-button${autoStop && presetActive && stopAmount === String(preset.value) ? " is-active" : ""}`}
                        onClick={() => {
                          setAutoStop(true);
                          setPresetActive(true);
                          setStopAmount(String(preset.value));
                        }}
                      >
                        {preset.label}
                      </button>
                    ))}
                  </div>
                  <div className="two-up u-mt-4">
                    <div className="field">
                      <label htmlFor="stop-after-amount">Duration</label>
                      <input
                        type="number"
                        id="stop-after-amount"
                        min={1}
                        step={1}
                        inputMode="numeric"
                        placeholder="No limit"
                        disabled={!autoStop}
                        value={stopAmount}
                        onChange={(event) => {
                          setPresetActive(false);
                          setStopAmount(event.target.value);
                        }}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="stop-after-unit">Unit</label>
                      <select
                        id="stop-after-unit"
                        disabled={!autoStop}
                        value={stopUnit}
                        onChange={(event) => {
                          const unit = event.target.value as DurationUnit;
                          setStopUnit(unit);
                          if (presetActive) setStopAmount(String(PRESETS[unit][0]!.value));
                        }}
                      >
                        <option value="minutes">Minutes</option>
                        <option value="hours">Hours</option>
                      </select>
                    </div>
                  </div>
                </section>
                <section className="slab slab-pad rm-block" data-mode={mode}>
                  <fieldset className="rm-fieldset">
                    <legend className="field-label rm-legend">Reminder</legend>
                    <div className="rm-modes" role="radiogroup" aria-label="Reminder timing">
                      {MODES.map((option) => (
                        <label className="rm-mode" key={option.value}>
                          <input
                            type="radio"
                            name="reminder_mode"
                            value={option.value}
                            checked={mode === option.value}
                            onChange={() => setMode(option.value)}
                          />
                          <span className="rm-mode-face">
                            <span className="rm-mode-name">{option.label}</span>
                          </span>
                        </label>
                      ))}
                    </div>

                    {mode === "after" ? (
                      <div className="rm-panel rm-panel--after">
                        <AmountUnit
                          label="Notify me once after"
                          id="reminder"
                          amount={afterAmount}
                          unit={afterUnit}
                          onAmount={setAfterAmount}
                          onUnit={setAfterUnit}
                        />
                      </div>
                    ) : null}
                    {mode === "interval" ? (
                      <div className="rm-panel rm-panel--interval">
                        <AmountUnit
                          label="Notify me every"
                          id="interval"
                          amount={intervalAmount}
                          unit={intervalUnit}
                          onAmount={setIntervalAmount}
                          onUnit={setIntervalUnit}
                        />
                      </div>
                    ) : null}
                    {mode === "at" ? (
                      <div className="rm-panel rm-panel--at">
                        <div className="field">
                          <label htmlFor="reminder-at">Date and time</label>
                          <input
                            type="datetime-local"
                            id="reminder-at"
                            step={60}
                            value={at}
                            onChange={(event) => setAt(event.target.value)}
                            aria-describedby="reminder-timezone"
                          />
                          <LocalTimeNotice field={atTime} label="the reminder" />
                        </div>
                        <p className="rm-note" id="reminder-timezone">
                          {atTime.instant
                            ? `${`${formatDate(atTime.instant)}, ${formatTime(atTime.instant)}`}, ${zone} (profile timezone)`
                            : `Your profile timezone: ${zone}`}
                        </p>
                      </div>
                    ) : null}

                    <figure className="rm-rail" aria-labelledby="rm-rail-title">
                      <figcaption className="rm-rail-cap">
                        <span className="rm-rail-title" id="rm-rail-title">
                          When this fires
                        </span>
                        <span className="rm-rail-count mono">{plan.count}</span>
                      </figcaption>
                      <div className="rm-rail-axis" aria-hidden="true">
                        <span className="mono">now {formatTime(now)}</span>
                        <span className="mono">{plan.stopAt ? `stops ${formatTime(plan.stopAt)}` : "open-ended"}</span>
                      </div>
                      <p className="rm-plan" role="status">
                        {plan.sentence}
                      </p>
                      {plan.warning ? <p className="rm-warn">{plan.warning}</p> : null}
                    </figure>

                    <div className="field rm-message-field">
                      <label htmlFor="reminder-message">Message</label>
                      <input
                        type="text"
                        id="reminder-message"
                        maxLength={240}
                        placeholder="Time to check in"
                        aria-describedby="reminder-message-help"
                        value={message}
                        onChange={(event) => setMessage(event.target.value)}
                      />
                      <p className="rm-note" id="reminder-message-help">
                        Use <span className="mono">{"{project}"}</span> and <span className="mono">{"{elapsed}"}</span>{" "}
                        to include live timer details.
                      </p>
                    </div>
                    <label className="check-row rm-auto-stop">
                      <input
                        type="checkbox"
                        checked={notifyOnAutoStop}
                        onChange={(event) => setNotifyOnAutoStop(event.target.checked)}
                      />
                      <span>Notify me when this timer auto-stops</span>
                    </label>
                    <PushPermission />
                  </fieldset>
                </section>
              </details>
            ) : null}

          </div>
        </form>
        {!past && !project && dashboard.data?.quick_starts.length ? <div className="today-quick">
          <h3>Pick up where you left off</h3>
          {[...new Map(dashboard.data.quick_starts.map((item) => [item.project.id, item])).values()].slice(0, 4).map((item) => <button className="today-quick-pick" type="button" key={item.project.id} disabled={start.isPending} aria-label={`Start ${item.project.name}${item.subprojects.length ? ` / ${item.subprojects.map((sub) => sub.name).join(", ")}` : ""}`} onClick={() => {
            const next = projects.data?.find((p) => p.id === item.project.id);
            if (next) void submit(undefined, next, item.subprojects.map((sub) => sub.id));
          }}><Icon icon={faPlay} /><CapturePickLabel project={item.project.name} sublabel={item.subprojects.map((sub) => sub.name).join(", ")} /></button>)}
        </div> : null}
        {inline ? <AppLink className="btn btn--secondary today-log-past" href="/start_timer/?mode=past">Log past time</AppLink> : null}
    </div>
  );
}

function AmountUnit({
  label,
  id,
  amount,
  unit,
  onAmount,
  onUnit,
}: {
  label: string;
  id: string;
  amount: string;
  unit: DurationUnit;
  onAmount: (value: string) => void;
  onUnit: (value: DurationUnit) => void;
}) {
  return (
    <div className="two-up">
      <div className="field">
        <label htmlFor={`${id}-amount`}>{label}</label>
        <input
          type="number"
          id={`${id}-amount`}
          min={1}
          step={1}
          inputMode="numeric"
          value={amount}
          onChange={(event) => onAmount(event.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor={`${id}-unit`}>Unit</label>
        <select id={`${id}-unit`} value={unit} onChange={(event) => onUnit(event.target.value as DurationUnit)}>
          <option value="minutes">Minutes</option>
          <option value="hours">Hours</option>
        </select>
      </div>
    </div>
  );
}
