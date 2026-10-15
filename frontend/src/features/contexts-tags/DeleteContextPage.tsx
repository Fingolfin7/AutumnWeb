import { useParams, useNavigate } from "react-router";
import { faArrowLeft, faExclamationTriangle, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { useContextById, useDeleteContext } from "./api";
import { DeskHead } from "./ui";

/* "Delete context?" confirmation (templates/core/delete_context.html). */
export default function DeleteContextPage() {
  const id = Number(useParams().contextId);
  const navigate = useNavigate();
  const toast = useToast();
  const { query, item, missing } = useContextById(id);
  const remove = useDeleteContext();

  if (query.isPending) {
    return (
      <>
        <DeskHead title="Delete context?" />
        <section className="slab">
          <Skeleton lines={3} />
        </section>
      </>
    );
  }
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (missing || !item) {
    return (
      <>
        <DeskHead title="Delete context?" />
        <section className="slab slab-pad">
          <Empty>That context no longer exists.</Empty>
          <AppLink className="btn btn--ghost" href={urls.contexts()}>
            <Icon icon={faArrowLeft} /> Back
          </AppLink>
        </section>
      </>
    );
  }

  const confirm = () =>
    remove.mutate(item.id, {
      onSuccess: () => {
        toast.success("Context deleted successfully");
        navigate(urls.contexts());
      },
    });

  return (
    <>
      <DeskHead title="Delete context?" />
      <section className="slab slab-pad" id={`context-${item.id}`}>
        <p className="confirm-lede">
          <span className="context-chip">{item.name}</span>
        </p>
        {item.description ? <p className="focus-lede">{item.description}</p> : null}
        <p className="muted">
          Used by <span className="mono tnum">{item.project_count}</span> {item.project_count === 1 ? "project" : "projects"}.
        </p>
      </section>

      <p className="confirm-warn">
        <Icon icon={faExclamationTriangle} /> Projects using this context will lose the association. This cannot be undone.
      </p>

      {remove.isError ? (
        <p className="confirm-warn" role="alert">
          {errorMessage(remove.error)}
        </p>
      ) : null}

      <div className="form-actions">
        <AppLink className="btn btn--ghost" href={urls.contexts()}>
          <Icon icon={faArrowLeft} /> Back
        </AppLink>
        <button type="button" className="btn btn--stop btn--spacer" onClick={confirm} disabled={remove.isPending}>
          <Icon icon={faTrash} /> Delete context
        </button>
      </div>
    </>
  );
}
