import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { faArrowLeft, faExclamationTriangle, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { formatDate, formatDurationWords } from "@/lib/format";
import type { ProjectDetail } from "@/api/types";
import { failure, useDeleteProject, useProject } from "./api";
import { conflictCurrent, splitErrors } from "./forms";
import { ConflictBanner, FormErrors, LoadState, PageHead } from "./Parts";

/* "Are you sure?" page kept at its old URL. The server refuses (409) while a
   commitment targets the project; its message is shown as is. */
export default function DeleteProjectPage() {
  const projectId = Number(useParams().projectId);
  const [deleting, setDeleting] = useState(false);
  /* `deleting` stops the record being refetched (and answering 404) between
     the delete and the navigation away. */
  const project = useProject(projectId, !deleting);
  return (
    <LoadState query={project}>
      {project.data ? <ConfirmDelete key={projectId} project={project.data} setDeleting={setDeleting} /> : null}
    </LoadState>
  );
}

function ConfirmDelete({ project, setDeleting }: { project: ProjectDetail; setDeleting: (deleting: boolean) => void }) {
  const navigate = useNavigate();
  const toast = useToast();
  const remove = useDeleteProject();
  /* What the user was shown (or last chose to load): the delete only goes
     through against this version (If-Match). */
  const [shown, setShown] = useState(project);
  const [conflicted, setConflicted] = useState(false);
  const errors = splitErrors(conflicted ? null : remove.error, []);
  const changedElsewhere = project.version !== shown.version;

  const onDelete = () => {
    setDeleting(true);
    remove.mutate(
      { id: shown.id, version: shown.version },
      {
        onSuccess: () => {
          toast.success("Project deleted successfully");
          navigate(urls.projects());
        },
        onError: (error) => {
          setDeleting(false);
          if (conflictCurrent(error)) setConflicted(true);
          else toast.error(failure("delete the project", error));
        },
      },
    );
  };

  return (
    <>
      <PageHead title="Delete project?" />
      {conflicted || changedElsewhere ? (
        <ConflictBanner
          noun="project"
          outcome={conflicted ? "It was not deleted." : undefined}
          onLoadLatest={() => {
            setShown(project);
            setConflicted(false);
            remove.reset();
          }}
        />
      ) : null}
      <FormErrors errors={errors} />
      <section className="slab slab-pad">
        <div className="project-top">
          <span className="project-name text-red">{shown.name}</span>
          <span className="muted">{shown.status}</span>
        </div>
        {shown.description ? <p className="focus-lede">{shown.description}</p> : null}
        <p className="project-total">{formatDurationWords(shown.total_minutes)}</p>
        <p className="project-dates">
          {formatDate(shown.start_date)} &rarr; {formatDate(shown.last_activity)}
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
  );
}
