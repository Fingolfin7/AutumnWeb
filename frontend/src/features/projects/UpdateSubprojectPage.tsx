import { useMemo, useState, type FormEvent } from "react";
import { useParams } from "react-router";
import { faCheckCircle, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { formatDate, formatDurationWords } from "@/lib/format";
import type { Subproject } from "@/api/types";
import { failure, useCommitments, useFirstSessionDate, useProject, useSubproject, useUpdateSubproject } from "./api";
import { CommitmentsPanel } from "./CommitmentsPanel";
import { splitErrors } from "./forms";
import { commitmentAppliesToSubproject, sortCommitments } from "./logic";
import { FieldError, FormErrors, LoadState, PageHead } from "./Parts";

const FIELDS = ["name", "description"];

export default function UpdateSubprojectPage() {
  const subprojectId = Number(useParams().subprojectId);
  const subproject = useSubproject(subprojectId);
  const project = useProject(subproject.data?.project_id ?? 0);
  const ready = subproject.data && project.data;
  /* The parent project is only needed once the subproject is known. */
  const query = subproject.isError || !subproject.data ? subproject : project;
  return (
    <LoadState query={query}>
      {ready ? <SubprojectView key={subprojectId} subproject={subproject.data!} projectName={project.data!.name} /> : null}
    </LoadState>
  );
}

function SubprojectView({ subproject, projectName }: { subproject: Subproject; projectName: string }) {
  const toast = useToast();
  const update = useUpdateSubproject(subproject.id);
  const { data: project } = useProject(subproject.project_id);
  const commitments = useCommitments();
  const first = useFirstSessionDate(subproject.id, subproject.session_count);
  const [name, setName] = useState(subproject.name);
  const [description, setDescription] = useState(subproject.description);
  const errors = splitErrors(update.error, FIELDS, "name");

  const related = useMemo(() => {
    if (!project) return [];
    const scope = {
      id: project.id,
      contextId: project.context?.id ?? null,
      tagIds: project.tags.map((tag) => tag.id),
      subprojectIds: project.subprojects.map((sub) => sub.id),
    };
    return sortCommitments((commitments.data ?? []).filter((c) => commitmentAppliesToSubproject(c, scope, subproject.id)));
  }, [commitments.data, project, subproject.id]);
  const known = useMemo(() => new Map((project?.subprojects ?? []).map((sub) => [sub.id, sub.name] as const)), [project]);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const patch: { name?: string; description?: string } = {};
    if (name.trim() !== subproject.name) patch.name = name.trim();
    if (description !== subproject.description) patch.description = description;
    if (!Object.keys(patch).length) {
      toast.info("Nothing to save.");
      return;
    }
    update.mutate(patch, {
      onSuccess: (saved) => {
        setName(saved.name);
        toast.success("Subproject updated successfully");
      },
      onError: (error) => {
        if (splitErrors(error, FIELDS, "name").general.length) toast.error(failure("save the subproject", error));
      },
    });
  };

  const average = subproject.session_count > 0 ? subproject.total_minutes / subproject.session_count : 0;

  return (
    <>
      <PageHead
        eyebrow={
          <AppLink className="text-red" href={urls.updateProject(subproject.project_id)}>
            {projectName}
          </AppLink>
        }
        title={subproject.name}
        titleClass="text-blue"
      />

      <div className="split">
        <form className="fields" onSubmit={onSubmit}>
          <FormErrors errors={errors} />
          <section className="slab slab-pad">
            <div className="field">
              <label htmlFor="id_name">Name</label>
              <input id="id_name" type="text" placeholder="Subproject Name" maxLength={255} required value={name} onChange={(e) => setName(e.target.value)} />
              <FieldError message={errors.fields.name} />
            </div>

            <div className="field">
              <label htmlFor="id_description">Description</label>
              <textarea id="id_description" placeholder="Description" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
              <FieldError message={errors.fields.description} />
            </div>

            <div className="form-actions">
              <button className="btn btn--primary" type="submit" id="update-subproject" disabled={update.isPending}>
                <Icon icon={faCheckCircle} /> Save changes
              </button>
              <AppLink className="btn btn--ghost btn--spacer" href={urls.deleteSubproject(subproject.id)}>
                <Icon icon={faTrash} /> Delete subproject
              </AppLink>
            </div>
          </section>
        </form>

        <section className="slab slab-pad">
          <div className="meta-list">
            <div className="meta-row">
              <span className="meta-label">Project</span>
              <AppLink className="meta-value text-red" href={urls.updateProject(subproject.project_id)}>
                {projectName}
              </AppLink>
            </div>
            <div className="meta-row">
              <span className="meta-label">Total time</span>
              <span className="meta-value text-green">{formatDurationWords(subproject.total_minutes)}</span>
            </div>
            <div className="meta-row">
              <span className="meta-label">Sessions</span>
              <span className="meta-value">{subproject.session_count}</span>
            </div>
            <div className="meta-row">
              <span className="meta-label">Average session</span>
              <span className="meta-value text-green">{formatDurationWords(average)}</span>
            </div>
            {/* The API has no creation date for subprojects: show the first session instead. */}
            <div className="meta-row">
              <span className="meta-label">First session</span>
              <span className="meta-value text-cyan">{first.data ? formatDate(first.data) : "—"}</span>
            </div>
            <div className="meta-row">
              <span className="meta-label">Last updated</span>
              <span className="meta-value text-cyan">{formatDate(subproject.last_activity)}</span>
            </div>
          </div>
        </section>
      </div>

      <CommitmentsPanel
        commitments={related}
        addUrl={`${urls.createCommitment()}?aggregation_type=subproject&target_id=${subproject.id}`}
        entityLabel="subproject"
        knownSubprojects={known}
      />
    </>
  );
}
