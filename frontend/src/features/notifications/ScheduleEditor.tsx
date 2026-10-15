import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { useAllProjects, useContexts, useSubprojects, useTags } from "@/api/meta";
import { bootstrap } from "@/bootstrap";
import { FieldErrors, FormLevelErrors } from "@/features/contexts-tags/ui";
import { NO_ERRORS, parseFormErrors, type FormErrors } from "@/features/contexts-tags/formErrors";
import { useCreateSchedule, useUpdateSchedule } from "./api";
import { defaultSlot } from "./dates";
import {
  CADENCE_OPTIONS,
  TARGET_OPTIONS,
  emptyForm,
  formFromSchedule,
  keepSubprojects,
  toPayload,
  toggleId,
  validateForm,
  type Cadence,
  type Schedule,
  type ScheduleForm,
  type Target,
} from "./scheduleForm";

/* New or edit reminder (the "schedule editor" slab). Mounted with a key per
   schedule, so each starts from its own values. */
export function ScheduleEditor({ schedule, onSaved }: { schedule?: Schedule; onSaved: () => void }) {
  const toast = useToast();
  const timezone = bootstrap().profile.timezone;
  const [form, setForm] = useState<ScheduleForm>(() => (schedule ? formFromSchedule(schedule) : emptyForm(defaultSlot(timezone))));
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);
  const create = useCreateSchedule();
  const update = useUpdateSchedule(schedule?.id ?? 0);
  const busy = create.isPending || update.isPending;

  const projects = useAllProjects();
  const contexts = useContexts();
  const tags = useTags();
  const projectId = form.target === "project" && form.project ? Number(form.project) : null;
  const subprojects = useSubprojects(projectId);

  const openProjects = useMemo(
    () =>
      (projects.data ?? [])
        .filter((project) => project.status !== "archived" && project.status !== "complete")
        .sort((a, b) => a.name.localeCompare(b.name)),
    [projects.data],
  );

  /* A schedule being edited keeps its project in the list even if it has
     since been completed, so the select never shows a blank. */
  const projectOptions = useMemo(() => {
    const current = schedule?.target === "project" ? schedule.target_resource : null;
    if (current && !openProjects.some((project) => project.id === current.id)) {
      return [...openProjects, { id: current.id, name: current.name }];
    }
    return openProjects;
  }, [openProjects, schedule]);

  /* On edit, focus the first field so keyboard users land in the editor. */
  const first = useRef<HTMLSelectElement>(null);
  useEffect(() => {
    if (schedule) first.current?.focus();
  }, [schedule]);

  const set = <K extends keyof ScheduleForm>(key: K, value: ScheduleForm[K]) => setForm((current) => ({ ...current, [key]: value }));

  const pickProject = (value: string) =>
    setForm((current) => ({ ...current, project: value, subprojects: [] }));

  const available = subprojects.data ?? [];
  /* Subprojects loaded for the project: forget any that do not belong. */
  useEffect(() => {
    if (!projectId || subprojects.isPending) return;
    setForm((current) => {
      const kept = keepSubprojects(current.subprojects, available);
      return kept.length === current.subprojects.length ? current : { ...current, subprojects: kept };
    });
  }, [projectId, subprojects.isPending, available]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const problems = validateForm(form);
    if (Object.keys(problems).length) {
      setErrors({ fields: Object.fromEntries(Object.entries(problems).map(([key, text]) => [key, [text]])), general: [] });
      return;
    }
    setErrors(NO_ERRORS);
    const callbacks = {
      onError: (error: unknown) => setErrors(parseFormErrors(error)),
    };
    if (schedule) {
      update.mutate(toPayload(form, schedule.version), {
        ...callbacks,
        onSuccess: () => {
          toast.success("Schedule updated.");
          onSaved();
        },
      });
    } else {
      create.mutate(toPayload(form), {
        ...callbacks,
        onSuccess: () => {
          toast.success("Schedule added.");
          onSaved();
        },
      });
    }
  };

  const fieldError = (name: string) => errors.fields[name];

  return (
    <section className="slab slab-pad nx-schedule-editor" aria-labelledby="schedule-title" id="schedule-editor">
      <div className="nx-section-head">
        <h2 className="nx-title" id="schedule-title">
          {schedule ? "Edit reminder" : "New reminder"}
        </h2>
      </div>
      <form className="fields" onSubmit={submit} noValidate>
        <FormLevelErrors errors={errors.general} />
        <div className="nx-form-grid">
          <div className="field">
            <label htmlFor="id_target">Remind me about</label>
            <select id="id_target" ref={first} value={form.target} onChange={(event) => set("target", event.target.value as Target)}>
              {TARGET_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <FieldErrors errors={fieldError("target")} />
          </div>

          {form.target === "project" ? (
            <div className="field">
              <label htmlFor="id_project">Project</label>
              <select id="id_project" value={form.project} aria-invalid={!!fieldError("project")} onChange={(event) => pickProject(event.target.value)}>
                <option value="">---------</option>
                {projectOptions.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
              <FieldErrors errors={fieldError("project")} />
            </div>
          ) : null}
          {form.target === "context" ? (
            <div className="field">
              <label htmlFor="id_context">Context</label>
              <select id="id_context" value={form.context} aria-invalid={!!fieldError("context")} onChange={(event) => set("context", event.target.value)}>
                <option value="">---------</option>
                {(contexts.data ?? []).map((context) => (
                  <option key={context.id} value={context.id}>
                    {context.name}
                  </option>
                ))}
              </select>
              <FieldErrors errors={fieldError("context")} />
            </div>
          ) : null}
          {form.target === "tag" ? (
            <div className="field">
              <label htmlFor="id_tag">Tag</label>
              <select id="id_tag" value={form.tag} aria-invalid={!!fieldError("tag")} onChange={(event) => set("tag", event.target.value)}>
                <option value="">---------</option>
                {(tags.data ?? []).map((tag) => (
                  <option key={tag.id} value={tag.id}>
                    {tag.name}
                  </option>
                ))}
              </select>
              <FieldErrors errors={fieldError("tag")} />
            </div>
          ) : null}

          {form.target === "project" && available.length > 0 ? (
            <div className="field nx-subprojects-field">
              <label id="id_subprojects_label">Subprojects (optional)</label>
              <div className="nx-subproject-options" role="group" aria-labelledby="id_subprojects_label">
                {available.map((sub) => (
                  <div key={sub.id}>
                    <label>
                      <input
                        type="checkbox"
                        checked={form.subprojects.includes(sub.id)}
                        onChange={() => set("subprojects", toggleId(form.subprojects, sub.id))}
                      />{" "}
                      {sub.name}
                    </label>
                  </div>
                ))}
              </div>
              <FieldErrors errors={fieldError("subprojects")} />
            </div>
          ) : null}

          <div className="field">
            <label htmlFor="id_local_date">Date</label>
            <input
              id="id_local_date"
              type="date"
              value={form.date}
              aria-invalid={!!fieldError("local_date")}
              onChange={(event) => set("date", event.target.value)}
            />
            <FieldErrors errors={fieldError("local_date")} />
          </div>
          <div className="field">
            <label htmlFor="id_local_time">Time</label>
            <input
              id="id_local_time"
              type="time"
              step={60}
              value={form.time}
              aria-invalid={!!fieldError("local_time")}
              onChange={(event) => set("time", event.target.value)}
            />
            <FieldErrors errors={fieldError("local_time")} />
          </div>
          <div className="field">
            <label htmlFor="id_cadence">Repeat</label>
            <select id="id_cadence" value={form.cadence} onChange={(event) => set("cadence", event.target.value as Cadence)}>
              {CADENCE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <FieldErrors errors={fieldError("cadence")} />
          </div>
          <div className="field nx-message-field">
            <label htmlFor="id_message">Message</label>
            <input
              id="id_message"
              type="text"
              maxLength={240}
              placeholder="What should Autumn remind you about?"
              value={form.message}
              aria-invalid={!!fieldError("message")}
              onChange={(event) => set("message", event.target.value)}
            />
            <FieldErrors errors={fieldError("message")} />
          </div>
        </div>
        <p className="muted nx-timezone-note">Your profile timezone: {timezone}</p>
        <div className="form-actions">
          {schedule ? (
            <AppLink className="btn btn--ghost" href={urls.notifications()}>
              Cancel edit
            </AppLink>
          ) : null}
          <button className="btn btn--primary" type="submit" disabled={busy}>
            {schedule ? "Save reminder" : "Add reminder"}
          </button>
        </div>
      </form>
    </section>
  );
}
