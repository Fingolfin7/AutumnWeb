import { useMemo, useState, type FormEvent } from "react";
import { useParams } from "react-router";
import { faCheckCircle, faCodeBranch, faPen, faPlus, faSitemap, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
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

  const average = project.session_count > 0 ? project.total_minutes / project.session_count : 0;

  return (
    <>
      <PageHead title={project.name} titleClass="text-red" />

      {conflict || changedElsewhere ? (
        <ConflictBanner
          noun="project"
          outcome={conflict ? "Your changes were not saved." : undefined}
          onLoadLatest={() => reset(conflict ? { ...project, ...conflict } : project)}
          onSaveAnyway={conflict ? () => save(changes(), conflict.version) : undefined}
          busy={update.isPending}
        />
      ) : null}

      <div className="split">
        <form className="fields" onSubmit={onSubmit}>
          <FormErrors errors={errors} />
          <section className="slab slab-pad">
            <ProjectFields values={values} onChange={setValues} errors={errors} showStatus />
            <div className="form-actions">
              <button className="btn btn--primary" type="submit" id="update-project" disabled={update.isPending}>
                <Icon icon={faCheckCircle} /> Save changes
              </button>
              <AppLink className="btn btn--ghost btn--spacer" href={urls.deleteProject(project.id)}>
                <Icon icon={faTrash} /> Delete project
              </AppLink>
            </div>
          </section>
        </form>

        <section className="slab slab-pad">
          <div className="meta-list">
            <div className="meta-row">
              <span className="meta-label">Total time</span>
              <span className="meta-value text-green">{formatDurationWords(project.total_minutes)}</span>
            </div>
            <div className="meta-row">
              <span className="meta-label">Sessions</span>
              <span className="meta-value">{project.session_count}</span>
            </div>
            <div className="meta-row">
              <span className="meta-label">Average session</span>
              <span className="meta-value text-green">{formatDurationWords(average)}</span>
            </div>
            <div className="meta-row">
              <span className="meta-label">Created</span>
              <span className="meta-value text-cyan">{formatDate(project.start_date)}</span>
            </div>
            <div className="meta-row">
              <span className="meta-label">Last updated</span>
              <span className="meta-value text-cyan">{formatDate(project.last_activity)}</span>
            </div>
          </div>
        </section>
      </div>

      <CommitmentsPanel
        commitments={related}
        addUrl={urls.createCommitment(project.id)}
        entityLabel="project"
        knownSubprojects={knownSubprojects}
      />

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
                  {sub.last_activity ? <p className="project-dates">Last active {formatDate(sub.last_activity)}</p> : null}
                </div>
                <div className="u-row u-gap-2">
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
          <AppLink className="btn btn--primary" href={urls.createSubproject(project.id)}>
            <Icon icon={faPlus} /> New subproject
          </AppLink>
          {project.subprojects.length ? (
            <AppLink className="btn btn--ghost" href={urls.mergeSubprojects(project.id)}>
              <Icon icon={faCodeBranch} /> Merge
            </AppLink>
          ) : null}
        </div>
      </Disclose>
    </>
  );
}
