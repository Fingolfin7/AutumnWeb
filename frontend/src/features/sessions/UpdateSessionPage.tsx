import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";
import { Navigate, useNavigate, useParams } from "react-router";
import { faArrowLeft, faCheckCircle, faExclamationTriangle } from "@fortawesome/free-solid-svg-icons";
import { AllocationEditor } from "@/components/AllocationEditor";
import { Icon } from "@/components/Icon";
import { LocalTimeNotice, useLocalTime } from "@/components/LocalTimeNotice";
import { ProjectCombobox } from "@/components/ProjectCombobox";
import { NoteEditor } from "@/components/NoteEditor";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { useAllProjects, useSubprojects } from "@/api/meta";
import { ApiError, errorMessage } from "@/api/errors";
import type { Project, SessionPatch } from "@/api/types";
import { sameAllocations, type AllocationItem, type AllocationWrite } from "@/lib/allocation";
import { toDateTimeLocal } from "@/lib/format";
import { parseSessionParam, useSession, useUpdateSession, type SessionRow } from "./api";

/* /update_session/<id or uuid>/ (update_session.html). Three slabs' worth of
   fields in two: what it was (project), when it ran, the note, then how the
   time splits across subprojects. Only fields the user changed are sent, so
   an untouched start/end keeps its sub-second precision, and the PATCH
   carries the version the form was opened on (If-Match). */
export default function UpdateSessionPage() {
  const { sessionId } = useParams();
  const parsed = parseSessionParam(sessionId);
  const query = useSession(sessionId);

  if (parsed.kind === "invalid") return <Missing />;
  if (query.isPending) return <Skeleton lines={6} height="2rem" />;
  if (query.isError) {
    return query.error instanceof ApiError && query.error.status === 404 ? (
      <Missing />
    ) : (
      <ErrorState error={query.error} onRetry={() => void query.refetch()} />
    );
  }
  /* A running timer is edited through its stop page, which also ends it. */
  if (query.data.active) return <Navigate to={urls.stopTimer(query.data.id)} replace />;
  return <SessionForm session={query.data} />;
}

function Missing() {
  return (
    <>
      <div className="desk-head">
        <h1 className="page-title">Session not found</h1>
      </div>
      <Empty>That session no longer exists. It may have been deleted.</Empty>
      <div className="form-actions">
        <AppLink className="btn btn--ghost" href={urls.sessions()}>
          <Icon icon={faArrowLeft} /> Back
        </AppLink>
      </div>
    </>
  );
}

interface FormState {
  projectId: number | null;
  projectText: string;
  start: string;
  end: string;
  note: string;
  subprojectIds: number[];
}

function initialState(session: SessionRow): FormState {
  return {
    projectId: session.project.id,
    projectText: session.project.name,
    start: toDateTimeLocal(session.start, true),
    end: toDateTimeLocal(session.end, true),
    note: session.note ?? "",
    subprojectIds: session.subproject_allocations.map((a) => a.subproject_id).sort((a, b) => a - b),
  };
}

