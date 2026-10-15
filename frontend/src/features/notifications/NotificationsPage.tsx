import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { bootstrap } from "@/bootstrap";
import { Dialog, ConfirmDialog } from "@/components/Sheet";
import { ErrorState, Skeleton } from "@/components/states";
import {
  useCancelSchedule,
  useCreateSchedule,
  usePreferences,
  useSchedules,
  useSnoozeSchedule,
  type NotificationPreference,
  type SnoozeChoice,
} from "./api";
import { BrowserPush } from "./BrowserPush";
import { clockText, formatInstant } from "./dates";
import { PreferencesForm, WEEKDAYS } from "./PreferencesForm";
import { ScheduleEditor } from "./ScheduleEditor";
import { CADENCE_LABEL, toPayload, formFromSchedule, type Schedule } from "./scheduleForm";

/* Notifications (templates/core/notifications.html): what Autumn will send,
   the planned reminders, and delivery to this browser. */
export default function NotificationsPage() {
  const schedules = useSchedules();
  const preferences = usePreferences();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const editId = Number(params.get("edit")) || null;
  const editing = editId ? schedules.data?.schedules.find((item) => item.id === editId) : undefined;
  const [formKey, setFormKey] = useState(0);
  const [snoozing, setSnoozing] = useState<Schedule | null>(null);
  const [cancelling, setCancelling] = useState<Schedule | null>(null);
  const editorRef = useRef<HTMLDivElement>(null);
  const toast = useToast();

  /* An ?edit= for a reminder that no longer exists (cancelled elsewhere). */
  const missing = !!editId && schedules.isSuccess && !schedules.isFetching && !editing;
  useEffect(() => {
    if (!missing) return;
    toast.info("That reminder no longer exists.");
    navigate(urls.notifications(), { replace: true });
  }, [missing, navigate, toast]);

  /* ?snooze= / ?cancel= open that dialog: a reminder notification's Snooze
     action lands here (via /notifications/schedules/<id>/snooze/). */
  const actionParam = params.has("snooze") ? "snooze" : params.has("cancel") ? "cancel" : null;
  const actionId = actionParam ? Number(params.get(actionParam)) || null : null;
  const settled = schedules.isSuccess && !schedules.isFetching;
  useEffect(() => {
    if (!actionParam || !settled) return;
    const target = schedules.data?.schedules.find((item) => item.id === actionId);
    if (!target) toast.info("That reminder no longer exists.");
    else if (actionParam === "snooze") setSnoozing(target);
    else setCancelling(target);
    navigate(urls.notifications(), { replace: true });
  }, [actionParam, actionId, settled, schedules.data, navigate, toast]);

  useEffect(() => {
    if (editId) editorRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [editId]);

  const timezone = bootstrap().profile.timezone;

  return (
    <>
      <div className="desk-head nx-page-head">
        <div>
          <h1 className="page-title">Notifications</h1>
        </div>
      </div>

      <section className="slab slab-pad nx-rail-slab" aria-labelledby="next-week-title">
        <div className="nx-section-head">
          <h2 className="nx-title" id="next-week-title">
            Next 7 days
          </h2>
        </div>
        <Rail schedules={schedules} preferences={preferences} timezone={timezone} />
      </section>

      <div className="nx-columns">
        <section className="slab nx-active-schedules" aria-labelledby="active-schedules-title">
          <div className="slab-pad nx-section-head">
            <h2 className="nx-title" id="active-schedules-title">
              Scheduled reminders
            </h2>
          </div>
          {schedules.isPending ? (
            <div className="slab-pad">
              <Skeleton lines={3} />
            </div>
          ) : schedules.isError ? (
            <div className="slab-pad">
              <ErrorState error={schedules.error} onRetry={() => void schedules.refetch()} />
            </div>
          ) : schedules.data.schedules.length ? (
            <div className="band-list">
              {schedules.data.schedules.map((schedule) => (
                <ScheduleRow
                  key={schedule.id}
                  schedule={schedule}
                  timezone={timezone}
                  editing={schedule.id === editing?.id}
                  onSnooze={() => setSnoozing(schedule)}
                  onCancel={() => setCancelling(schedule)}
                />
              ))}
            </div>
          ) : (
            <p className="empty slab-pad">No scheduled reminders.</p>
          )}
        </section>

        <div ref={editorRef}>
          {editId && !editing ? (
            <section className="slab slab-pad nx-schedule-editor" aria-label="Edit reminder">
              {schedules.isError ? <ErrorState error={schedules.error} onRetry={() => void schedules.refetch()} /> : <Skeleton lines={4} />}
            </section>
          ) : (
            <ScheduleEditor
              key={editing ? `edit-${editing.id}` : `new-${formKey}`}
              schedule={editing}
              onSaved={() => {
                if (editing) navigate(urls.notifications());
                else setFormKey((key) => key + 1);
              }}
            />
          )}
        </div>
      </div>

      <div className="nx-columns">
        <section className="slab slab-pad" aria-labelledby="delivery-title">
          <div className="nx-section-head">
            <h2 className="nx-title" id="delivery-title">
              This browser
            </h2>
          </div>
          <BrowserPush />
        </section>

        {preferences.isPending ? (
          <section className="slab slab-pad" aria-label="Send me">
            <Skeleton lines={5} />
          </section>
        ) : preferences.isError ? (
          <section className="slab slab-pad" aria-label="Send me">
            <ErrorState error={preferences.error} onRetry={() => void preferences.refetch()} />
          </section>
        ) : (
          <PreferencesForm key={preferences.data.version} preference={preferences.data} />
        )}
      </div>

      <p className="nx-footer-link">
        <AppLink href={urls.weeklyReview()}>Open your weekly review</AppLink> <span aria-hidden="true">→</span>
      </p>

      <SnoozeDialog schedule={snoozing} onClose={() => setSnoozing(null)} />
      <CancelDialog schedule={cancelling} onClose={() => setCancelling(null)} />
    </>
  );
}

function TargetKind({ schedule }: { schedule: Schedule }) {
  return schedule.target === "context" || schedule.target === "tag" ? (
    <span className="muted nx-target-kind">{schedule.target}</span>
  ) : null;
}

/* The three lanes: planned reminders, the daily commitment check, the weekly review. */
function Rail({
  schedules,
  preferences,
  timezone,
}: {
  schedules: ReturnType<typeof useSchedules>;
  preferences: ReturnType<typeof usePreferences>;
  timezone: string;
}) {
  const upcoming = schedules.data?.upcoming ?? [];
  const preference: NotificationPreference | undefined = preferences.data;
  return (
    <div className="nx-rail" role="list" aria-label="Notification lanes for the next seven days">
      <section className="nx-lane nx-lane--planned" role="listitem" aria-labelledby="lane-planned">
        <div className="nx-lane-label">
          <span className="nx-lane-mark" aria-hidden="true">
            ↳
          </span>
          <h3 id="lane-planned">Planned reminders</h3>
        </div>
        <div className="nx-lane-track">
          {schedules.isPending ? (
            <p className="nx-lane-empty">Loading…</p>
          ) : schedules.isError ? (
            <p className="nx-lane-empty">Could not load reminders.</p>
          ) : upcoming.length ? (
            upcoming.map((schedule) => (
              <AppLink key={schedule.id} className="nx-event" href={`${urls.notifications()}?edit=${schedule.id}`}>
                <time className="mono" dateTime={schedule.next_fire_at ?? undefined}>
                  {formatInstant(schedule.next_fire_at, schedule.timezone || timezone)}
                </time>
                <strong>{schedule.target_resource.name}</strong>
                <TargetKind schedule={schedule} />
                {schedule.subprojects.map((sub) => (
                  <span key={sub.id}>{sub.name}</span>
                ))}
              </AppLink>
            ))
          ) : (
            <p className="nx-lane-empty">Nothing scheduled for the next seven days.</p>
          )}
        </div>
      </section>
      <section className="nx-lane nx-lane--check" role="listitem" aria-labelledby="lane-check">
        <div className="nx-lane-label">
          <span className="nx-lane-mark" aria-hidden="true">
            □
          </span>
          <h3 id="lane-check">Commitment checks</h3>
        </div>
        <div className="nx-lane-track">
          {!preference ? (
            <p className="nx-lane-empty">{preferences.isError ? "Unavailable" : "Loading…"}</p>
          ) : preference.commitment_checks_enabled ? (
            <p className="nx-event nx-event--quiet">
              <span className="mono">{clockText(preference.commitment_check_time)}</span>
              <strong>Commitment check</strong>
            </p>
          ) : (
            <p className="nx-lane-empty">Off</p>
          )}
        </div>
      </section>
      <section className="nx-lane nx-lane--review" role="listitem" aria-labelledby="lane-review">
        <div className="nx-lane-label">
          <span className="nx-lane-mark" aria-hidden="true">
            ◷
          </span>
          <h3 id="lane-review">Weekly review</h3>
        </div>
        <div className="nx-lane-track">
          {!preference ? (
            <p className="nx-lane-empty">{preferences.isError ? "Unavailable" : "Loading…"}</p>
          ) : preference.weekly_review_enabled ? (
            <p className="nx-event nx-event--quiet">
              <span className="mono">{clockText(preference.weekly_review_time)}</span>
              <strong>Every {WEEKDAYS[preference.weekly_review_weekday] ?? "Monday"}</strong>
            </p>
          ) : (
            <p className="nx-lane-empty">Off</p>
          )}
        </div>
      </section>
    </div>
  );
}

function ScheduleRow({
  schedule,
  timezone,
  editing,
  onSnooze,
  onCancel,
}: {
  schedule: Schedule;
  timezone: string;
  editing: boolean;
  onSnooze: () => void;
  onCancel: () => void;
}) {
  return (
    <article className="band nx-schedule-row" aria-current={editing ? "true" : undefined}>
      <div className="nx-schedule-copy">
        <div className="nx-schedule-name">
          <strong>{schedule.target_resource.name}</strong>
          <TargetKind schedule={schedule} />
          {schedule.subprojects.map((sub) => (
            <span key={sub.id} className="text-blue">
              {sub.name}
            </span>
          ))}
        </div>
        <p>{schedule.message || "A focused session"}</p>
        <small className="muted">
          <span className="mono">{clockText(schedule.local_time)}</span> · {CADENCE_LABEL[schedule.cadence] ?? schedule.cadence} · next{" "}
          <span className="mono">{formatInstant(schedule.next_fire_at, schedule.timezone || timezone)}</span>
          {schedule.snoozed_until ? <> · snoozed</> : null}
        </small>
      </div>
      <div className="nx-row-actions">
        <AppLink className="btn btn--quiet" href={`${urls.notifications()}?edit=${schedule.id}`}>
          Edit
        </AppLink>
        <button type="button" className="btn btn--quiet" onClick={onSnooze}>
          Snooze
        </button>
        <button type="button" className="btn btn--quiet btn-icon--danger" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </article>
  );
}

const SNOOZE_OPTIONS: { value: SnoozeChoice; label: string; hint: string }[] = [
  { value: "15m", label: "15 minutes", hint: "Just a little later" },
  { value: "1h", label: "1 hour", hint: "After this block" },
  { value: "tomorrow", label: "Tomorrow", hint: "At the schedule’s local time" },
];

function ScheduleSummary({ schedule }: { schedule: Schedule }) {
  return (
    <p className="nx-lede">
      <strong>{schedule.target_resource.name}</strong>
      {schedule.target !== "project" ? <span className="muted nx-target-kind"> {schedule.target}</span> : null}
      {schedule.subprojects.map((sub) => ` · ${sub.name}`).join("")} · <span className="mono">{clockText(schedule.local_time)}</span>
    </p>
  );
}

function SnoozeDialog({ schedule, onClose }: { schedule: Schedule | null; onClose: () => void }) {
  const toast = useToast();
  const snooze = useSnoozeSchedule();
  const [choice, setChoice] = useState<SnoozeChoice>("15m");
  const [error, setError] = useState("");

  useEffect(() => {
    setChoice("15m");
    setError("");
  }, [schedule?.id]);

  const submit = () => {
    if (!schedule) return;
    snooze.mutate(
      { id: schedule.id, choice, version: schedule.version },
      {
        onSuccess: (updated) => {
          toast.success(`Reminder snoozed to ${formatInstant(updated.snoozed_until ?? updated.next_fire_at, updated.timezone || bootstrap().profile.timezone)}.`);
          onClose();
        },
        onError: (failure) => setError(failure instanceof Error ? failure.message : "Could not snooze this reminder."),
      },
    );
  };

  return (
    <Dialog open={!!schedule} onClose={onClose} title="Snooze this reminder">
      {schedule ? (
        <>
          <ScheduleSummary schedule={schedule} />
          <p className="muted">Choose one new occurrence. A recurring reminder returns to its regular local cadence after it fires.</p>
          <fieldset className="nx-snooze-options">
            <legend className="sr-only">Snooze duration</legend>
            {SNOOZE_OPTIONS.map((option) => (
              <label key={option.value}>
                <input type="radio" name="choice" value={option.value} checked={choice === option.value} onChange={() => setChoice(option.value)} />
                <span>
                  <strong>{option.label}</strong>
                  <small>{option.hint}</small>
                </span>
              </label>
            ))}
          </fieldset>
          {error ? (
            <ul className="errorlist nonfield" role="alert">
              <li>{error}</li>
            </ul>
          ) : null}
          <div className="dialog-actions">
            <button type="button" className="btn btn--ghost" onClick={onClose}>
              Keep time
            </button>
            <button type="button" className="btn btn--primary" disabled={snooze.isPending} onClick={submit}>
              Snooze reminder
            </button>
          </div>
        </>
      ) : null}
    </Dialog>
  );
}

function CancelDialog({ schedule, onClose }: { schedule: Schedule | null; onClose: () => void }) {
  const toast = useToast();
  const cancel = useCancelSchedule();
  const recreate = useCreateSchedule();

  const confirm = () => {
    if (!schedule) return;
    const gone = schedule;
    cancel.mutate(
      { id: gone.id, version: gone.version },
      {
        onSuccess: () => {
          onClose();
          toast.success("Schedule cancelled.", {
            action: {
              label: "Undo",
              run: () =>
                recreate.mutate(toPayload(formFromSchedule(gone)), {
                  onSuccess: () => toast.success("Schedule restored."),
                  onError: () => toast.error("Could not restore that schedule. Add it again from the form."),
                }),
            },
          });
        },
        onError: (failure) => {
          onClose();
          toast.error(failure instanceof Error ? failure.message : "Could not cancel this schedule.");
        },
      },
    );
  };

  return (
    <ConfirmDialog
      open={!!schedule}
      title="Cancel this schedule?"
      body={
        schedule ? (
          <>
            <ScheduleSummary schedule={schedule} />
            <p>Autumn will stop future occurrences of this reminder. Already delivered notifications are not changed.</p>
          </>
        ) : null
      }
      confirmLabel="Cancel schedule"
      danger
      busy={cancel.isPending}
      onConfirm={confirm}
      onClose={onClose}
    />
  );
}
