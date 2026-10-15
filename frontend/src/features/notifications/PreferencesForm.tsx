import { useState, type FormEvent } from "react";
import { useToast } from "@/app/toasts";
import { FieldErrors, FormLevelErrors } from "@/features/contexts-tags/ui";
import { NO_ERRORS, parseFormErrors, type FormErrors } from "@/features/contexts-tags/formErrors";
import { useSavePreferences, type NotificationPreference } from "./api";
import { clockText } from "./dates";

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/* "Send me": the three delivery categories and their local slots. Mounted
   once the preferences have loaded, so the fields start from them. */
export function PreferencesForm({ preference }: { preference: NotificationPreference }) {
  const toast = useToast();
  const save = useSavePreferences();
  const [reminders, setReminders] = useState(preference.scheduled_reminders_enabled);
  const [checks, setChecks] = useState(preference.commitment_checks_enabled);
  const [review, setReview] = useState(preference.weekly_review_enabled);
  const [checkTime, setCheckTime] = useState(clockText(preference.commitment_check_time));
  const [weekday, setWeekday] = useState(String(preference.weekly_review_weekday));
  const [reviewTime, setReviewTime] = useState(clockText(preference.weekly_review_time));
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors(NO_ERRORS);
    save.mutate(
      {
        scheduled_reminders_enabled: reminders,
        commitment_checks_enabled: checks,
        weekly_review_enabled: review,
        commitment_check_time: checkTime,
        weekly_review_weekday: Number(weekday),
        weekly_review_time: reviewTime,
      },
      {
        onSuccess: () => toast.success("Notification settings saved."),
        onError: (error) => setErrors(parseFormErrors(error)),
      },
    );
  };

  return (
    <form className="slab slab-pad fields" aria-labelledby="categories-title" onSubmit={submit} noValidate>
      <div className="nx-section-head">
        <h2 className="nx-title" id="categories-title">
          Send me
        </h2>
      </div>
      <FormLevelErrors errors={errors.general} />
      <label className="nx-switch">
        <span>
          <strong>Scheduled reminders</strong>
        </span>
        <input type="checkbox" checked={reminders} onChange={(event) => setReminders(event.target.checked)} />
      </label>
      <label className="nx-switch">
        <span>
          <strong>Commitment checks</strong>
          <small>When a period is about to close short of its target</small>
        </span>
        <input type="checkbox" checked={checks} onChange={(event) => setChecks(event.target.checked)} />
      </label>
      <label className="nx-switch">
        <span>
          <strong>Weekly review</strong>
          <small>A summary of last week</small>
        </span>
        <input type="checkbox" checked={review} onChange={(event) => setReview(event.target.checked)} />
      </label>
      <div className="nx-schedule-fields">
        <div className="field">
          <label htmlFor="id_commitment_check_time">Commitment check time</label>
          <input
            id="id_commitment_check_time"
            type="time"
            step={60}
            value={checkTime}
            aria-invalid={!!errors.fields.commitment_check_time}
            onChange={(event) => setCheckTime(event.target.value)}
          />
          <small className="muted">Choose a local time from 18:00 through 23:59.</small>
          <FieldErrors errors={errors.fields.commitment_check_time} />
        </div>
        <div className="field">
          <label htmlFor="id_weekly_review_weekday">Weekly review day</label>
          <select id="id_weekly_review_weekday" value={weekday} onChange={(event) => setWeekday(event.target.value)}>
            {WEEKDAYS.map((name, index) => (
              <option key={name} value={index}>
                {name}
              </option>
            ))}
          </select>
          <FieldErrors errors={errors.fields.weekly_review_weekday} />
        </div>
        <div className="field">
          <label htmlFor="id_weekly_review_time">Weekly review time</label>
          <input
            id="id_weekly_review_time"
            type="time"
            step={60}
            value={reviewTime}
            aria-invalid={!!errors.fields.weekly_review_time}
            onChange={(event) => setReviewTime(event.target.value)}
          />
          <small className="muted">This uses your profile timezone.</small>
          <FieldErrors errors={errors.fields.weekly_review_time} />
        </div>
      </div>
      <div className="form-actions">
        <button className="btn btn--primary" type="submit" disabled={save.isPending}>
          Save settings
        </button>
      </div>
    </form>
  );
}
