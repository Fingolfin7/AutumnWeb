import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { faArrowLeft, faExclamationTriangle, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { formatDate, formatDurationWords } from "@/lib/format";
import { failure, useDeleteProject, useProject } from "./api";
import { splitErrors } from "./forms";
import { FormErrors, LoadState, PageHead } from "./Parts";

/* "Are you sure?" page kept at its old URL. The server refuses (409) while a
   commitment targets the project; its message is shown as is. */
export default function DeleteProjectPage() {
  const projectId = Number(useParams().projectId);
  const navigate = useNavigate();
  const toast = useToast();
  const [deleting, setDeleting] = useState(false);
  const project = useProject(projectId, !deleting);
  const remove = useDeleteProject();
  const errors = splitErrors(remove.error, []);

  const onDelete = () => {
    setDeleting(true);
    remove.mutate(projectId, {
      onSuccess: () => {
        toast.success("Project deleted successfully");
        navigate(urls.projects());
      },
      onError: (error) => {
        setDeleting(false);
        toast.error(failure("delete the project", error));
      },
    });
  };

  return (
    <LoadState query={project}>
      {project.data ? (
        <>
          <PageHead title="Delete project?" />
          <FormErrors errors={errors} />
          <section className="slab slab-pad">
            <div className="project-top">
              <span className="project-name text-red">{project.data.name}</span>
              <span className="muted">{project.data.status}</span>
            </div>
            {project.data.description ? <p className="focus-lede">{project.data.description}</p> : null}
            <p className="project-total">{formatDurationWords(project.data.total_minutes)}</p>
            <p className="project-dates">
              {formatDate(project.data.start_date)} &rarr; {formatDate(project.data.last_activity)}
            </p>
          </section>

          <p className="confirm-warn">
            <Icon icon={faExclamationTriangle} /> This deletes the project, its subprojects and every session recorded against them. It cannot be
            undone.
          </p>

          <div className="form-actions">
            <AppLink className="btn btn--ghost" href={urls.projects()}>
              <Icon icon={faArrowLeft} /> Back
            </AppLink>
            <button className="btn btn--stop btn--spacer" type="button" onClick={onDelete} disabled={remove.isPending}>
              <Icon icon={faTrash} /> Delete project
            </button>
          </div>
        </>
      ) : null}
    </LoadState>
  );
}
