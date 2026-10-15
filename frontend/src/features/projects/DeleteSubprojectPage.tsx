import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { faArrowLeft, faExclamationTriangle, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { formatDate, formatDurationWords } from "@/lib/format";
import type { ProjectDetail, Subproject } from "@/api/types";
import { failure, useDeleteSubproject, useProject, useSubproject } from "./api";
import { conflictCurrent, splitErrors } from "./forms";
import { ConflictBanner, FormErrors, LoadState, PageHead } from "./Parts";

/* "Are you sure?" page kept at its old URL; a 409 from a commitment that
   targets the subproject shows the server's message. */
export default function DeleteSubprojectPage() {
  const subprojectId = Number(useParams().subprojectId);
  const [deleting, setDeleting] = useState(false);
  /* `deleting` stops the records being refetched (and answering 404) between
     the delete and the navigation away. */
  const subproject = useSubproject(subprojectId, !deleting);
  const project = useProject(subproject.data?.project_id ?? 0, !deleting);
  const query = subproject.isError || !subproject.data ? subproject : project;
  return (
    <LoadState query={query}>
      {subproject.data && project.data ? (
        <ConfirmDelete key={subprojectId} subproject={subproject.data} parent={project.data} setDeleting={setDeleting} />
      ) : null}
    </LoadState>
  );
}

function ConfirmDelete({
  subproject,
  parent,
  setDeleting,
}: {
  subproject: Subproject;
  parent: ProjectDetail;
  setDeleting: (deleting: boolean) => void;
}) {
  const navigate = useNavigate();
  const toast = useToast();
  const remove = useDeleteSubproject();
  /* What the user was shown (or last chose to load): the delete only goes
     through against this version (If-Match). */
  const [shown, setShown] = useState(subproject);
  const [conflicted, setConflicted] = useState(false);
  const errors = splitErrors(conflicted ? null : remove.error, []);
  const changedElsewhere = subproject.version !== shown.version;

  const onDelete = () => {
    setDeleting(true);
    remove.mutate(
      { id: shown.id, version: shown.version },
      {
        onSuccess: () => {
          toast.success("Subproject deleted successfully");
          navigate(urls.projects());
        },
        onError: (error) => {
          setDeleting(false);
          if (conflictCurrent(error)) setConflicted(true);
          else toast.error(failure("delete the subproject", error));
        },
      },
    );
  };

  return (
    <>
      <PageHead
        eyebrow={
          <AppLink className="text-red" href={urls.updateProject(parent.id)}>
            {parent.name}
          </AppLink>
        }
        title="Delete subproject?"
      />
      {conflicted || changedElsewhere ? (
        <ConflictBanner
          noun="subproject"
          outcome={conflicted ? "It was not deleted." : undefined}
          onLoadLatest={() => {
            setShown(subproject);
            setConflicted(false);
            remove.reset();
          }}
        />
      ) : null}
      <FormErrors errors={errors} />
      <section className="slab slab-pad">
        <div className="project-top">
          <span className="project-name text-blue">{shown.name}</span>
        </div>
        {shown.description ? <p className="focus-lede">{shown.description}</p> : null}
        <p className="project-total">{formatDurationWords(shown.total_minutes)}</p>
        {shown.last_activity ? <p className="project-dates">Last active {formatDate(shown.last_activity)}</p> : null}
      </section>

      <p className="confirm-warn">
        <Icon icon={faExclamationTriangle} /> Sessions recorded against this subproject lose it. It cannot be undone.
      </p>

      <div className="form-actions">
        <AppLink className="btn btn--ghost" href={urls.updateProject(parent.id)}>
          <Icon icon={faArrowLeft} /> Back
        </AppLink>
        <button className="btn btn--stop btn--spacer" type="button" onClick={onDelete} disabled={remove.isPending}>
          <Icon icon={faTrash} /> Delete subproject
        </button>
      </div>
    </>
  );
}
