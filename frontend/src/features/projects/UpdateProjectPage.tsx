import { useMemo, useState, type FormEvent } from "react";
import { useParams } from "react-router";
import { faCheckCircle, faCodeBranch, faPlay, faPen, faPlus, faSitemap, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Sheet } from "@/components/Sheet";
import { SessionBand } from "@/features/sessions/SessionBand";
import { SessionNote } from "@/components/SessionNote";
import { useSessionList, useSessionTotals } from "@/features/sessions/api";

import { useStartTimer } from "@/features/timers/api";
import { Disclose } from "@/components/Disclose";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { formatDate, formatDurationWords } from "@/lib/format";
import type { Project, ProjectDetail } from "@/api/types";
import { useCommitmentsAppliedTo } from "@/features/commitments/api";
import { failure, useProject, useUpdateProject } from "./api";
import { CommitmentsPanel } from "./CommitmentsPanel";
import { conflictCurrent, splitErrors } from "./forms";
import { changedFields, type ProjectValues } from "./logic";
import { ConflictBanner, FormErrors, LoadState, PageHead, ProjectFields } from "./Parts";

const FIELDS = ["name", "description", "status", "context_id", "tag_ids"];

const toValues = (project: ProjectDetail): ProjectValues => ({
  name: project.name,
  description: project.description,
  status: project.status,
  context_id: project.context?.id ?? null,
  tag_ids: project.tags.map((tag) => tag.id),
});

export default function UpdateProjectPage() {
  const projectId = Number(useParams().projectId);
  const project = useProject(projectId);
  return <LoadState query={project}>{project.data ? <ProjectDetailView key={projectId} project={project.data} /> : null}</LoadState>;
}