function SessionForm({ session }: { session: SessionRow }) {
  const navigate = useNavigate();
  const toast = useToast();
  const update = useUpdateSession();
  const projects = useAllProjects();

  /* The session as the form was opened (or last saved/reloaded). */
  const [baseline, setBaseline] = useState(session);
  const [form, setForm] = useState(() => initialState(session));
  const [allocations, setAllocations] = useState<AllocationWrite[] | null>(null);
  const [conflict, setConflict] = useState<SessionRow | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [banner, setBanner] = useState<string | null>(null);
  const bannerRef = useRef<HTMLDivElement>(null);
  const startId = useId();
  const endId = useId();
  /* A wall time can mean two instants (clocks went back) or none (they went
     forward); an untouched field keeps the occurrence it was saved with. */
  const startTime = useLocalTime(form.start, baseline.start);
  const endTime = useLocalTime(form.end, baseline.end);

  const subprojects = useSubprojects(form.projectId);
  const baselineIds = useMemo(() => initialState(baseline).subprojectIds, [baseline]);
  const changedElsewhere = session.version !== baseline.version;

  /* The save button is far below the banners: bring them into view. */
  useEffect(() => {
    if (conflict || banner) bannerRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [conflict, banner]);

  const reset = (from: SessionRow) => {
    setBaseline(from);
    setForm(initialState(from));
    setConflict(null);
    setFieldErrors({});
    setBanner(null);
  };

  const setProject = (project: Project | null, text: string) => {
    setForm((current) => {
      const id = project?.id ?? null;
      if (id === current.projectId) return { ...current, projectText: text };
      /* A different project has different subprojects: nothing carried over,
         except coming back to the project the session started on. */
      return { ...current, projectText: text, projectId: id, subprojectIds: id === baseline.project.id ? baselineIds : [] };
    });
  };

  const toggleSubproject = (id: number, checked: boolean) =>
    setForm((current) => ({
      ...current,
      subprojectIds: (checked ? [...current.subprojectIds, id] : current.subprojectIds.filter((value) => value !== id)).sort((a, b) => a - b),
    }));

  const items: AllocationItem[] = useMemo(() => {
    const stored = new Map(baseline.subproject_allocations.map((a) => [a.subproject_id, a.allocation_bp]));
    const byId = new Map((subprojects.data ?? []).map((sub) => [sub.id, sub.name]));
    return form.subprojectIds.map((id) => ({
      id,
      name: byId.get(id) ?? baseline.subproject_allocations.find((a) => a.subproject_id === id)?.name ?? `#${id}`,
      bp: form.projectId === baseline.project.id ? stored.get(id) ?? 0 : 0,
    }));
  }, [form.subprojectIds, form.projectId, subprojects.data, baseline]);

  /* Build the PATCH from what differs from the baseline. */
  const buildPatch = (): { body: SessionPatch } | { errors: Record<string, string[]> } => {
    const errors: Record<string, string[]> = {};
    const body: SessionPatch = {};
    const initial = initialState(baseline);

    if (form.projectId === null) errors.project = ["Choose one of your projects."];
    else if (form.projectId !== baseline.project.id) body.project_id = form.projectId;

    const start = startTime.instant;
    const end = endTime.instant;
    /* A skipped time already says so under its field. */
    if (!start) errors.start = [startTime.error ?? "Enter a start time."];
    if (!end) errors.end = [endTime.error ?? "Enter an end time."];
    if (start && end && new Date(end) < new Date(start)) errors.end = ["End time cannot be earlier than start time."];
    /* Picking the other occurrence of a repeated time changes the instant
       without changing the field's text. */
    const moved = (instant: string, was: string | null) => !was || Math.floor(Date.parse(instant) / 1000) !== Math.floor(Date.parse(was) / 1000);
    if (start && (form.start !== initial.start || moved(start, baseline.start))) body.start = start;
    if (end && (form.end !== initial.end || moved(end, baseline.end))) body.end = end;

    if (form.note !== initial.note) body.note = form.note;

    const sameIds = form.subprojectIds.length === baselineIds.length && form.subprojectIds.every((id, i) => id === baselineIds[i]);
    const baselineSplit = baseline.subproject_allocations.map((a) => ({ subproject_id: a.subproject_id, allocation_bp: a.allocation_bp }));
    if (form.subprojectIds.length >= 2) {
      if (allocations && (!sameIds || !sameAllocations(allocations, baselineSplit))) body.subproject_allocations = allocations;
    } else if (!sameIds) {
      body.subproject_ids = form.subprojectIds;
    }

    return Object.keys(errors).length ? { errors } : { body };
  };

  const save = (body: SessionPatch, version?: number) => {
    setBanner(null);
    setFieldErrors({});
    update.mutate(
      { session: baseline, body, version },
      {
        onSuccess: (saved) => {
          toast.success("Updated session");
          reset(saved);
          /* Where the old view redirected: the numeric URL of this session. */
          navigate(urls.updateSession(saved.id), { replace: true });
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 409 && error.code === "version_conflict") {
            const current = (error.details as { current?: SessionRow } | undefined)?.current;
            if (current) {
              setConflict(current);
              return;
            }
          }
          if (error instanceof ApiError && error.details && typeof error.details === "object") {
            const mapped = mapFieldErrors(error.details as Record<string, unknown>);
            if (Object.keys(mapped.fields).length) setFieldErrors(mapped.fields);
            setBanner(mapped.rest.length ? mapped.rest.join(" ") : Object.keys(mapped.fields).length ? "Invalid form data. Please check your inputs." : errorMessage(error));
            return;
          }
          setBanner(errorMessage(error));
        },
      },
    );
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const built = buildPatch();
    if ("errors" in built) {
      setFieldErrors(built.errors);
      setBanner("Invalid form data. Please check your inputs.");
      return;
    }
    if (!Object.keys(built.body).length) {
      toast.info("No changes to save.");
      return;
    }
    save(built.body);
  };

  const conflictBody = () => {
    const built = buildPatch();
    return "body" in built ? built.body : null;
  };

  return (
    <>
      <div className="desk-head">
        <div>
          <h1 className="page-title">{baseline.project.name || "Session"}</h1>
        </div>
      </div>

      {conflict || changedElsewhere ? (
        <div ref={bannerRef} className="msg msg--warning" role="alert" style={{ marginBottom: "var(--s4)" }}>
          <Icon icon={faExclamationTriangle} className="msg-icon" />
          <span>
            This session was changed somewhere else (another tab, the CLI or an assistant) after you opened it.
            {conflict ? " Your changes were not saved." : ""}
          </span>
          <button type="button" className="toast-action" onClick={() => reset(conflict ?? session)}>
            Load latest
          </button>
          {conflict ? (
            <button
              type="button"
              className="toast-action"
              disabled={update.isPending}
              onClick={() => {
                const body = conflictBody();
                if (body) save(body, conflict.version);
              }}
            >
              Save mine anyway
            </button>
          ) : null}
        </div>
      ) : null}
      {banner ? (
        <div ref={bannerRef} className="msg msg--error" role="alert" style={{ marginBottom: "var(--s4)" }}>
          <Icon icon={faExclamationTriangle} className="msg-icon" />
          <span>{banner}</span>
        </div>
      ) : null}

      <form className="fields" onSubmit={submit} noValidate>
        <section className="slab slab-pad">
          <ProjectField
            projects={projects.data ?? []}
            loading={projects.isPending}
            text={form.projectText}
            selectedId={form.projectId}
            onChange={setProject}
            errors={fieldErrors.project}
          />

          <div className="two-up">
            <div className="field">
              <label htmlFor={startId}>Started</label>
              <input
                id={startId}
                type="datetime-local"
                step={1}
                value={form.start}
                onChange={(event) => setForm({ ...form, start: event.target.value })}
              />
              <FieldErrors messages={fieldErrors.start?.filter((message) => message !== startTime.error)} />
              <LocalTimeNotice field={startTime} label="the start" />
            </div>
            <div className="field">
              <label htmlFor={endId}>Ended</label>
              <input
                id={endId}
                type="datetime-local"
                step={1}
                value={form.end}
                onChange={(event) => setForm({ ...form, end: event.target.value })}
              />
              <FieldErrors messages={fieldErrors.end?.filter((message) => message !== endTime.error)} />
              <LocalTimeNotice field={endTime} label="the end" />
            </div>
          </div>

          <NoteEditor rows={10} value={form.note} onChange={(note) => setForm((current) => ({ ...current, note }))} error={fieldErrors.note} />
        </section>

        <section className="slab slab-pad">
          <p className="field-label">Subprojects</p>
          <div className="check-grid" id="subproject_options">
            {form.projectId === null ? (
              <span className="subproject-empty-state" style={{ gridColumn: "1 / -1" }}>Choose a project to pick its subprojects.</span>
            ) : subprojects.isPending ? (
              <span className="subproject-empty-state" style={{ gridColumn: "1 / -1" }}>Loading...</span>
            ) : subprojects.isError ? (
              <span className="subproject-empty-state" style={{ gridColumn: "1 / -1" }}>Could not load subprojects.</span>
            ) : subprojects.data.length === 0 ? (
              <span className="subproject-empty-state" style={{ gridColumn: "1 / -1" }}>This project has no subprojects.</span>
            ) : (
              [...subprojects.data].sort((a, b) => a.id - b.id).map((sub) => (
                <span key={sub.id}>
                  <input
                    type="checkbox"
                    id={`subproject-${sub.id}`}
                    checked={form.subprojectIds.includes(sub.id)}
                    onChange={(event) => toggleSubproject(sub.id, event.target.checked)}
                  />
                  <label htmlFor={`subproject-${sub.id}`}>{sub.name}</label>
                </span>
              ))
            )}
          </div>
          <FieldErrors messages={fieldErrors.subprojects} />
          <AllocationEditor items={items} onChange={setAllocations} />
        </section>

        <div className="form-actions">
          <AppLink className="btn btn--ghost" href={urls.sessions()}>
            <Icon icon={faArrowLeft} /> Back
          </AppLink>
          <button className="btn btn--primary btn--spacer" type="submit" disabled={update.isPending}>
            <Icon icon={faCheckCircle} /> {update.isPending ? "Saving..." : "Save changes"}
          </button>
        </div>
      </form>
    </>
  );
}

