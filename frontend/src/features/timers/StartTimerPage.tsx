import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { faArrowLeft } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { LocalTimeNotice, useLocalTime } from "@/components/LocalTimeNotice";
import { ProjectCombobox } from "@/components/ProjectCombobox";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { useAllProjects, useSubprojects } from "@/api/meta";
import { errorMessage } from "@/api/errors";
import { bootstrap } from "@/bootstrap";
import type { Project } from "@/api/types";
import { useStartTimer } from "./api";
import { minutesOf, planReminders, type DurationUnit, type ReminderMode } from "./reminderPlan";
import { PushPermission } from "./PushPermission";

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
export default function StartTimerPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const start = useStartTimer();
  const projects = useAllProjects();

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
      setSelected(params.getAll("subproject_id").map(Number).filter((n) => Number.isInteger(n) && n > 0));
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
    [mode, stopAfter?.amount, stopAfter?.unit, afterAmount, afterUnit, intervalAmount, intervalUnit, atTime.instant, now],
  );

  const pickProject = (next: Project | null) => {
    if (next?.id !== project?.id) setSelected([]);
    setProject(next);
  };

  const subs = subprojects.data ?? [];
  const allChecked = subs.length > 0 && subs.every((s) => selected.includes(s.id));
  const stopMinutes = minutesOf(stopAfter);
  const summary = project ? `${project.name}${stopAmount && autoStop ? ` - stops after ${stopAmount} ${stopUnit}` : ""}` : "No project selected";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!project) return;
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
        subproject_ids: chosen.map((s) => s.id),
        ...(stopMinutes ? { stop_after_minutes: stopMinutes } : {}),
        ...(notifyOnAutoStop ? { notify_on_auto_stop: true } : {}),
        ...(reminder ? { reminder } : {}),
        optimistic: { projectName: project.name, subprojects: chosen.map((s) => ({ id: s.id, name: s.name })) },
      },
      {
        onSuccess: () => toast.success("Started timer"),
        onError: (error) => toast.error(`Couldn't start the timer: ${errorMessage(error)}`),
      },
    );
    /* Optimistic: the new card is already on the Timers page. */
    navigate(urls.timers());
  };

  const zone = bootstrap().profile.timezone || "UTC";

  return (
    <>
      <div className="desk-head">
        <div>
          <h1 className="page-title">New timer</h1>
        </div>
      </div>
      <form className="fields desk" onSubmit={submit}>
        <div className="desk-main">
          <section className="slab slab-pad">
            <div className="field" id="search-projects">
              <label htmlFor="project-search">Project</label>
              <ProjectCombobox id="project-search" value={project} onChange={pickProject} autoFocus={!params.get("project_id")} />
            </div>
            {project ? (
              <section id="pick-subprojects" className="field">
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
                            setSelected((current) => (current.includes(sub.id) ? current.filter((id) => id !== sub.id) : [...current, sub.id]))
                          }
                        />
                        <label htmlFor={`subproject-option-${sub.id}`}>{sub.name}</label>
                      </span>
                    ))
                  ) : (
                    <span className="subproject-empty-state">No subprojects found.</span>
                  )}
                </div>
              </section>
            ) : null}
          </section>

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
                  disabled={!autoStop}
                  onClick={() => {
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
        </div>

        <div className="desk-side">
          <section className="slab slab-pad rm-block" data-mode={mode}>
            <fieldset className="rm-fieldset">
              <legend className="field-label rm-legend">Reminder</legend>
              <div className="rm-modes" role="radiogroup" aria-label="Reminder timing">
                {MODES.map((option) => (
                  <label className="rm-mode" key={option.value}>
                    <input type="radio" name="reminder_mode" value={option.value} checked={mode === option.value} onChange={() => setMode(option.value)} />
                    <span className="rm-mode-face">
                      <span className="rm-mode-name">{option.label}</span>
                    </span>
                  </label>
                ))}
              </div>

              {mode === "after" ? (
                <div className="rm-panel rm-panel--after">
                  <AmountUnit label="Notify me once after" id="reminder" amount={afterAmount} unit={afterUnit} onAmount={setAfterAmount} onUnit={setAfterUnit} />
                </div>
              ) : null}
              {mode === "interval" ? (
                <div className="rm-panel rm-panel--interval">
                  <AmountUnit label="Notify me every" id="interval" amount={intervalAmount} unit={intervalUnit} onAmount={setIntervalAmount} onUnit={setIntervalUnit} />
                </div>
              ) : null}
              {mode === "at" ? (
                <div className="rm-panel rm-panel--at">
                  <div className="field">
                    <label htmlFor="reminder-at">Date and time</label>
                    <input type="datetime-local" id="reminder-at" step={60} value={at} onChange={(event) => setAt(event.target.value)} aria-describedby="reminder-timezone" />
                    <LocalTimeNotice field={atTime} label="the reminder" />
                  </div>
                  <p className="rm-note" id="reminder-timezone">
                    {atTime.instant ? `${new Date(atTime.instant).toLocaleString([], { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })}, ${zone} (profile timezone)` : `Your profile timezone: ${zone}`}
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
                <div className="rm-rail-track">
                  <span className="rm-rail-now" aria-hidden="true" />
                  {plan.stopAt ? <span className="rm-rail-stop" aria-hidden="true" /> : null}
                  {plan.ticks.map((tick) => (
                    <span
                      key={tick.at.getTime()}
                      className={`rm-tick${tick.beyondStop ? " is-void" : tick.next ? " is-next" : ""}`}
                      style={{ "--x": `${tick.x}%` } as CSSProperties}
                    >
                      <span className="sr-only">
                        Reminder at {tick.at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                        {tick.beyondStop ? "; after the timer stops" : ""}
                      </span>
                    </span>
                  ))}
                </div>
                <div className="rm-rail-axis" aria-hidden="true">
                  <span className="mono">now {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                  <span className="mono">
                    {plan.stopAt ? `stops ${plan.stopAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "open-ended"}
                  </span>
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
                  Use <span className="mono">{"{project}"}</span> and <span className="mono">{"{elapsed}"}</span> to include live timer details.
                </p>
              </div>
              <label className="check-row rm-auto-stop">
                <input type="checkbox" checked={notifyOnAutoStop} onChange={(event) => setNotifyOnAutoStop(event.target.checked)} />
                <span>Notify me when this timer auto-stops</span>
              </label>
              <PushPermission />
            </fieldset>
          </section>
          <div className="form-actions">
            <AppLink className="btn btn--ghost" href={urls.timers()}>
              <Icon icon={faArrowLeft} /> Back
            </AppLink>
            <span className="start-summary">{summary}</span>
            <button type="submit" id="start-timer" className="btn btn--primary btn--lg btn--spacer" disabled={!project || start.isPending}>
              <span className="hourglass-icon" aria-hidden="true" /> Start timer
            </button>
          </div>
        </div>
      </form>
    </>
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
        <input type="number" id={`${id}-amount`} min={1} step={1} inputMode="numeric" value={amount} onChange={(event) => onAmount(event.target.value)} />
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