function ProjectDetailView({ project }: { project: ProjectDetail }) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const start = useStartTimer();
  const recent = useSessionList({ project_ids: String(project.id) });
  const monday = new Date();
  monday.setDate(monday.getDate() - (monday.getDay() + 6) % 7);
  const weekStart = `${monday.getFullYear()}-${String(monday.getMonth() + 1).padStart(2, "0")}-${String(monday.getDate()).padStart(2, "0")}`;
  const week = useSessionTotals({ project_ids: String(project.id), start_date: weekStart });
  const update = useUpdateProject(project.id);
  const related = useCommitmentsAppliedTo("project", project.id).data ?? [];
  /* The project as the form was opened (or last saved/reloaded): the edit is
     diffed against it and the PATCH carries its version (If-Match). */
  const [baseline, setBaseline] = useState(project);
  const [values, setValues] = useState<ProjectValues>(() => toValues(project));
  const [conflict, setConflict] = useState<Project | null>(null);
  const errors = splitErrors(conflict ? null : update.error, FIELDS, "name");
  const changedElsewhere = project.version !== baseline.version;

  const reset = (from: ProjectDetail) => {
    setBaseline(from);
    setValues(toValues(from));
    setConflict(null);
    update.reset();
  };

  const knownSubprojects = useMemo(() => new Map(project.subprojects.map((sub) => [sub.id, sub.name] as const)), [project.subprojects]);

  const save = (patch: Partial<ProjectValues>, version: number | undefined) => {
    update.mutate(
      { patch, version },
      {
        onSuccess: (saved) => {
          setBaseline((current) => ({ ...current, ...saved }));
          setConflict(null);
          setEditing(false);
          setValues((current) => ({ ...current, name: saved.name }));
          /* The server words it (core/services/celebrations.py), the same as
             the CLI and MCP see. */
          if (saved.celebration) {
            toast.success(saved.celebration.message, { celebration: "completion" });
          } else {
            toast.success("Project updated successfully");
          }
        },
        onError: (error) => {
          const current = conflictCurrent<Project>(error);
          if (current) setConflict(current);
          else if (splitErrors(error, FIELDS, "name").general.length) toast.error(failure("save the project", error));
        },
      },
    );
  };

  const changes = () => changedFields(toValues(baseline), { ...values, name: values.name.trim() });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const patch = changes();
    if (!Object.keys(patch).length) {
      toast.info("Nothing to save.");
      return;
    }
    save(patch, baseline.version);
  };

  return (
    <>
      <div className="project-overview">
        <div className="desk-head project-page-head">
          <PageHead title={project.name} titleClass="text-red" />
          <button type="button" className="btn btn--quiet" onClick={() => { reset(project); setEditing(true); }}><Icon icon={faPen} /> Edit project</button>
        </div>
        <section className="slab slab-pad project-hero" aria-label="Project overview">
          <button className="btn btn--primary" type="button" disabled={start.isPending} onClick={() => start.mutate({ project_id: project.id, optimistic: { projectName: project.name, subprojects: [] } }, { onSuccess: () => toast.success(`Started ${project.name}.`), onError: (error) => toast.error(failure("start the timer", error)) })}><Icon icon={faPlay} /> Start timer</button>
          <div className="project-stat"><span>This week</span><strong>{week.data ? formatDurationWords(week.data.total_minutes) : "…"}</strong></div>
          <div className="project-stat"><span>Total time</span><strong>{formatDurationWords(project.total_minutes)}</strong></div>
          <span className="muted">{project.session_count} sessions</span>
          {project.description ? <div className="project-description"><SessionNote text={project.description} /></div> : null}
        </section>
        <Sheet open={editing} onClose={() => setEditing(false)} title="Edit project" className="project-edit-sheet">

        {conflict || changedElsewhere ? (
          <ConflictBanner
            noun="project"
            outcome={conflict ? "Your changes were not saved." : undefined}
            onLoadLatest={() => reset(conflict ? { ...project, ...conflict } : project)}
            onSaveAnyway={conflict ? () => save(changes(), conflict.version) : undefined}
            busy={update.isPending}
          />
        ) : null}


          <form className="fields" onSubmit={onSubmit}>
            <FormErrors errors={errors} />
            <section>
              <p className="muted project-history">Created {formatDate(project.start_date)}. Last active {formatDate(project.last_activity) || "never"}. Average session {formatDurationWords(project.session_count ? project.total_minutes / project.session_count : 0)}.</p>
              <ProjectFields values={values} onChange={setValues} errors={errors} showStatus />
              <div className="form-actions">
                <button className="btn btn--primary" type="submit" id="update-project" disabled={update.isPending}>
                  <Icon icon={faCheckCircle} /> Save changes
                </button>
                <AppLink className="btn btn--danger btn--spacer" href={urls.deleteProject(project.id)}>
                  <Icon icon={faTrash} /> Delete project
                </AppLink>
                <AppLink className="btn btn--quiet" href={urls.mergeProjects()}><Icon icon={faCodeBranch} /> Merge projects</AppLink>
              </div>
            </section>
          </form>

        </Sheet>

        <CommitmentsPanel
          commitments={related}
          addUrl={urls.createCommitment(project.id)}
          entityLabel="project"
          knownSubprojects={knownSubprojects}
        />

        <section className="slab session-list project-journal" aria-label="Recent journal entries">
          <header className="day-head"><h2 className="day-date">Recent journal entries</h2><AppLink className="btn btn--quiet" href={`${urls.sessions()}?include_projects=${project.id}`}>All sessions</AppLink></header>
          {recent.isError ? <p className="slab-pad muted">Could not load journal entries. <button type="button" className="btn btn--quiet" onClick={() => void recent.refetch()}>Try again</button></p> : recent.isPending ? <p className="slab-pad muted">Loading entries…</p> : recent.data?.pages[0]?.sessions.length ? <ul className="band-list">{recent.data.pages[0].sessions.slice(0, 5).map((session) => <SessionBand key={session.id} session={session} showDate />)}</ul> : <p className="empty">Your first session will appear here.</p>}
        </section>
        <Disclose id="project-subprojects" icon={faSitemap} iconClass="text-blue" title="Subprojects" summary={project.subprojects.length}>
          {project.subprojects.length ? (
            <ul className="band-list">
              {project.subprojects.map((sub) => (
                <li className="band project" id={`subproject-${sub.id}`} key={sub.id}>
                  <div className="u-grow">
                    <div className="project-top">
                      <AppLink className="project-name text-blue" href={urls.updateSubproject(sub.id)}>
                        {sub.name}
                      </AppLink>
                    </div>
                    <p className="project-total">{formatDurationWords(sub.total_minutes)}</p>
                    <progress className="subproject-progress" max={Math.max(project.total_minutes, sub.total_minutes, 1)} value={sub.total_minutes} aria-label={`${sub.name} share of total time`} />
                    {sub.last_activity ? <p className="project-dates">Last active {formatDate(sub.last_activity)}</p> : null}
                  </div>
                  <div className="u-row u-gap-2">
                    <button className="btn btn--secondary" type="button" disabled={start.isPending} onClick={() => start.mutate({ project_id: project.id, subproject_ids: [sub.id], optimistic: { projectName: project.name, subprojects: [{ id: sub.id, name: sub.name }] } }, { onSuccess: () => toast.success(`Started ${sub.name}.`), onError: (error) => toast.error(failure("start the timer", error)) })}><Icon icon={faPlay} /> Start<span className="sr-only"> {sub.name}</span></button>
                    <AppLink className="btn-icon" href={urls.updateSubproject(sub.id)} title="Edit subproject">
                      <Icon icon={faPen} />
                      <span className="sr-only">Edit {sub.name}</span>
                    </AppLink>
                    <AppLink className="btn-icon btn-icon--danger" href={urls.deleteSubproject(sub.id)} title="Delete subproject">
                      <Icon icon={faTrash} />
                      <span className="sr-only">Delete {sub.name}</span>
                    </AppLink>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty">No subprojects yet.</p>
          )}

          <div className="slab-foot action-row">
            <AppLink className="btn btn--secondary" href={urls.createSubproject(project.id)}>
              <Icon icon={faPlus} /> New subproject
            </AppLink>
            {project.subprojects.length ? (
              <AppLink className="btn btn--ghost" href={urls.mergeSubprojects(project.id)}>
                <Icon icon={faCodeBranch} /> Merge
              </AppLink>
            ) : null}
          </div>
        </Disclose>

      </div>
    </>
  );
}