function FieldErrors({ messages }: { messages?: string[] }) {
  if (!messages?.length) return null;
  return (
    <ul className="errorlist">
      {messages.map((message) => (
        <li key={message}>{message}</li>
      ))}
    </ul>
  );
}

/* API field errors -> the form's fields; anything else is shown in the banner. */
function mapFieldErrors(details: Record<string, unknown>): { fields: Record<string, string[]>; rest: string[] } {
  const alias: Record<string, string> = {
    project_id: "project",
    start: "start",
    end: "end",
    note: "note",
    subproject_ids: "subprojects",
    subproject_allocations: "subprojects",
  };
  const fields: Record<string, string[]> = {};
  const rest: string[] = [];
  for (const [key, value] of Object.entries(details)) {
    const messages = (Array.isArray(value) ? value : [value]).map((item) => (typeof item === "string" ? item : JSON.stringify(item)));
    const target = alias[key];
    if (target) fields[target] = [...(fields[target] ?? []), ...messages];
    else rest.push(...messages);
  }
  return { fields, rest };
}

/* The shared project picker, plus this form's errors: typing a name that
   matches no project leaves nothing selected, and says so on blur. */
function ProjectField({
  projects,
  loading,
  text,
  selectedId,
  onChange,
  errors,
}: {
  projects: Project[];
  loading: boolean;
  text: string;
  selectedId: number | null;
  onChange: (project: Project | null, text: string) => void;
  errors?: string[];
}) {
  const [focused, setFocused] = useState(false);
  const selected = projects.find((p) => p.id === selectedId) ?? null;
  const unmatched = !focused && text.trim() !== "" && selectedId === null && !loading;
  return (
    <div className="field" onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}>
      <label htmlFor="project-search">Project</label>
      <ProjectCombobox
        id="project-search"
        value={selected}
        onChange={onChange}
        placeholder="Projects"
        invalid={Boolean(errors?.length) || unmatched}
      />
      <FieldErrors messages={errors} />
      {unmatched && !errors?.length ? <ul className="errorlist"><li>No project with that name. Pick one from the list.</li></ul> : null}
    </div>
  );
}
