import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";
import { faArrowLeft, faCheckCircle } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { usePickerProjects, useTags } from "@/api/meta";
import type { Project } from "@/api/types";
import { resolveId } from "@/lib/offlineQueue";
import { failure, useCreateSubproject, useProject } from "./api";
import { splitErrors } from "./forms";
import { FieldError, FormErrors, LoadState, PageHead } from "./Parts";

export default function CreateSubprojectPage() {
  /* A project created offline has a temporary id until it syncs. The saved
     project list stands in for its details with no connection. */
  const projectId = resolveId(Number(useParams().projectId));
  const project = useProject(projectId);
  const listed = usePickerProjects().data?.find((p) => p.id === projectId);
  const shown = project.data ?? listed;
  if (shown) return <CreateSubprojectForm project={shown} />;
  return <LoadState query={project}>{null}</LoadState>;
}

function CreateSubprojectForm({ project }: { project: Project }) {
  const navigate = useNavigate();
  const toast = useToast();
  const tags = useTags();
  const create = useCreateSubproject(project);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const errors = splitErrors(create.error, ["name", "description"], "name");
  const back = project.pending_sync ? urls.projects() : urls.updateProject(project.id);

  const tagColor = (id: number) => tags.data?.find((tag) => tag.id === id)?.color;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate(
      { name: name.trim(), description },
      {
        onSuccess: (result) => {
          if (result === "queued") toast.info(`Saved ${name.trim()} on this device. It syncs when Autumn can be reached.`);
          else toast.success("Subproject created successfully");
          navigate(urls.projects());
        },
        onError: (error) => {
          if (splitErrors(error, ["name", "description"], "name").general.length) toast.error(failure("create the subproject", error));
        },
      },
    );
  };

  return (
    <>
      <PageHead
        eyebrow={
          <AppLink className="text-red" href={back}>
            {project.name}
          </AppLink>
        }
        title="New subproject"
      />
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

          {project.context || project.tags.length ? (
            <div className="field">
              <span className="field-label">Inherited from {project.name}</span>
              <div className="project-meta">
                {project.context ? <span className="context-chip">{project.context.name}</span> : null}
                {project.tags.map((tag) => {
                  const color = tagColor(tag.id);
                  return (
                    <span key={tag.id} className="tag-chip" style={color ? ({ "--tag": color } as React.CSSProperties) : undefined}>
                      {tag.name}
                    </span>
                  );
                })}
              </div>
            </div>
          ) : null}
        </section>

        <div className="form-actions">
          <AppLink className="btn btn--ghost" href={back}>
            <Icon icon={faArrowLeft} /> Back
          </AppLink>
          <button className="btn btn--primary btn--spacer" type="submit" id="create-subproject" disabled={create.isPending}>
            <Icon icon={faCheckCircle} /> Create subproject
          </button>
        </div>
      </form>
    </>
  );
}
