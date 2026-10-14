import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { faArrowLeft, faExclamationTriangle, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { formatDate, formatDurationWords } from "@/lib/format";
import { failure, useDeleteSubproject, useProject, useSubproject } from "./api";
import { splitErrors } from "./forms";
import { FormErrors, LoadState, PageHead } from "./Parts";

/* "Are you sure?" page kept at its old URL; a 409 from a commitment that
   targets the subproject shows the server's message. */
export default function DeleteSubprojectPage() {
  const subprojectId = Number(useParams().subprojectId);
  const navigate = useNavigate();
  const toast = useToast();
  const [deleting, setDeleting] = useState(false);
  const subproject = useSubproject(subprojectId, !deleting);
  const project = useProject(subproject.data?.project_id ?? 0, !deleting);
  const remove = useDeleteSubproject();
  const errors = splitErrors(remove.error, []);
  const query = subproject.isError || !subproject.data ? subproject : project;
  const sub = subproject.data;
  const parent = project.data;

  const onDelete = () => {
    setDeleting(true);
    remove.mutate(subprojectId, {
      onSuccess: () => {
        toast.success("Subproject deleted successfully");
        navigate(urls.projects());
      },
      onError: (error) => {
        setDeleting(false);
        toast.error(failure("delete the subproject", error));
      },
    });
  };

  return (
    <LoadState query={query}>
      {sub && parent ? (
        <>
          <PageHead
            eyebrow={
              <AppLink className="text-red" href={urls.updateProject(parent.id)}>
                {parent.name}
              </AppLink>
            }
            title="Delete subproject?"
          />
          <FormErrors errors={errors} />
          <section className="slab slab-pad">
            <div className="project-top">
              <span className="project-name text-blue">{sub.name}</span>
            </div>
            {sub.description ? <p className="focus-lede">{sub.description}</p> : null}
            <p className="project-total">{formatDurationWords(sub.total_minutes)}</p>
            {sub.last_activity ? <p className="project-dates">Last active {formatDate(sub.last_activity)}</p> : null}
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
      ) : null}
    </LoadState>
  );
}
